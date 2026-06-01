from bestbuy_hunter import glitch
from bestbuy_hunter.config import GlitchConfig
from bestbuy_hunter.models import Deal
from bestbuy_hunter.pricehistory import PriceStats


def cfg(**kw) -> GlitchConfig:
    c = GlitchConfig()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def deal(price, regular=0.0) -> Deal:
    return Deal(sku=1, name="RTX 5090 Laptop", price=price, regular=regular, bucket="laptops")


# --------------------------------------------------------------------------- #
# MSRP signal (no history)
# --------------------------------------------------------------------------- #
def test_msrp_glitch_no_history():
    # $200 on a $2000 laptop => 90% off MSRP, well past 0.40 ratio
    v = glitch.assess(deal(200.0, regular=2000.0), PriceStats(0, None, None, 200.0), cfg())
    assert v.is_glitch
    assert v.confidence >= 0.6
    assert "MSRP" in v.reason


def test_normal_sale_is_not_glitch():
    # 25% off, ordinary sale -> not a glitch
    v = glitch.assess(deal(1500.0, regular=2000.0), PriceStats(10, 1400.0, 1800.0, 1500.0), cfg())
    assert not v.is_glitch


# --------------------------------------------------------------------------- #
# Historical floor signal
# --------------------------------------------------------------------------- #
def test_below_historical_floor():
    stats = PriceStats(count=10, low=1800.0, median=2000.0, last=600.0)
    # $600 vs historical low $1800 => 33% of low, far under 0.60
    v = glitch.assess(deal(600.0), stats, cfg())
    assert v.is_glitch
    assert "below historical low" in v.reason


def test_floor_ignored_without_enough_history():
    stats = PriceStats(count=2, low=1800.0, median=2000.0, last=600.0)
    v = glitch.assess(deal(600.0), stats, cfg(min_history=4))
    # not enough history, and no regular price -> no signal
    assert not v.is_glitch


def test_median_signal():
    stats = PriceStats(count=8, low=900.0, median=1000.0, last=400.0)
    # $400 is 40% of median $1000 (< 0.50). low is $900 so floor ratio=0.44 also triggers
    v = glitch.assess(deal(400.0), stats, cfg())
    assert v.is_glitch


def test_disabled_returns_no_glitch():
    v = glitch.assess(deal(50.0, regular=2000.0), PriceStats(0, None, None, 50.0), cfg(enabled=False))
    assert not v.is_glitch


def test_combined_confidence_higher_than_single():
    # both floor + median + msrp agree -> very high confidence
    stats = PriceStats(count=10, low=1800.0, median=2000.0, last=150.0)
    v = glitch.assess(deal(150.0, regular=2000.0), stats, cfg())
    assert v.is_glitch
    assert v.confidence > 0.9
