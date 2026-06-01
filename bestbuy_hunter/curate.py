"""The curation engine — turns raw candidates into hand-picked, ranked deals.

This is what stops the bot from spitting out "20% off a random cable." Each
``Deal`` is run through:

  1. a category allowlist (core compute / components / monitors / *useful*
     gaming peripherals only — everything else is rejected),
  2. a price floor (kills sticker/cable noise),
  3. tiered discount thresholds (strict on accessories, lenient on core compute
     and RTX 5060+ machines),

and survivors are scored so the best deals rank first.
"""
from __future__ import annotations

import math
from typing import Iterable

from .config import Config, BUCKET_GROUP, BUCKET_WEIGHT, PERIPHERAL_KEYWORDS, REJECT_KEYWORDS
from .models import Deal

# Open-box condition desirability bonus.
CONDITION_BONUS: dict[str, float] = {
    "excellent": 12.0,
    "excellent-certified": 12.0,
    "certified": 9.0,
    "good": 6.0,
    "fair": 3.0,
    "new": 0.0,
}


def _classify_peripheral(deal: Deal) -> bool:
    """True if this looks like a *useful* gaming peripheral we want to keep."""
    haystack = f"{deal.name} {deal.category_name}".lower()
    return any(kw in haystack for kw in PERIPHERAL_KEYWORDS)


def _is_rejected(deal: Deal) -> bool:
    haystack = f"{deal.name} {deal.category_name}".lower()
    return any(kw in haystack for kw in REJECT_KEYWORDS)


def _threshold_for(group: str, cfg: Config) -> float:
    t = cfg.thresholds
    return {
        "core": t.core,
        "component": t.component,
        "monitor": t.monitor,
        "peripheral": t.peripheral,
    }.get(group, t.core)


def passes(deal: Deal, cfg: Config) -> bool:
    """Gate: does this deal clear the allowlist + price + discount thresholds?"""
    # Price floor / cap.
    if deal.price < cfg.min_price:
        return False
    if cfg.price_cap is not None and deal.price > cfg.price_cap:
        return False

    # Hard rejects (cables, warranties, gift cards, ...). A genuine RTX 5060+
    # machine never matches these, so this is safe.
    if _is_rejected(deal):
        return False

    # RTX 5060+ machines are the mission: always keep them if they have *any*
    # discount or are open-box.
    if deal.gpu_tier >= cfg.gpu_min_tier and (deal.is_open_box or deal.pct_off > 0):
        deal.reasons.append(f"RTX 50-series target (tier {deal.gpu_tier})")
        return True

    group = BUCKET_GROUP.get(deal.bucket)

    if group is None:
        # Not a core bucket — only keep recognized useful peripherals.
        if not _classify_peripheral(deal):
            return False
        group = "peripheral"
        deal.bucket = "peripheral"

    threshold = _threshold_for(group, cfg)

    # Core compute: open-box, or a real % discount, or a big dollar saving.
    if group == "core":
        if deal.is_open_box:
            deal.reasons.append(f"open-box ({deal.condition})")
            return True
        if deal.pct_off >= threshold:
            deal.reasons.append(f"{deal.pct_off:.0f}% off")
            return True
        if deal.dollar_off >= cfg.thresholds.core_dollar_floor:
            deal.reasons.append(f"${deal.dollar_off:.0f} off")
            return True
        return False

    # Components / monitors / peripherals: require the discount threshold (open
    # box also qualifies since it's a real discount).
    if deal.is_open_box and deal.pct_off >= max(threshold * 0.5, 10):
        deal.reasons.append(f"open-box ({deal.condition})")
        return True
    if deal.pct_off >= threshold:
        deal.reasons.append(f"{deal.pct_off:.0f}% off")
        return True
    return False


def score(deal: Deal) -> float:
    """Compute a ranking score (higher = better deal). Mutates deal.score."""
    bucket_weight = BUCKET_WEIGHT.get(deal.bucket, BUCKET_WEIGHT["other"])

    # Discount signal: percent dominates, with a log-scaled dollar bonus so a
    # $400-off laptop outranks a $4-off cable at the same percentage.
    discount = deal.pct_off * 1.5
    if deal.dollar_off > 0:
        discount += math.log10(deal.dollar_off + 1) * 8.0

    gpu_bonus = deal.gpu_tier * 14.0  # 5090 (tier 6) => +84
    condition_bonus = CONDITION_BONUS.get(deal.condition, 0.0)

    # Trust signal: good ratings with enough reviews nudge a deal up a little.
    trust = 0.0
    if deal.rating is not None and deal.reviews:
        trust = (deal.rating - 3.0) * math.log10(deal.reviews + 1) * 2.0

    total = (discount + gpu_bonus + condition_bonus + trust) * bucket_weight
    deal.score = round(total, 2)
    return deal.score


def curate(deals: Iterable[Deal], cfg: Config) -> list[Deal]:
    """Gate, score, and sort candidates; returns the hand-picked ranked list."""
    kept: list[Deal] = []
    seen_keys: set[str] = set()
    for deal in deals:
        if deal.dedupe_key in seen_keys:
            continue
        if passes(deal, cfg):
            score(deal)
            kept.append(deal)
            seen_keys.add(deal.dedupe_key)
    kept.sort(key=lambda d: d.score, reverse=True)
    return kept
