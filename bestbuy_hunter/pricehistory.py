"""Rolling per-product price history, used by the glitch detector.

Persisted as JSON at ``data/price_history.json``:

    { "<retailer>:<product_id>": [[epoch_seconds, price], ...], ... }

Each key keeps the most recent ``max_points`` samples; keys untouched for
``max_age_days`` are pruned so the file stays small. The point of recording
*every* candidate we see (not just curated ones) is to build an honest price
floor per product so we can recognize when something drops impossibly low.
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .models import Deal

log = logging.getLogger("bestbuy_hunter.pricehistory")


@dataclass
class PriceStats:
    count: int
    low: Optional[float]
    median: Optional[float]
    last: Optional[float]


class PriceHistory:
    def __init__(self, path: Path, max_points: int = 40, max_age_days: int = 90) -> None:
        self.path = path
        self.max_points = max_points
        self.max_age_seconds = max_age_days * 86400
        self._hist: dict[str, list[list[float]]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text())
                if isinstance(raw, dict):
                    self._hist = {str(k): list(v) for k, v in raw.items()}
            except Exception:  # pragma: no cover - corrupt file, start fresh
                log.warning("Could not read %s; starting fresh.", self.path)
                self._hist = {}

    # ------------------------------------------------------------------ #
    def record(self, deals: Iterable[Deal], now: Optional[float] = None) -> None:
        """Append the current price for each deal (deduped per key per call)."""
        ts = now if now is not None else time.time()
        latest: dict[str, float] = {}
        for d in deals:
            if d.price and d.price > 0:
                latest[d.history_key] = d.price  # last write wins within a cycle
        for key, price in latest.items():
            series = self._hist.setdefault(key, [])
            # Skip a no-op duplicate if price unchanged from the last sample.
            if series and abs(series[-1][1] - price) < 0.005:
                series[-1][0] = ts
            else:
                series.append([ts, round(price, 2)])
            if len(series) > self.max_points:
                del series[: len(series) - self.max_points]
        self._prune(ts)
        self._save()

    def stats(self, key: str, exclude_last: bool = True) -> PriceStats:
        """Summary stats for a product. ``exclude_last`` ignores the most recent
        sample so a current (possibly glitched) price isn't compared to itself."""
        series = self._hist.get(key, [])
        prices = [p for _, p in series]
        baseline = prices[:-1] if (exclude_last and len(prices) > 1) else prices
        if not baseline:
            return PriceStats(count=len(prices), low=None, median=None,
                              last=prices[-1] if prices else None)
        return PriceStats(
            count=len(prices),
            low=min(baseline),
            median=statistics.median(baseline),
            last=prices[-1] if prices else None,
        )

    def _prune(self, now: float) -> None:
        cutoff = now - self.max_age_seconds
        for key in list(self._hist.keys()):
            self._hist[key] = [pt for pt in self._hist[key] if pt[0] >= cutoff]
            if not self._hist[key]:
                del self._hist[key]

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._hist))
        except Exception as exc:  # pragma: no cover
            log.warning("Could not persist price history: %s", exc)
