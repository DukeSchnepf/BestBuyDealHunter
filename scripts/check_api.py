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
    if not cfg.api_key:
        print("ERROR: BBY_API_KEY is not set. Get a free key at https://developer.bestbuy.com/")
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

    print("\nBest Buy API looks good. ✅")

    # Optional: eBay connectivity check if credentials are present.
    if cfg.ebay_client_id and cfg.ebay_client_secret:
        print("\nChecking eBay Browse API...")
        from bestbuy_hunter.sources.ebay import EbaySource  # noqa: E402
        ebay = EbaySource(cfg)
        try:
            items = ebay._search("RTX 5070 laptop", limit=3)
            print(f"  eBay token OK; sample results for 'RTX 5070 laptop': {len(items)}")
            for it in items[:3]:
                price = (it.get("price") or {}).get("value")
                print(f"    - ${price:<10} {it.get('title','')[:60]}  [{it.get('condition')}]")
            print("eBay API looks good. ✅")
        except Exception as exc:
            print(f"  eBay check failed: {exc}")
    else:
        print("\n(eBay not configured — set EBAY_CLIENT_ID + EBAY_CLIENT_SECRET to enable.)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
