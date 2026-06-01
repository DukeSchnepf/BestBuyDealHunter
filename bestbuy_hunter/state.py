"""Dedupe store so the watcher only alerts on NEW or price-dropped deals.

Persisted as JSON at ``data/seen.json``: {dedupe_key: last_price}. A deal is
considered "new" if its key is unseen, or if its price dropped below the last
price we alerted on (a fresh, better offer worth pinging about).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from .models import Deal

log = logging.getLogger("bestbuy_hunter.state")


class SeenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._seen = {str(k): float(v) for k, v in json.loads(self.path.read_text()).items()}
            except Exception:  # pragma: no cover - corrupt file, start fresh
                log.warning("Could not read %s; starting with empty state.", self.path)
                self._seen = {}

    def is_new(self, deal: Deal) -> bool:
        prev = self._seen.get(deal.dedupe_key)
        if prev is None:
            return True
        # Alert again only if the price meaningfully dropped (>= $1) vs last alert.
        return deal.price <= prev - 1.0

    def filter_new(self, deals: Iterable[Deal]) -> list[Deal]:
        return [d for d in deals if self.is_new(d)]

    def remember(self, deals: Iterable[Deal]) -> None:
        for d in deals:
            self._seen[d.dedupe_key] = d.price
        self._save()

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._seen, indent=2))
        except Exception as exc:  # pragma: no cover
            log.warning("Could not persist state to %s: %s", self.path, exc)
