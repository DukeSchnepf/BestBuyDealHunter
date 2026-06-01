#!/usr/bin/env python3
"""Best Buy Deal Hunter — CLI entry point.

Usage:
    python main.py --watch        Continuous watcher (default): poll, dedupe, alert to Discord.
    python main.py --once         Single scan: curate, alert, exit.
    python main.py --dry-run      Single scan: curate, print ranked table, NO Discord send.

Requires BBY_API_KEY (and DISCORD_WEBHOOK_URL for alerts) in the environment or .env.
"""
from __future__ import annotations

import argparse
import logging
import sys

from bestbuy_hunter.client import BestBuyClient
from bestbuy_hunter.config import Config
from bestbuy_hunter.hunter import Hunter
from bestbuy_hunter import gpu
from bestbuy_hunter.watcher import watch


def _print_table(deals) -> None:
    if not deals:
        print("\nNo deals passed curation this scan.\n")
        return
    print(f"\n=== {len(deals)} hand-picked deals (best first) ===\n")
    for i, d in enumerate(deals, 1):
        cond = "NEW" if d.condition == "new" else f"OB/{d.condition}"
        gpu_lbl = f" [{gpu.label(d.gpu_tier)}]" if d.gpu_tier else ""
        why = f"  ({', '.join(d.reasons)})" if d.reasons else ""
        print(
            f"{i:>2}. [{d.score:6.1f}] {cond:>12} | ${d.price:>9,.2f} "
            f"({d.pct_off:>4.0f}% off ${d.dollar_off:>6,.0f}) | {d.name[:70]}{gpu_lbl}{why}"
        )
        if d.url:
            print(f"      {d.url}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Best Buy deal hunter")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="continuous watcher (default)")
    mode.add_argument("--once", action="store_true", help="single scan + alert, then exit")
    mode.add_argument("--dry-run", action="store_true", help="single scan, print only, no Discord")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = Config.from_env()
    try:
        cfg.require_api_key()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    client = BestBuyClient(cfg.api_key)
    hunter = Hunter(cfg, client)

    if args.dry_run:
        deals = hunter.run_once(dry_run=True)
        _print_table(deals)
        return 0

    if args.once:
        deals = hunter.run_once(dry_run=False)
        _print_table(deals)
        print(f"Alerted on {len(deals)} new deal(s).")
        return 0

    # default: watch
    watch(hunter, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
