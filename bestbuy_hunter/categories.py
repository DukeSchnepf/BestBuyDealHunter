"""Resolve category names -> Best Buy category IDs, with caching + fallbacks.

Best Buy occasionally restructures category IDs. At startup we try to confirm
the IDs via the Categories API and cache them to ``data/categories.json``. If
the network/lookup fails, we fall back to the known-good defaults in config so
the bot keeps working offline-ish.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from . import config
from .client import BestBuyClient

log = logging.getLogger("bestbuy_hunter.categories")


def resolve(client: Optional[BestBuyClient], data_dir: Path, refresh: bool = False) -> dict[str, str]:
    """Return a {bucket_key: category_id} map, using cache/API/defaults in that order."""
    cache_path = data_dir / "categories.json"
    if not refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if isinstance(cached, dict) and cached:
                return {**config.CATEGORY_DEFAULTS, **cached}
        except Exception:  # pragma: no cover - corrupt cache, ignore
            pass

    resolved: dict[str, str] = dict(config.CATEGORY_DEFAULTS)

    if client is not None:
        for friendly_name, bucket in config.CATEGORY_LOOKUP_NAMES.items():
            try:
                matches = client.categories(friendly_name)
            except Exception as exc:  # network/API hiccup -> keep default
                log.debug("Category lookup failed for %r: %s", friendly_name, exc)
                continue
            if matches and matches[0].get("id"):
                resolved[bucket] = matches[0]["id"]

        try:
            cache_path.write_text(json.dumps(resolved, indent=2))
        except Exception:  # pragma: no cover
            pass

    return resolved
