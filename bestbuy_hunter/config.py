"""Configuration: env loading, category map, curation thresholds, GPU tiers.

Everything tunable lives here so the curation logic in ``curate.py`` stays clean.
Values come from environment variables (loaded from ``.env`` if present) with
sensible defaults, so the bot runs out of the box once the two required secrets
(``BBY_API_KEY`` and ``DISCORD_WEBHOOK_URL``) are set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:  # optional; .env is convenient but not required
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a soft dependency
    pass


# --------------------------------------------------------------------------- #
# Category buckets
# --------------------------------------------------------------------------- #
# We group Best Buy categories into buckets that drive both *what we scan* and
# *how strict the discount threshold is*. Category IDs are Best Buy's stable
# "abcat"/"pcmcat" identifiers; categories.py verifies/refreshes them at startup
# and falls back to these defaults if the API lookup fails.
CATEGORY_DEFAULTS: dict[str, str] = {
    "laptops": "abcat0502000",          # All Laptops
    "desktops": "abcat0501000",         # All Desktops
    "graphics_cards": "abcat0507002",   # Graphics Cards / GPUs
    "cpus": "abcat0507010",             # CPUs / Processors
    "components": "abcat0507000",       # Computer Cards & Components (RAM/mobo/PSU/etc.)
    "monitors": "abcat0509000",         # Monitors
    "storage": "pcmcat186100050007",    # Internal SSDs / storage
}

# Friendly names for the Categories API lookup (name -> bucket key).
CATEGORY_LOOKUP_NAMES: dict[str, str] = {
    "All Laptops": "laptops",
    "All Desktops": "desktops",
    "Graphics Cards": "graphics_cards",
    "CPUs / Processors": "cpus",
    "Computer Cards & Components": "components",
    "Monitors": "monitors",
    "Internal Solid State Drives": "storage",
}

# Bucket -> discount-threshold group used by the curation engine.
BUCKET_GROUP: dict[str, str] = {
    "laptops": "core",
    "desktops": "core",
    "graphics_cards": "core",
    "cpus": "core",
    "components": "component",
    "storage": "component",
    "monitors": "monitor",
}

# Relevance weight applied to each bucket's score (higher = surfaced more readily).
BUCKET_WEIGHT: dict[str, float] = {
    "laptops": 1.4,
    "desktops": 1.3,
    "graphics_cards": 1.3,
    "cpus": 1.1,
    "components": 1.0,
    "storage": 1.0,
    "monitors": 1.05,
    "peripheral": 0.8,
    "other": 0.3,
}

# Useful gaming peripherals we *do* want (matched against product name/category,
# lowercase substring). Anything not here and not in a core bucket is rejected.
PERIPHERAL_KEYWORDS: tuple[str, ...] = (
    "mechanical keyboard", "gaming keyboard", "gaming mouse", "gaming mice",
    "gaming headset", "headset", "controller", "gamepad", "capture card",
    "webcam", "stream deck", "gaming chair",
)

# Hard rejects — categories/keywords that are almost always junk for this user.
REJECT_KEYWORDS: tuple[str, ...] = (
    "cable", "adapter", "dongle", "screen protector", "case for", "sleeve",
    "warranty", "protection plan", "geek squad", "gift card", "ink", "toner",
    "mount", "stand for", "cleaning", "sticker", "skin for", "stylus",
)


@dataclass
class Thresholds:
    """Discount thresholds (percent) per category group + dollar shortcut."""

    core: float = 15.0
    component: float = 20.0
    monitor: float = 20.0
    peripheral: float = 35.0
    core_dollar_floor: float = 75.0


@dataclass
class GlitchConfig:
    """Tuning for the price-error / glitch detector (see glitch.py)."""

    enabled: bool = True
    # Fraction of the historical low that a price must fall to/below to look like
    # an error (e.g. 0.60 => 40%+ under the lowest price we've ever recorded).
    floor_ratio: float = 0.60
    # Fraction of the rolling median that flags an anomaly (0.50 => half median).
    median_ratio: float = 0.50
    # Fraction of MSRP/regular that flags a likely error even with no history
    # (0.40 => 60%+ off list price).
    msrp_ratio: float = 0.40
    # Minimum recorded history points before floor/median signals are trusted.
    min_history: int = 4
    # Minimum confidence (0-1) required to fire a glitch alert.
    min_confidence: float = 0.6


@dataclass
class Config:
    """Top-level runtime configuration."""

    api_key: str = ""
    discord_webhook_url: str = ""
    discord_glitch_webhook_url: str = ""   # optional separate lane for price errors
    glitch_ping: str = ""                  # e.g. "@here" or "<@&ROLE_ID>" for glitch alerts
    poll_interval_minutes: int = 12
    price_cap: Optional[float] = None
    min_price: float = 15.0
    gpu_min_tier: int = 1
    max_alerts_per_cycle: int = 15
    watch_skus: list[int] = field(default_factory=list)
    thresholds: Thresholds = field(default_factory=Thresholds)
    glitch: GlitchConfig = field(default_factory=GlitchConfig)
    # source toggles + credentials
    bestbuy_enabled: bool = True
    ebay_enabled: bool = False
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_marketplace: str = "EBAY_US"
    data_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data")

    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls) -> "Config":
        def _f(name: str, default: Optional[float]) -> Optional[float]:
            raw = os.getenv(name, "").strip()
            if raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        def _i(name: str, default: int) -> int:
            raw = os.getenv(name, "").strip()
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        def _b(name: str, default: bool) -> bool:
            raw = os.getenv(name, "").strip().lower()
            if raw == "":
                return default
            return raw in ("1", "true", "yes", "on", "y")

        watch_raw = os.getenv("WATCH_SKUS", "").strip()
        watch_skus: list[int] = []
        for chunk in watch_raw.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                watch_skus.append(int(chunk))

        thresholds = Thresholds(
            core=_f("THRESHOLD_CORE", 15.0),
            component=_f("THRESHOLD_COMPONENT", 20.0),
            monitor=_f("THRESHOLD_MONITOR", 20.0),
            peripheral=_f("THRESHOLD_PERIPHERAL", 35.0),
            core_dollar_floor=_f("CORE_DOLLAR_FLOOR", 75.0),
        )

        glitch = GlitchConfig(
            enabled=_b("GLITCH_ENABLED", True),
            floor_ratio=_f("GLITCH_FLOOR_RATIO", 0.60),
            median_ratio=_f("GLITCH_MEDIAN_RATIO", 0.50),
            msrp_ratio=_f("GLITCH_MSRP_RATIO", 0.40),
            min_history=_i("GLITCH_MIN_HISTORY", 4),
            min_confidence=_f("GLITCH_MIN_CONFIDENCE", 0.6),
        )

        ebay_id = os.getenv("EBAY_CLIENT_ID", "").strip()
        ebay_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()

        cfg = cls(
            api_key=os.getenv("BBY_API_KEY", "").strip(),
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
            discord_glitch_webhook_url=os.getenv("DISCORD_GLITCH_WEBHOOK_URL", "").strip(),
            glitch_ping=os.getenv("GLITCH_PING", "").strip(),
            poll_interval_minutes=_i("POLL_INTERVAL_MINUTES", 12),
            price_cap=_f("PRICE_CAP", None),
            min_price=_f("MIN_PRICE", 15.0),
            gpu_min_tier=_i("GPU_MIN_TIER", 1),
            max_alerts_per_cycle=_i("MAX_ALERTS_PER_CYCLE", 15),
            watch_skus=watch_skus,
            thresholds=thresholds,
            glitch=glitch,
            bestbuy_enabled=_b("BESTBUY_ENABLED", True),
            # eBay turns on automatically when credentials are present (or via flag).
            ebay_enabled=_b("EBAY_ENABLED", bool(ebay_id and ebay_secret)),
            ebay_client_id=ebay_id,
            ebay_client_secret=ebay_secret,
            ebay_marketplace=os.getenv("EBAY_MARKETPLACE", "EBAY_US").strip() or "EBAY_US",
        )
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        return cfg

    # ------------------------------------------------------------------ #
    def validate_sources(self) -> None:
        """Ensure at least one usable source is configured; raise otherwise."""
        bestbuy_ok = self.bestbuy_enabled and bool(self.api_key)
        ebay_ok = self.ebay_enabled and bool(self.ebay_client_id and self.ebay_client_secret)
        if not (bestbuy_ok or ebay_ok):
            raise RuntimeError(
                "No source is configured. Set BBY_API_KEY (Best Buy, "
                "https://developer.bestbuy.com/) and/or EBAY_CLIENT_ID + "
                "EBAY_CLIENT_SECRET (eBay, https://developer.ebay.com/) in your .env."
            )
