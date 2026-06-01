from bestbuy_hunter import gpu


def test_detects_each_tier():
    assert gpu.detect_tier("Acer Nitro Laptop GeForce RTX 5060") == 1
    assert gpu.detect_tier("MSI Katana RTX 5060 Ti 16GB") == 2
    assert gpu.detect_tier("ASUS TUF Gaming RTX 5070") == 3
    assert gpu.detect_tier("Lenovo Legion RTX 5070 Ti") == 4
    assert gpu.detect_tier("Razer Blade RTX 5080") == 5
    assert gpu.detect_tier("Alienware RTX 5090 Desktop") == 6


def test_no_separators_and_picks_highest():
    assert gpu.detect_tier("RTX5070Ti gaming") == 4
    # picks the highest tier mentioned
    assert gpu.detect_tier("compare RTX 5060 vs RTX 5080") == 5


def test_rejects_non_targets():
    assert gpu.detect_tier("GeForce RTX 4060 laptop") == 0
    assert gpu.detect_tier("RTX 5050 budget") == 0
    assert gpu.detect_tier("USB-C cable") == 0


def test_tier_from_details():
    details = [{"name": "Graphics", "value": "NVIDIA GeForce RTX 5070 Laptop GPU"}]
    assert gpu.tier_from_details("Some Laptop", details) == 3


def test_label():
    assert gpu.label(1) == "RTX 5060"
    assert gpu.label(6) == "RTX 5090"
    assert gpu.label(0) == ""
