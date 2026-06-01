"""Continuous watcher loop: scan on an interval, alert on new deals, back off on errors."""
from __future__ import annotations

import logging
import time

from .config import Config
from .hunter import Hunter

log = logging.getLogger("bestbuy_hunter.watcher")


def watch(hunter: Hunter, cfg: Config) -> None:
    interval = max(cfg.poll_interval_minutes, 1) * 60
    log.info("Watcher started — polling every %d min. Ctrl-C to stop.", cfg.poll_interval_minutes)
    backoff = 60
    while True:
        try:
            result = hunter.run_once(dry_run=False)
            log.info("Cycle complete: %d glitch(es) + %d new deal(s) alerted.",
                     len(result.glitches), len(result.deals))
            backoff = 60  # reset after a healthy cycle
            time.sleep(interval)
        except KeyboardInterrupt:
            log.info("Watcher stopped by user.")
            return
        except Exception as exc:  # keep the watcher alive through transient failures
            log.error("Cycle failed: %s — backing off %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, interval)
