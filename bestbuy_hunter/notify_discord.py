"""Push ranked deals to Discord via an incoming webhook (rich embeds).

Batches up to 10 embeds per message (Discord's limit), color-codes by deal
score, and honors 429 Retry-After. If no webhook is configured it silently
no-ops so --dry-run / console use still works.
"""
from __future__ import annotations

import logging
import time
from typing import Sequence

import requests

from . import gpu
from .models import Deal

log = logging.getLogger("bestbuy_hunter.discord")

EMBEDS_PER_MESSAGE = 10

# Color by score tier (Discord int color).
_GREEN = 0x2ECC71
_YELLOW = 0xF1C40F
_BLUE = 0x3498DB


def _color_for(deal: Deal) -> int:
    if deal.gpu_tier > 0 or deal.score >= 120:
        return _GREEN
    if deal.score >= 60:
        return _YELLOW
    return _BLUE


def _embed(deal: Deal) -> dict:
    cond = "New" if deal.condition == "new" else f"Open-Box · {deal.condition.title()}"
    fields = [
        {"name": "Price", "value": f"${deal.price:,.2f}", "inline": True},
        {"name": "Regular", "value": f"${deal.regular:,.2f}" if deal.regular else "—", "inline": True},
        {"name": "Discount", "value": f"{deal.pct_off:.0f}% (${deal.dollar_off:,.0f})" if deal.pct_off else "—", "inline": True},
        {"name": "Condition", "value": cond, "inline": True},
        {"name": "Category", "value": deal.category_name or deal.bucket, "inline": True},
    ]
    if deal.gpu_tier:
        fields.append({"name": "GPU", "value": gpu.label(deal.gpu_tier), "inline": True})
    if deal.rating is not None and deal.reviews:
        fields.append({"name": "Rating", "value": f"{deal.rating:.1f}★ ({deal.reviews})", "inline": True})

    desc = ", ".join(deal.reasons) if deal.reasons else ""
    embed = {
        "title": deal.name[:250],
        "url": deal.url or None,
        "color": _color_for(deal),
        "fields": fields,
        "footer": {"text": f"SKU {deal.sku} · score {deal.score:.0f}"},
    }
    if desc:
        embed["description"] = f"**Why:** {desc}"
    if deal.image:
        embed["thumbnail"] = {"url": deal.image}
    return embed


def send(webhook_url: str, deals: Sequence[Deal], header: str | None = None) -> bool:
    """Send deals to Discord. Returns True if anything was sent (or nothing to send)."""
    if not deals:
        return True
    if not webhook_url:
        log.info("No DISCORD_WEBHOOK_URL set; skipping send of %d deal(s).", len(deals))
        return False

    ok = True
    first = True
    for i in range(0, len(deals), EMBEDS_PER_MESSAGE):
        batch = deals[i : i + EMBEDS_PER_MESSAGE]
        payload: dict = {"embeds": [_embed(d) for d in batch]}
        if first and header:
            payload["content"] = header
            first = False
        ok = _post(webhook_url, payload) and ok
    return ok


def _post(webhook_url: str, payload: dict, max_retries: int = 4) -> bool:
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=20)
        except requests.RequestException as exc:
            log.warning("Discord post error (%s/%s): %s", attempt, max_retries, exc)
            if attempt == max_retries:
                return False
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code in (200, 204):
            return True
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            sleep_for = float(retry_after) if retry_after else backoff
            log.info("Discord rate-limited; sleeping %.1fs", sleep_for)
            time.sleep(sleep_for)
            backoff *= 2
            continue
        log.warning("Discord HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    return False
