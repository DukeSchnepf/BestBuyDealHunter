"""Continuous watcher: slow full sweep + optional fast watchlist poll.

Glitches die in minutes, so when WATCH_INTERVAL_MINUTES is set (and a watchlist
exists) we poll the watchlist far more often than the full catalog sweep, while
both stay well under API rate limits.
"""
from __future__ import annotations

import logging
import time

from .config import Config
from .hunter import Hunter

log = logging.getLogger("bestbuy_hunter.watcher")


def watch(hunter: Hunter, cfg: Config) -> None:
    full_interval = max(cfg.poll_interval_minutes, 1) * 60
    has_watchlist = bool(cfg.watch_skus or cfg.watch_terms)
    watch_interval = cfg.watch_interval_minutes * 60 if (cfg.watch_interval_minutes and has_watchlist) else 0

    if watch_interval:
        log.info("Watcher started — full sweep every %d min, watchlist every %d min.",
                 cfg.poll_interval_minutes, cfg.watch_interval_minutes)
    else:
        log.info("Watcher started — polling every %d min. Ctrl-C to stop.",
                 cfg.poll_interval_minutes)

    next_full = 0.0
    next_watch = 0.0
    backoff = 60
    while True:
        try:
            now = time.monotonic()
            if now >= next_full:
                res = hunter.run_once(dry_run=False)
                log.info("Full sweep: %d glitch(es) + %d new deal(s).",
                         len(res.glitches), len(res.deals))
                next_full = time.monotonic() + full_interval
                backoff = 60

            if watch_interval and time.monotonic() >= next_watch:
                res = hunter.run_watchlist(dry_run=False)
                if res.glitches or res.deals:
                    log.info("Watchlist: %d glitch(es) + %d new deal(s).",
                             len(res.glitches), len(res.deals))
                next_watch = time.monotonic() + watch_interval

            # Sleep until the next scheduled event (cap so Ctrl-C stays responsive).
            upcoming = [next_full] + ([next_watch] if watch_interval else [])
            sleep_for = max(1.0, min(t - time.monotonic() for t in upcoming))
            time.sleep(min(sleep_for, 30.0))
        except KeyboardInterrupt:
            log.info("Watcher stopped by user.")
            hunter.store.close()
            return
        except Exception as exc:
            log.error("Cycle failed: %s — backing off %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, full_interval)
