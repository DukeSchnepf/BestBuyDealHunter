"""Orchestrator: build scan queries, fetch, normalize, curate, dedupe, notify."""
from __future__ import annotations

import logging
from typing import Optional

from . import categories as cats
from . import curate, gpu, notify_discord
from .client import BestBuyClient
from .config import Config, BUCKET_GROUP
from .models import Deal
from .state import SeenStore

log = logging.getLogger("bestbuy_hunter.hunter")

# Buckets we sweep for open-box offers each cycle (the main savings source).
OPENBOX_BUCKETS = ("laptops", "desktops", "graphics_cards", "cpus", "monitors", "components", "storage")

# Buckets we sweep for on-sale *new* items via the Products API.
ONSALE_BUCKETS = ("laptops", "desktops", "graphics_cards", "cpus", "monitors")

# Keyword queries for the RTX 5060+ hunt (post-filtered by gpu.detect_tier).
GPU_SEARCH_BUCKETS = ("laptops", "desktops")


class Hunter:
    def __init__(self, cfg: Config, client: BestBuyClient) -> None:
        self.cfg = cfg
        self.client = client
        self.category_ids = cats.resolve(client, cfg.data_dir)
        self.seen = SeenStore(cfg.data_dir / "seen.json")

    # ------------------------------------------------------------------ #
    # Normalization
    # ------------------------------------------------------------------ #
    def _bucket_for_category_id(self, category_id: str) -> Optional[str]:
        for bucket, cid in self.category_ids.items():
            if cid == category_id:
                return bucket
        return None

    def _product_to_deal(self, item: dict, bucket: str) -> Deal:
        cat_path = item.get("categoryPath") or []
        cat_name = cat_path[-1].get("name", "") if cat_path else ""
        details = item.get("details") or []
        sale = item.get("salePrice") or 0.0
        regular = item.get("regularPrice") or sale
        return Deal(
            sku=int(item.get("sku", 0)),
            name=item.get("name", "") or "",
            url=item.get("url", "") or "",
            image=item.get("image", "") or "",
            price=float(sale or 0.0),
            regular=float(regular or 0.0),
            condition="new",
            rating=item.get("customerReviewAverage"),
            reviews=int(item.get("customerReviewCount") or 0),
            bucket=bucket,
            category_name=cat_name,
            gpu_tier=gpu.tier_from_details(item.get("name", ""), details),
            source="products",
        )

    def _openbox_to_deals(self, result: dict, bucket: str) -> list[Deal]:
        name = (result.get("names") or {}).get("title", "") or result.get("name", "")
        url = result.get("url", "") or ""
        image = (result.get("images") or {}).get("standard", "") or ""
        cat_path = result.get("categoryPath") or []
        cat_name = cat_path[-1].get("name", "") if cat_path else ""
        reviews_obj = result.get("customerReviews") or {}
        rating = reviews_obj.get("averageScore")
        review_count = int(reviews_obj.get("count") or 0)
        sku = int(result.get("sku", 0))
        gpu_tier = gpu.detect_tier(name)

        deals: list[Deal] = []
        for offer in result.get("offers", []) or []:
            prices = offer.get("prices") or {}
            current = prices.get("current")
            regular = prices.get("regular") or current
            if current is None:
                continue
            deals.append(
                Deal(
                    sku=sku,
                    name=name,
                    url=url,
                    image=image,
                    price=float(current),
                    regular=float(regular or current),
                    condition=str(offer.get("condition", "open-box")).lower(),
                    rating=float(rating) if rating is not None else None,
                    reviews=review_count,
                    bucket=bucket,
                    category_name=cat_name,
                    gpu_tier=gpu_tier,
                    source="openbox",
                )
            )
        return deals

    # ------------------------------------------------------------------ #
    # Scanning
    # ------------------------------------------------------------------ #
    def scan(self) -> list[Deal]:
        """Run all scan queries and return raw (un-curated) candidate deals."""
        candidates: list[Deal] = []

        # 1) Open-box by category.
        for bucket in OPENBOX_BUCKETS:
            cid = self.category_ids.get(bucket)
            if not cid:
                continue
            try:
                for result in self.client.open_box(category_id=cid):
                    candidates.extend(self._openbox_to_deals(result, bucket))
            except Exception as exc:
                log.warning("Open-box scan failed for %s: %s", bucket, exc)

        # 2) Open-box for explicitly watched SKUs.
        if self.cfg.watch_skus:
            try:
                for result in self.client.open_box(skus=self.cfg.watch_skus):
                    candidates.extend(self._openbox_to_deals(result, "laptops"))
            except Exception as exc:
                log.warning("Watch-SKU open-box scan failed: %s", exc)

        # 3) On-sale new items in core categories.
        for bucket in ONSALE_BUCKETS:
            cid = self.category_ids.get(bucket)
            if not cid:
                continue
            query = f"(categoryPath.id={cid}&onSale=true)"
            try:
                for item in self.client.products(query, sort="percentSavings.dsc", max_pages=2):
                    candidates.append(self._product_to_deal(item, bucket))
            except Exception as exc:
                log.warning("On-sale scan failed for %s: %s", bucket, exc)

        # 4) RTX 5060+ keyword hunt (new + on the shelf, even if lightly discounted).
        for bucket in GPU_SEARCH_BUCKETS:
            cid = self.category_ids.get(bucket)
            if not cid:
                continue
            query = f"(categoryPath.id={cid}&search=rtx&search=50)"
            try:
                for item in self.client.products(query, sort="salePrice.asc", max_pages=2):
                    deal = self._product_to_deal(item, bucket)
                    if deal.gpu_tier >= self.cfg.gpu_min_tier:
                        candidates.append(deal)
            except Exception as exc:
                log.warning("GPU hunt failed for %s: %s", bucket, exc)

        log.info("Collected %d raw candidates.", len(candidates))
        return candidates

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def run_once(self, dry_run: bool = False) -> list[Deal]:
        """One full cycle. Returns the NEW curated deals (after dedupe)."""
        raw = self.scan()
        ranked = curate.curate(raw, self.cfg)
        log.info("%d deals passed curation.", len(ranked))

        fresh = self.seen.filter_new(ranked)
        log.info("%d are new since last scan.", len(fresh))

        to_alert = fresh[: self.cfg.max_alerts_per_cycle]

        if dry_run:
            return to_alert

        if to_alert:
            header = f"🛒 **{len(to_alert)} new Best Buy deal(s)** hand-picked for you"
            notify_discord.send(self.cfg.discord_webhook_url, to_alert, header=header)
        # Remember everything that passed curation (not just alerted) so we don't
        # re-alert items beyond the per-cycle cap on the next run.
        self.seen.remember(ranked)
        return to_alert
