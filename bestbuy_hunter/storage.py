"""SQLite-backed price history + alert audit log.

Replaces the old JSON store. Using SQLite (Python stdlib — no extra software)
gives us indexed time-series queries, robust statistics, a daily rollup to keep
the file small, and an audit trail of what we alerted on.

Schema
------
products      one row per tracked product (metadata + MSRP baseline)
price_samples one row per observation per cycle (the raw time series)
daily_rollup  compacted daily min/median/high for samples older than raw_days
alerts        audit log of every deal we pushed (dedupe-friendly, hit-rate stats)

The store records *every cycle* (not only on price change) so the glitch
detector's history-based signals warm up predictably over time.
"""
from __future__ import annotations

import logging
import sqlite3
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .models import Deal

log = logging.getLogger("bestbuy_hunter.storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_key TEXT PRIMARY KEY,
    retailer    TEXT,
    product_id  TEXT,
    name        TEXT,
    url         TEXT,
    bucket      TEXT,
    msrp        REAL DEFAULT 0,
    gpu_tier    INTEGER DEFAULT 0,
    last_seen   INTEGER
);
CREATE TABLE IF NOT EXISTS price_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    price       REAL NOT NULL,
    in_stock    INTEGER DEFAULT 1,
    condition   TEXT
);
CREATE INDEX IF NOT EXISTS idx_samples_key_ts ON price_samples(product_key, ts);
CREATE TABLE IF NOT EXISTS daily_rollup (
    product_key TEXT NOT NULL,
    day         INTEGER NOT NULL,
    low         REAL,
    median      REAL,
    high        REAL,
    samples     INTEGER,
    PRIMARY KEY (product_key, day)
);
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key  TEXT,
    product_key TEXT,
    ts          INTEGER,
    price       REAL,
    kind        TEXT,
    confidence  REAL,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_key ON alerts(dedupe_key);
"""


@dataclass
class PriceStats:
    """Summary statistics for a product's price history."""

    count: int                       # total observations (raw + rolled-up)
    low: Optional[float]             # lowest price ever recorded
    median: Optional[float]          # median of the baseline distribution
    last: Optional[float]            # most recent raw sample
    mean: Optional[float] = None
    stdev: Optional[float] = None
    mad: Optional[float] = None      # median absolute deviation (robust spread)
    prev: Optional[float] = None     # the sample just before ``last`` (rate-of-change)


class PriceStore:
    def __init__(self, path: Path, raw_days: int = 7, retention_days: int = 90) -> None:
        self.path = path
        self.raw_seconds = raw_days * 86400
        self.retention_seconds = retention_days * 86400
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Let concurrent access (e.g. the dashboard reading while the watcher
        # writes) wait briefly for a lock instead of erroring out.
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------ #
    def record(self, deals: Iterable[Deal], now: Optional[float] = None) -> None:
        """Insert one sample per product this cycle (lowest current offer wins)."""
        ts = int(now if now is not None else time.time())
        # Collapse multiple offers of the same product to its lowest price.
        best: dict[str, Deal] = {}
        for d in deals:
            if not d.price or d.price <= 0:
                continue
            key = d.history_key
            if key not in best or d.price < best[key].price:
                best[key] = d

        cur = self.conn.cursor()
        for key, d in best.items():
            cur.execute(
                """
                INSERT INTO products (product_key, retailer, product_id, name, url,
                                      bucket, msrp, gpu_tier, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_key) DO UPDATE SET
                    name=excluded.name, url=excluded.url, bucket=excluded.bucket,
                    gpu_tier=excluded.gpu_tier, last_seen=excluded.last_seen,
                    msrp=MAX(COALESCE(products.msrp, 0), excluded.msrp)
                """,
                (key, d.retailer, d.product_id, d.name, d.url, d.bucket,
                 float(d.regular or 0.0), int(d.gpu_tier), ts),
            )
            cur.execute(
                "INSERT INTO price_samples (product_key, ts, price, in_stock, condition) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, ts, round(float(d.price), 2), 1, d.condition),
            )
        self.conn.commit()

    # ------------------------------------------------------------------ #
    def stats(self, product_key: str, exclude_last: bool = True) -> PriceStats:
        """Compute history statistics from raw samples + daily rollups.

        ``exclude_last`` drops the most recent raw sample from the baseline so a
        current (possibly glitched) price isn't compared against itself.
        """
        raw = [r[0] for r in self.conn.execute(
            "SELECT price FROM price_samples WHERE product_key=? ORDER BY ts", (product_key,))]
        rollups = self.conn.execute(
            "SELECT low, median, samples FROM daily_rollup WHERE product_key=? ORDER BY day",
            (product_key,)).fetchall()

        last = raw[-1] if raw else None
        prev = raw[-2] if len(raw) >= 2 else None
        baseline_raw = raw[:-1] if (exclude_last and len(raw) > 1) else raw

        points = list(baseline_raw) + [m for (_lo, m, _s) in rollups if m is not None]
        lows = list(baseline_raw) + [lo for (lo, _m, _s) in rollups if lo is not None]
        count = len(raw) + sum(int(s or 0) for (_lo, _m, s) in rollups)

        if not points:
            return PriceStats(count=count, low=(min(lows) if lows else None),
                              median=None, last=last, prev=prev)

        median = statistics.median(points)
        mad = statistics.median([abs(p - median) for p in points]) if len(points) >= 2 else 0.0
        return PriceStats(
            count=count,
            low=min(lows) if lows else None,
            median=median,
            last=last,
            mean=statistics.fmean(points),
            stdev=statistics.pstdev(points) if len(points) >= 2 else 0.0,
            mad=mad,
            prev=prev,
        )

    # ------------------------------------------------------------------ #
    def prune_and_rollup(self, now: Optional[float] = None) -> None:
        """Compact raw samples older than raw_days into daily rollups, then drop
        rollups older than the retention window."""
        ts = int(now if now is not None else time.time())
        raw_cutoff = ts - self.raw_seconds
        retention_cutoff_day = (ts - self.retention_seconds) // 86400

        old = self.conn.execute(
            "SELECT product_key, ts, price FROM price_samples WHERE ts < ?", (raw_cutoff,)
        ).fetchall()
        if old:
            buckets: dict[tuple[str, int], list[float]] = {}
            for product_key, sample_ts, price in old:
                buckets.setdefault((product_key, sample_ts // 86400), []).append(price)
            for (product_key, day), prices in buckets.items():
                existing = self.conn.execute(
                    "SELECT low, high, samples FROM daily_rollup WHERE product_key=? AND day=?",
                    (product_key, day)).fetchone()
                low, high, n = min(prices), max(prices), len(prices)
                med = statistics.median(prices)
                if existing:
                    low = min(low, existing[0])
                    high = max(high, existing[1])
                    n += int(existing[2] or 0)
                self.conn.execute(
                    "INSERT INTO daily_rollup (product_key, day, low, median, high, samples) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(product_key, day) DO UPDATE SET "
                    "low=excluded.low, median=excluded.median, high=excluded.high, samples=excluded.samples",
                    (product_key, day, low, med, high, n))
            self.conn.execute("DELETE FROM price_samples WHERE ts < ?", (raw_cutoff,))

        self.conn.execute("DELETE FROM daily_rollup WHERE day < ?", (retention_cutoff_day,))
        self.conn.commit()

    # ------------------------------------------------------------------ #
    def record_alert(self, deal: Deal, kind: str, now: Optional[float] = None) -> None:
        ts = int(now if now is not None else time.time())
        self.conn.execute(
            "INSERT INTO alerts (dedupe_key, product_key, ts, price, kind, confidence, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (deal.dedupe_key, deal.history_key, ts, deal.price, kind,
             deal.glitch_confidence, "; ".join(deal.reasons)[:500]),
        )
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover
            pass
