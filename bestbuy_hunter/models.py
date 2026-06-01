"""Normalized data model shared across all retailers/sources in the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Deal:
    """A normalized candidate deal from any source (Best Buy, eBay, ...).

    Sources translate their own payloads into this shape so the curation,
    price-history, glitch-detection, and notification layers stay retailer-agnostic.
    """

    sku: int = 0                   # numeric product id (Best Buy SKU); 0 if N/A
    name: str = ""
    url: str = ""
    image: str = ""
    price: float = 0.0              # current / sale / open-box / listing price
    regular: float = 0.0           # regular (list) / original price (0 if unknown)
    condition: str = "new"         # new | excellent | certified | good | fair | used | refurbished
    rating: Optional[float] = None
    reviews: int = 0
    bucket: str = "other"          # category bucket key (see config.BUCKET_*)
    category_name: str = ""
    gpu_tier: int = 0              # RTX 50-series tier (0 = none)
    source: str = "products"       # finer-grained source tag: products | openbox | ebay-browse
    retailer: str = "bestbuy"      # retailer namespace: bestbuy | ebay | amazon | ...
    listing_id: str = ""           # string id for retailers without integer SKUs (eBay itemId)
    seller: str = ""               # marketplace seller name, when applicable

    # filled in by the curation engine
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    # filled in by the glitch detector
    is_glitch: bool = False
    glitch_confidence: float = 0.0  # 0.0 - 1.0

    # ------------------------------------------------------------------ #
    @property
    def product_id(self) -> str:
        """Stable per-retailer product identifier (string)."""
        return self.listing_id or str(self.sku)

    @property
    def is_open_box(self) -> bool:
        return self.source == "openbox" or self.condition not in ("new", "")

    @property
    def is_used(self) -> bool:
        return self.condition in ("used", "refurbished")

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
    def history_key(self) -> str:
        """Identity for the price-history store (per retailer + product)."""
        return f"{self.retailer}:{self.product_id}"

    @property
    def dedupe_key(self) -> str:
        """Stable identity for the seen-store: same retailer+product+condition is one offer."""
        return f"{self.retailer}:{self.product_id}:{self.condition}"
