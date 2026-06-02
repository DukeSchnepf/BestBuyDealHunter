"""Price-error / glitch detection.

Glitches are different from ordinary "% off regular" sales: the price is often
just an absurd number with no discount flag, and the listing dies within
minutes. We detect them statistically from three independent signals, combine
them into a confidence (0-1), and let the orchestrator route high-confidence
hits to a dedicated, faster alert lane.

Signals:
  * floor  — price collapses far below the product's own historical low
  * median — price is a fraction of its rolling median
  * msrp   — price is a tiny fraction of MSRP/regular (works with zero history)
  * robust — modified z-score (median/MAD) flags a statistical outlier
  * drop   — price cratered since the previous observation (rate-of-change)

The history-based signals only count once we have enough samples so a
brand-new product doesn't false-positive on its first sighting; ``msrp`` works
from the very first scan.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import GlitchConfig
from .models import Deal
from .storage import PriceStats


@dataclass
class GlitchVerdict:
    is_glitch: bool
    confidence: float          # 0.0 - 1.0
    reason: str                # human-readable explanation


def assess(deal: Deal, stats: PriceStats, cfg: GlitchConfig) -> GlitchVerdict:
    """Score a deal for "looks like a pricing error" likelihood."""
    if not cfg.enabled or deal.price <= 0:
        return GlitchVerdict(False, 0.0, "")

    signals: list[tuple[float, str]] = []  # (confidence_contribution, reason)
    have_history = stats.count >= cfg.min_history

    # 1) Below historical floor.
    if have_history and stats.low and stats.low > 0:
        ratio = deal.price / stats.low
        if ratio <= cfg.floor_ratio:
            drop = (1 - ratio) * 100
            # Deeper below the floor => higher confidence (cap at 0.9).
            conf = min(0.5 + (cfg.floor_ratio - ratio), 0.9)
            signals.append((conf, f"{drop:.0f}% below historical low ${stats.low:,.0f}"))

    # 2) Fraction of rolling median.
    if have_history and stats.median and stats.median > 0:
        ratio = deal.price / stats.median
        if ratio <= cfg.median_ratio:
            conf = min(0.4 + (cfg.median_ratio - ratio), 0.85)
            signals.append((conf, f"{ratio*100:.0f}% of median ${stats.median:,.0f}"))

    # 3) Fraction of MSRP / regular (no history required).
    if deal.regular and deal.regular > 0:
        ratio = deal.price / deal.regular
        if ratio <= cfg.msrp_ratio:
            off = (1 - ratio) * 100
            conf = min(0.35 + (cfg.msrp_ratio - ratio), 0.8)
            signals.append((conf, f"{off:.0f}% off MSRP ${deal.regular:,.0f}"))

    # 4) Robust outlier via modified z-score (median + MAD). Resistant to the
    # occasional sale spike that would skew a mean/stdev approach.
    if (stats.count >= cfg.min_history_robust and stats.median
            and stats.mad and stats.mad > 0):
        mod_z = 0.6745 * (deal.price - stats.median) / stats.mad
        if mod_z <= -cfg.mad_z_threshold:
            conf = min(0.5 + (abs(mod_z) - cfg.mad_z_threshold) * 0.05, 0.9)
            signals.append((conf, f"statistical outlier ({abs(mod_z):.1f} MADs below normal)"))

    # 5) Rate-of-change: price cratered since the previous observation.
    if stats.prev and stats.prev > 0:
        drop = (stats.prev - deal.price) / stats.prev
        if drop >= cfg.drop_ratio:
            conf = min(0.4 + (drop - cfg.drop_ratio), 0.85)
            signals.append((conf, f"{drop*100:.0f}% crash from ${stats.prev:,.0f} last seen"))

    if not signals:
        return GlitchVerdict(False, 0.0, "")

    # Combine independent signals (noisy-OR): more agreeing signals => higher
    # confidence, but no single weak signal alone clears a high bar.
    product = 1.0
    for conf, _ in signals:
        product *= (1 - conf)
    combined = 1 - product
    reason = "; ".join(r for _, r in signals)

    return GlitchVerdict(
        is_glitch=combined >= cfg.min_confidence,
        confidence=round(combined, 3),
        reason=reason,
    )
