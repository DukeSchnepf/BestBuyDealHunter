"""eBay source: Browse API search for used / open-box / refurbished RTX 5060+ gear.

Uses the OAuth2 *client credentials* grant (an application token — no user
login needed) to call the Browse API ``item_summary/search`` endpoint. This is
the highest-value second source for the mission: it's where used/refurb RTX
50-series laptops live, and (combined with the glitch detector) where the
occasional mispriced listing shows up.

Requires EBAY_CLIENT_ID + EBAY_CLIENT_SECRET (free eBay developer keyset).
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Optional

import requests

from .. import gpu
from ..config import Config
from ..models import Deal
from .base import Source

log = logging.getLogger("bestbuy_hunter.sources.ebay")

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"

# eBay conditionId -> our normalized condition. 1000 (new) and 7000 (for parts)
# are intentionally omitted: we don't want full-price-new or broken items here.
CONDITION_MAP: dict[str, str] = {
    "1500": "open-box",
    "2000": "refurbished", "2010": "refurbished", "2020": "refurbished",
    "2030": "refurbished", "2500": "refurbished", "2750": "refurbished",
    "3000": "used", "4000": "used", "5000": "used", "6000": "used",
}

# RTX 50-series tiers -> search term. We query only tiers >= gpu_min_tier.
TIER_TERMS: dict[int, str] = {
    1: "RTX 5060", 2: "RTX 5060 Ti", 3: "RTX 5070",
    4: "RTX 5070 Ti", 5: "RTX 5080", 6: "RTX 5090",
}

# Conditions we accept (used + open-box + refurbished tiers), comma-joined for the filter.
ACCEPTED_CONDITION_IDS = "1500|2000|2010|2020|2030|2500|2750|3000|4000|5000|6000"


class EbaySource(Source):
    name = "ebay"

    def __init__(self, cfg: Config, session: Optional[requests.Session] = None) -> None:
        super().__init__(cfg)
        self.session = session or requests.Session()
        self._token: str = ""
        self._token_expiry: float = 0.0

    # ------------------------------------------------------------------ #
    # OAuth
    # ------------------------------------------------------------------ #
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        creds = f"{self.cfg.ebay_client_id}:{self.cfg.ebay_client_secret}".encode()
        headers = {
            "Authorization": "Basic " + base64.b64encode(creds).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        resp = self.session.post(
            OAUTH_URL,
            headers=headers,
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + float(payload.get("expires_in", 7200))
        return self._token

    # ------------------------------------------------------------------ #
    # Search + normalization
    # ------------------------------------------------------------------ #
    def _search(self, query: str, limit: int = 50) -> list[dict]:
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": self.cfg.ebay_marketplace,
            "Content-Type": "application/json",
        }
        params = {
            "q": query,
            "limit": str(limit),
            "sort": "price",  # cheapest first — surfaces both bargains and glitches
            "filter": (
                f"conditionIds:{{{ACCEPTED_CONDITION_IDS}}},"
                "buyingOptions:{FIXED_PRICE}"
            ),
        }
        resp = self.session.get(SEARCH_URL, headers=headers, params=params, timeout=25)
        if resp.status_code == 429:
            log.warning("eBay rate-limited on %r; skipping this query.", query)
            return []
        resp.raise_for_status()
        return resp.json().get("itemSummaries", []) or []

    def _to_deal(self, item: dict, bucket: str) -> Optional[Deal]:
        title = item.get("title", "") or ""
        price_obj = item.get("price") or {}
        try:
            price = float(price_obj.get("value"))
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        cond_id = str(item.get("conditionId") or "")
        condition = CONDITION_MAP.get(cond_id)
        if condition is None:
            return None  # new / for-parts / unknown -> skip

        # Original price, when the seller provides a strike-through.
        regular = 0.0
        mp = item.get("marketingPrice") or {}
        orig = (mp.get("originalPrice") or {}).get("value")
        if orig:
            try:
                regular = float(orig)
            except (TypeError, ValueError):
                regular = 0.0

        image = (item.get("image") or {}).get("imageUrl", "") or ""
        if not image and item.get("thumbnailImages"):
            image = item["thumbnailImages"][0].get("imageUrl", "")
        seller = (item.get("seller") or {}).get("username", "")

        return Deal(
            name=title,
            url=item.get("itemWebUrl", "") or "",
            image=image,
            price=price,
            regular=regular,
            condition=condition,
            bucket=bucket,
            category_name=item.get("categories", [{}])[0].get("categoryName", "") if item.get("categories") else bucket,
            gpu_tier=gpu.detect_tier(title),
            source="ebay-browse",
            retailer=self.name,
            listing_id=str(item.get("itemId", "")),
            seller=seller,
        )

    # ------------------------------------------------------------------ #
    def scan(self) -> list[Deal]:
        candidates: list[Deal] = []
        min_tier = max(self.cfg.gpu_min_tier, 1)

        # Query each qualifying GPU tier for both laptops and desktops.
        for tier, term in TIER_TERMS.items():
            if tier < min_tier:
                continue
            for bucket, suffix in (("laptops", "laptop"), ("desktops", "desktop")):
                query = f"{term} {suffix}"
                try:
                    items = self._search(query)
                except Exception as exc:
                    log.warning("eBay search failed for %r: %s", query, exc)
                    continue
                for item in items:
                    deal = self._to_deal(item, bucket)
                    # Keep only genuine tier matches (title can be noisy).
                    if deal and deal.gpu_tier >= min_tier:
                        candidates.append(deal)

        log.info("eBay: %d raw candidates.", len(candidates))
        return candidates

    def scan_watchlist(self) -> list[Deal]:
        """Search just the user's WATCH_TERMS — cheap enough to poll often."""
        if not self.cfg.watch_terms:
            return []
        candidates: list[Deal] = []
        for term in self.cfg.watch_terms:
            try:
                items = self._search(term, limit=25)
            except Exception as exc:
                log.warning("eBay watchlist search failed for %r: %s", term, exc)
                continue
            for item in items:
                # Watchlist is intentionally permissive — keep every condition match.
                deal = self._to_deal(item, "laptops")
                if deal:
                    candidates.append(deal)
        return candidates
