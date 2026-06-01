"""Thin Best Buy Developer API client.

Handles auth, the ~5 req/sec rate limit, pagination, and retry/backoff on 429
and 5xx responses. Two surfaces are used by the bot:

* Products API (v1):  https://api.bestbuy.com/v1/products(<filters>)?apiKey=...
* Open Box API (beta): https://api.bestbuy.com/beta/products/openBox(...)?apiKey=...

The client returns raw decoded JSON dicts; normalization into ``Deal`` objects
happens in hunter.py so this layer stays simple and testable.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable, Iterator, Optional

import requests

log = logging.getLogger("bestbuy_hunter.client")

V1_BASE = "https://api.bestbuy.com/v1"
BETA_BASE = "https://api.bestbuy.com/beta"

# Fields we request from the Products API.
PRODUCT_SHOW = ",".join(
    [
        "sku", "name", "salePrice", "regularPrice", "percentSavings",
        "dollarSavings", "onSale", "url", "image", "customerReviewAverage",
        "customerReviewCount", "categoryPath.id", "categoryPath.name",
        "details.name", "details.value", "manufacturer", "modelNumber",
    ]
)


class BestBuyError(RuntimeError):
    pass


class BestBuyClient:
    def __init__(
        self,
        api_key: str,
        requests_per_second: float = 4.0,
        max_retries: int = 4,
        timeout: float = 20.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not api_key:
            raise BestBuyError("A Best Buy API key is required.")
        self.api_key = api_key
        self._min_interval = 1.0 / max(requests_per_second, 0.5)
        self._last_call = 0.0
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "bestbuy-deal-hunter/1.0"})

    # ------------------------------------------------------------------ #
    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, url: str, params: dict) -> dict:
        params = {**params, "apiKey": self.api_key, "format": "json"}
        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                log.warning("Request error (%s/%s): %s", attempt, self.max_retries, exc)
                if attempt == self.max_retries:
                    raise BestBuyError(f"Network error after retries: {exc}") from exc
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise BestBuyError(f"Bad JSON from {url}: {exc}") from exc

            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                sleep_for = float(retry_after) if retry_after else backoff
                log.warning(
                    "HTTP %s from Best Buy (%s/%s); sleeping %.1fs",
                    resp.status_code, attempt, self.max_retries, sleep_for,
                )
                if attempt == self.max_retries:
                    raise BestBuyError(f"HTTP {resp.status_code} after retries")
                time.sleep(sleep_for)
                backoff *= 2
                continue

            if resp.status_code in (403, 401):
                raise BestBuyError(
                    f"HTTP {resp.status_code} — check that BBY_API_KEY is valid/activated."
                )
            raise BestBuyError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        raise BestBuyError("Exhausted retries")  # pragma: no cover

    # ------------------------------------------------------------------ #
    def products(
        self,
        query: str,
        sort: str = "percentSavings.dsc",
        page_size: int = 100,
        max_pages: int = 1,
    ) -> Iterator[dict]:
        """Yield product dicts for a Products API query string, paginating as needed.

        ``query`` is the parenthesized filter expression, e.g.
        ``(categoryPath.id=abcat0502000&onSale=true)``.
        """
        url = f"{V1_BASE}/products{query}"
        for page in range(1, max_pages + 1):
            data = self._get(
                url,
                {"show": PRODUCT_SHOW, "sort": sort, "pageSize": page_size, "page": page},
            )
            items = data.get("products", []) or []
            for item in items:
                yield item
            total_pages = int(data.get("totalPages") or 1)
            if page >= total_pages:
                break

    def open_box(self, category_id: Optional[str] = None, skus: Optional[Iterable[int]] = None) -> list[dict]:
        """Fetch Open Box results, by category, by SKU list, or all (none given)."""
        if skus:
            sku_list = ",".join(str(s) for s in skus)
            url = f"{BETA_BASE}/products/openBox(sku in({sku_list}))"
        elif category_id:
            url = f"{BETA_BASE}/products/openBox(categoryId={category_id})"
        else:
            url = f"{BETA_BASE}/products/openBox"
        data = self._get(url, {"pageSize": 100})
        return data.get("results", []) or []

    def categories(self, name: str) -> list[dict]:
        """Look up categories by exact name (used to resolve/verify category IDs)."""
        url = f'{V1_BASE}/categories(name="{name}")'
        data = self._get(url, {"show": "id,name", "pageSize": 5})
        return data.get("categories", []) or []
