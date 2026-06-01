from bestbuy_hunter import curate
from bestbuy_hunter.config import Config
from bestbuy_hunter.models import Deal


def cfg():
    c = Config()  # defaults, no env required
    return c


def make(**kw) -> Deal:
    base = dict(sku=1, name="Item", price=100.0, regular=100.0, bucket="other")
    base.update(kw)
    return Deal(**base)


# --------------------------------------------------------------------------- #
# Rejections — the "no random accessory" guarantee
# --------------------------------------------------------------------------- #
def test_rejects_cheap_cable():
    d = make(name="USB-C Charging Cable", price=5.0, regular=10.0, bucket="other",
             category_name="Cables")
    assert not curate.passes(d, cfg())


def test_rejects_hard_keyword_even_if_big_discount():
    d = make(name="Protection Plan Geek Squad", price=20.0, regular=100.0, bucket="other")
    assert not curate.passes(d, cfg())


def test_rejects_unknown_accessory_not_in_allowlist():
    d = make(name="Phone Sticker Skin", price=20.0, regular=40.0, bucket="other",
             category_name="Decals")
    assert not curate.passes(d, cfg())


def test_rejects_low_discount_laptop():
    d = make(name="Some Laptop", price=98.0, regular=100.0, bucket="laptops")
    # only 2% off, no open-box, no big dollar saving -> rejected
    assert not curate.passes(d, cfg())


def test_rejects_below_min_price():
    d = make(name="Gaming Mouse", price=5.0, regular=20.0, bucket="other",
             category_name="Gaming Mice")
    assert not curate.passes(d, cfg())


# --------------------------------------------------------------------------- #
# Acceptances
# --------------------------------------------------------------------------- #
def test_accepts_openbox_laptop():
    d = make(name="Gaming Laptop", price=900.0, regular=1200.0, bucket="laptops",
             condition="excellent", source="openbox")
    assert curate.passes(d, cfg())


def test_accepts_rtx_5060_laptop_even_small_discount():
    d = make(name="Acer Nitro RTX 5060 Laptop", price=1190.0, regular=1200.0,
             bucket="laptops", gpu_tier=1)
    assert curate.passes(d, cfg())


def test_accepts_useful_peripheral_with_big_discount():
    d = make(name="Logitech Gaming Mouse", price=40.0, regular=70.0, bucket="other",
             category_name="Gaming Mice")
    # ~43% off, above the 35% peripheral threshold
    assert curate.passes(d, cfg())
    assert d.bucket == "peripheral"


def test_rejects_useful_peripheral_with_small_discount():
    d = make(name="Logitech Gaming Mouse", price=63.0, regular=70.0, bucket="other",
             category_name="Gaming Mice")
    # only 10% off, below 35% peripheral threshold
    assert not curate.passes(d, cfg())


def test_core_dollar_floor_accepts_big_savings():
    d = make(name="Desktop PC", price=920.0, regular=1000.0, bucket="desktops")
    # only 8% off but $80 saved (> $75 floor)
    assert curate.passes(d, cfg())


# --------------------------------------------------------------------------- #
# Scoring / ranking
# --------------------------------------------------------------------------- #
def test_gpu_laptop_outranks_accessory():
    laptop = make(name="RTX 5090 Laptop", price=2500.0, regular=3000.0,
                  bucket="laptops", gpu_tier=6, condition="excellent", source="openbox")
    mouse = make(name="Gaming Mouse", price=40.0, regular=80.0, bucket="peripheral",
                 category_name="Gaming Mice")
    ranked = curate.curate([mouse, laptop], cfg())
    assert ranked[0] is laptop
    assert laptop.score > mouse.score


def test_curate_dedupes_same_offer():
    a = make(sku=42, name="Laptop", price=900.0, regular=1200.0, bucket="laptops",
             condition="good", source="openbox")
    b = make(sku=42, name="Laptop", price=900.0, regular=1200.0, bucket="laptops",
             condition="good", source="openbox")
    ranked = curate.curate([a, b], cfg())
    assert len(ranked) == 1


def test_price_cap_filters_expensive():
    c = cfg()
    c.price_cap = 1000.0
    d = make(name="RTX 5090 Laptop", price=2500.0, regular=3000.0, bucket="laptops", gpu_tier=6)
    assert not curate.passes(d, c)
