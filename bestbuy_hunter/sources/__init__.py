"""Retailer source adapters.

Each source translates a retailer's API into a list of normalized ``Deal``
objects so the rest of the pipeline (curation, price history, glitch detection,
notification) is retailer-agnostic.
"""
from __future__ import annotations

from ..config import Config
from .base import Source


def build_sources(cfg: Config) -> list[Source]:
    """Instantiate every enabled + credentialed source from config."""
    sources: list[Source] = []

    if cfg.bestbuy_enabled and cfg.api_key:
        from .bestbuy import BestBuySource
        sources.append(BestBuySource(cfg))

    if cfg.ebay_enabled and cfg.ebay_client_id and cfg.ebay_client_secret:
        from .ebay import EbaySource
        sources.append(EbaySource(cfg))

    return sources


__all__ = ["Source", "build_sources"]
