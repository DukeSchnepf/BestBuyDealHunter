#!/usr/bin/env python3
"""Smoke test: confirm the Best Buy API key works and show the live schema.

Run after setting BBY_API_KEY in your .env:

    python scripts/check_api.py

Prints a few real on-sale laptops and a sample of open-box laptop offers so we
can confirm connectivity and that the response shape matches expectations.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bestbuy_hunter import categories as cats  # noqa: E402
from bestbuy_hunter.client import BestBuyClient  # noqa: E402
from bestbuy_hunter.config import Config  # noqa: E402


def main() -> int:
    cfg = Config.from_env()
    try:
        cfg.require_api_key()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 2

    client = BestBuyClient(cfg.api_key)

    print("Resolving category IDs...")
    cat_ids = cats.resolve(client, cfg.data_dir, refresh=True)
    for k, v in cat_ids.items():
        print(f"  {k:<16} {v}")

    laptops = cat_ids.get("laptops")

    print("\nTop on-sale laptops (Products API):")
    query = f"(categoryPath.id={laptops}&onSale=true)"
    count = 0
    for item in client.products(query, sort="percentSavings.dsc", page_size=5, max_pages=1):
        count += 1
        print(
            f"  - {item.get('name','')[:60]:<60} "
            f"${item.get('salePrice')} (was ${item.get('regularPrice')}, "
            f"{item.get('percentSavings')}% off)"
        )
        if count >= 5:
            break
    if count == 0:
        print("  (no on-sale laptops returned)")

    print("\nSample open-box laptop offers (Open Box API):")
    results = client.open_box(category_id=laptops)
    for result in results[:3]:
        name = (result.get("names") or {}).get("title", "")
        print(f"  - {name[:70]}")
        for offer in (result.get("offers") or [])[:3]:
            prices = offer.get("prices") or {}
            print(
                f"      {offer.get('condition'):<12} "
                f"current ${prices.get('current')}  regular ${prices.get('regular')}"
            )
    if not results:
        print("  (no open-box laptops returned right now)")

    print("\nAPI looks good. ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
