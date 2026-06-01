from bestbuy_hunter.models import Deal
from bestbuy_hunter.pricehistory import PriceHistory


def mk(price, retailer="bestbuy", sku=1) -> Deal:
    return Deal(sku=sku, name="Item", price=price, retailer=retailer)


def test_record_and_stats(tmp_path):
    ph = PriceHistory(tmp_path / "ph.json")
    for i, p in enumerate([1000, 900, 1000, 950]):
        ph.record([mk(p)], now=1000.0 + i * 86400)
    stats = ph.stats("bestbuy:1", exclude_last=False)
    assert stats.count == 4
    assert stats.low == 900
    assert stats.last == 950


def test_exclude_last_protects_current_sample(tmp_path):
    ph = PriceHistory(tmp_path / "ph.json")
    for i, p in enumerate([1000, 1000, 1000, 300]):
        ph.record([mk(p)], now=1000.0 + i * 86400)
    # Baseline excludes the current (300) sample, so the low stays at 1000.
    stats = ph.stats("bestbuy:1", exclude_last=True)
    assert stats.low == 1000
    assert stats.last == 300


def test_persists_across_instances(tmp_path):
    path = tmp_path / "ph.json"
    PriceHistory(path).record([mk(500)], now=10.0)
    reopened = PriceHistory(path)
    assert reopened.stats("bestbuy:1", exclude_last=False).low == 500


def test_caps_points(tmp_path):
    ph = PriceHistory(tmp_path / "ph.json", max_points=5)
    for i in range(20):
        ph.record([mk(100 + i)], now=1000.0 + i * 3600)
    assert ph.stats("bestbuy:1", exclude_last=False).count == 5


def test_retailers_kept_separate(tmp_path):
    ph = PriceHistory(tmp_path / "ph.json")
    ph.record([mk(100, retailer="bestbuy"), mk(200, retailer="ebay")], now=1.0)
    assert ph.stats("bestbuy:1", exclude_last=False).last == 100
    assert ph.stats("ebay:1", exclude_last=False).last == 200
