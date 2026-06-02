from bestbuy_hunter.models import Deal
from bestbuy_hunter.storage import PriceStore


def mk(price, retailer="bestbuy", sku=1, regular=0.0, condition="new") -> Deal:
    return Deal(sku=sku, name="Item", price=price, retailer=retailer,
                regular=regular, condition=condition)


def test_record_and_stats(tmp_path):
    store = PriceStore(tmp_path / "p.db")
    for i, p in enumerate([1000, 900, 1000, 950]):
        store.record([mk(p)], now=i * 86400)
    stats = store.stats("bestbuy:1", exclude_last=False)
    assert stats.count == 4
    assert stats.low == 900
    assert stats.last == 950
    assert stats.median is not None


def test_lowest_offer_wins_per_cycle(tmp_path):
    store = PriceStore(tmp_path / "p.db")
    # Two offers of the same product in one cycle -> store the cheaper one.
    store.record([mk(1200, condition="good"), mk(999, condition="fair")], now=0)
    assert store.stats("bestbuy:1", exclude_last=False).last == 999


def test_exclude_last_protects_current_sample(tmp_path):
    store = PriceStore(tmp_path / "p.db")
    for i, p in enumerate([1000, 1000, 1000, 300]):
        store.record([mk(p)], now=i * 86400)
    stats = store.stats("bestbuy:1", exclude_last=True)
    assert stats.low == 1000      # baseline excludes the 300 sample
    assert stats.last == 300
    assert stats.prev == 1000


def test_persists_across_instances(tmp_path):
    path = tmp_path / "p.db"
    PriceStore(path).record([mk(500)], now=10)
    assert PriceStore(path).stats("bestbuy:1", exclude_last=False).low == 500


def test_retailers_kept_separate(tmp_path):
    store = PriceStore(tmp_path / "p.db")
    store.record([mk(100, retailer="bestbuy"), mk(200, retailer="ebay")], now=1)
    assert store.stats("bestbuy:1", exclude_last=False).last == 100
    assert store.stats("ebay:1", exclude_last=False).last == 200


def test_rollup_compacts_old_samples(tmp_path):
    store = PriceStore(tmp_path / "p.db", raw_days=7, retention_days=90)
    # 5 samples on day 0, then prune as if it's now day 10.
    for i in range(5):
        store.record([mk(1000 + i)], now=i * 3600)
    store.prune_and_rollup(now=10 * 86400)
    # Raw samples gone, but history survives via the daily rollup.
    raw_count = store.conn.execute("SELECT COUNT(*) FROM price_samples").fetchone()[0]
    rollup_count = store.conn.execute("SELECT COUNT(*) FROM daily_rollup").fetchone()[0]
    assert raw_count == 0
    assert rollup_count == 1
    stats = store.stats("bestbuy:1", exclude_last=False)
    assert stats.count == 5          # samples preserved in the rollup
    assert stats.low == 1000


def test_msrp_baseline_kept_highest(tmp_path):
    store = PriceStore(tmp_path / "p.db")
    store.record([mk(1500, regular=2000)], now=0)
    store.record([mk(1400, regular=1800)], now=86400)  # lower regular shouldn't lower msrp
    msrp = store.conn.execute("SELECT msrp FROM products WHERE product_key='bestbuy:1'").fetchone()[0]
    assert msrp == 2000


def test_record_alert_audit(tmp_path):
    store = PriceStore(tmp_path / "p.db")
    d = mk(199)
    d.reasons = ["⚡ test"]
    store.record_alert(d, "glitch", now=5)
    row = store.conn.execute("SELECT kind, price FROM alerts").fetchone()
    assert row == ("glitch", 199)
