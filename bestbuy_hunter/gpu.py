"""RTX 50-series GPU detection and tier ranking.

The headline mission is an *RTX 5060-or-better* machine, so we detect the GPU
from a product's name + spec details and rank it. Tier mapping:

    5060=1  5060 Ti=2  5070=3  5070 Ti=4  5080=5  5090=6

``detect_tier`` returns 0 when no qualifying RTX 50-series GPU is found.
"""
from __future__ import annotations

import re
from typing import Iterable

# Ordered so that "Ti" variants are checked before the base model and higher
# models before lower ones. Each entry: (regex, tier).
_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\brtx\s*5090\b", re.I), 6),
    (re.compile(r"\brtx\s*5080\b", re.I), 5),
    (re.compile(r"\brtx\s*5070\s*ti\b", re.I), 4),
    (re.compile(r"\brtx\s*5070\b", re.I), 3),
    (re.compile(r"\brtx\s*5060\s*ti\b", re.I), 2),
    (re.compile(r"\brtx\s*5060\b", re.I), 1),
]

_TIER_LABEL: dict[int, str] = {
    1: "RTX 5060",
    2: "RTX 5060 Ti",
    3: "RTX 5070",
    4: "RTX 5070 Ti",
    5: "RTX 5080",
    6: "RTX 5090",
}


def detect_tier(*texts: str) -> int:
    """Return the highest RTX 50-series tier found across the given texts (0 = none)."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return 0
    # Normalize separators so "RTX5070Ti" / "RTX 5070 Ti" both match.
    blob = blob.replace("-", " ").replace("_", " ")
    best = 0
    for pattern, tier in _PATTERNS:
        if tier > best and pattern.search(blob):
            best = tier
    return best


def tier_from_details(name: str, details: Iterable[dict]) -> int:
    """Detect tier from a product name plus Best Buy ``details`` (name/value pairs)."""
    spec_values = []
    for d in details or []:
        # details entries look like {"name": "Graphics", "value": "NVIDIA GeForce RTX 5070"}
        val = d.get("value") if isinstance(d, dict) else None
        if val:
            spec_values.append(str(val))
    return detect_tier(name, *spec_values)


def label(tier: int) -> str:
    """Human-readable GPU label for a tier (empty string for 0)."""
    return _TIER_LABEL.get(tier, "")
