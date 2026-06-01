from bestbuy_hunter.config import Config
from bestbuy_hunter.sources.ebay import EbaySource


def src() -> EbaySource:
    cfg = Config()
    cfg.ebay_client_id = "x"
    cfg.ebay_client_secret = "y"
    return EbaySource(cfg)


def item(**kw) -> dict:
    base = {
        "itemId": "v1|123|0",
        "title": "ASUS ROG RTX 5070 Gaming Laptop",
        "price": {"value": "1299.99", "currency": "USD"},
        "conditionId": "3000",
        "condition": "Used",
        "itemWebUrl": "https://ebay.com/itm/123",
        "image": {"imageUrl": "https://i.ebayimg.com/x.jpg"},
        "seller": {"username": "techseller"},
    }
    base.update(kw)
    return base


def test_used_item_normalizes():
    d = src()._to_deal(item(), "laptops")
    assert d is not None
    assert d.retailer == "ebay"
    assert d.condition == "used"
    assert d.price == 1299.99
    assert d.gpu_tier == 3            # RTX 5070
    assert d.listing_id == "v1|123|0"
    assert d.seller == "techseller"
    assert d.is_open_box            # used counts as a discount-worthy condition
    assert d.is_used


def test_open_box_condition_mapped():
    d = src()._to_deal(item(conditionId="1500", condition="Open box"), "laptops")
    assert d.condition == "open-box"


def test_refurbished_condition_mapped():
    d = src()._to_deal(item(conditionId="2000", condition="Certified - Refurbished"), "laptops")
    assert d.condition == "refurbished"


def test_new_item_skipped():
    assert src()._to_deal(item(conditionId="1000", condition="New"), "laptops") is None


def test_for_parts_skipped():
    assert src()._to_deal(item(conditionId="7000", condition="For parts"), "laptops") is None


def test_marketing_original_price_becomes_regular():
    d = src()._to_deal(
        item(marketingPrice={"originalPrice": {"value": "1799.99"}}), "laptops"
    )
    assert d.regular == 1799.99
    assert d.pct_off > 0


def test_zero_price_skipped():
    assert src()._to_deal(item(price={"value": "0"}), "laptops") is None


def test_history_and_dedupe_keys_use_listing_id():
    d = src()._to_deal(item(), "laptops")
    assert d.history_key == "ebay:v1|123|0"
    assert d.dedupe_key == "ebay:v1|123|0:used"
