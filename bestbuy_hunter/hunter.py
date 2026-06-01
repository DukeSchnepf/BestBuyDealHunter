"""Orchestrator: scan all sources -> price history -> curate -> glitch -> dedupe -> notify."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import curate, glitch, notify_discord
from .config import Config
from .models import Deal
from .pricehistory import PriceHistory
from .sources import Source, build_sources
from .state import SeenStore

log = logging.getLogger("bestbuy_hunter.hunter")


@dataclass
class CycleResult:
    deals: list[Deal]       # normal new deals alerted this cycle
    glitches: list[Deal]    # price-error deals alerted this cycle


class Hunter:
    def __init__(self, cfg: Config, sources: list[Source] | None = None) -> None:
        self.cfg = cfg
        self.sources = sources if sources is not None else build_sources(cfg)
        self.seen = SeenStore(cfg.data_dir / "seen.json")
        self.history = PriceHistory(cfg.data_dir / "price_history.json")
        if not self.sources:
            log.warning("No sources are configured/enabled.")

    # ------------------------------------------------------------------ #
    def scan(self) -> list[Deal]:
        """Run every source; one failing source never sinks the cycle."""
        candidates: list[Deal] = []
        for source in self.sources:
            try:
                candidates.extend(source.scan())
            except Exception as exc:
                log.error("Source %s failed: %s", source.name, exc)
        log.info("Collected %d raw candidates across %d source(s).",
                 len(candidates), len(self.sources))
        return candidates

    # ------------------------------------------------------------------ #
    def _apply_glitch_detection(self, deals: list[Deal]) -> None:
        """Flag likely pricing errors and boost their score. Mutates deals."""
        if not self.cfg.glitch.enabled:
            return
        for d in deals:
            stats = self.history.stats(d.history_key, exclude_last=True)
            verdict = glitch.assess(d, stats, self.cfg.glitch)
            if verdict.is_glitch:
                d.is_glitch = True
                d.glitch_confidence = verdict.confidence
                d.reasons.insert(
                    0, f"⚡ POSSIBLE PRICE ERROR ({verdict.confidence*100:.0f}%): {verdict.reason}"
                )
                d.score += 200.0 * verdict.confidence

    # ------------------------------------------------------------------ #
    def run_once(self, dry_run: bool = False) -> CycleResult:
        """One full cycle. Returns the NEW deals + glitches alerted this cycle."""
        raw = self.scan()

        # Record price history for ALL candidates first so the glitch detector
        # compares against a baseline that excludes this cycle's sample.
        self.history.record(raw)

        ranked = curate.curate(raw, self.cfg)
        log.info("%d deals passed curation.", len(ranked))

        self._apply_glitch_detection(ranked)
        ranked.sort(key=lambda d: d.score, reverse=True)

        glitches = [d for d in ranked if d.is_glitch]
        normal = [d for d in ranked if not d.is_glitch]

        new_glitches = self.seen.filter_new(glitches)
        new_normal = self.seen.filter_new(normal)[: self.cfg.max_alerts_per_cycle]
        log.info("New this scan: %d glitch(es), %d normal deal(s).",
                 len(new_glitches), len(new_normal))

        if not dry_run:
            if new_glitches:
                notify_discord.send_glitches(self.cfg, new_glitches)
            if new_normal:
                header = f"🛒 **{len(new_normal)} new hand-picked deal(s)**"
                notify_discord.send(self.cfg.discord_webhook_url, new_normal, header=header)
            # Remember everything curated so we don't re-alert beyond the cap next cycle.
            self.seen.remember(ranked)

        return CycleResult(deals=new_normal, glitches=new_glitches)
