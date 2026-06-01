"""Normalized data model shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Deal:
    """A normalized candidate deal from either the Products or Open Box API."""

    sku: int
    name: str
    url: str = ""
    image: str = ""
    price: float = 0.0              # current / sale / open-box price
    regular: float = 0.0           # regular (list) price
    condition: str = "new"         # "new" or open-box tier: excellent/certified/good/fair
    rating: Optional[float] = None
    reviews: int = 0
    bucket: str = "other"          # category bucket key (see config.BUCKET_*)
    category_name: str = ""
    gpu_tier: int = 0              # RTX 50-series tier (0 = none)
    source: str = "products"       # "products" or "openbox"

    # filled in by the curation engine
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    @property
    def is_open_box(self) -> bool:
        return self.source == "openbox" or self.condition != "new"

    @property
    def dollar_off(self) -> float:
        if self.regular and self.regular > self.price:
            return round(self.regular - self.price, 2)
        return 0.0

    @property
    def pct_off(self) -> float:
        if self.regular and self.regular > 0 and self.regular >= self.price:
            return round((self.regular - self.price) / self.regular * 100.0, 1)
        return 0.0

    @property
    def dedupe_key(self) -> str:
        """Stable identity for the seen-store: same sku+condition is the same offer."""
        return f"{self.sku}:{self.condition}"
