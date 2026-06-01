# 🛒 Best Buy Deal Hunter

A Python bot that **hand-picks genuinely good Best Buy deals** and pushes them to Discord —
not a firehose of "20% off a random cable."

It's tuned for one mission first: finding an **RTX 5060-or-better laptop or desktop**
(open-box preferred, to save big), plus desktops, GPUs/CPUs, components, monitors, and
*useful* gaming peripherals at steep discounts. A scoring engine ranks every find so the
best deals land at the top, and a watcher only pings you about **new** ones.

## How it hand-picks (no junk)

Every candidate runs through the curation engine in `bestbuy_hunter/curate.py`:

1. **Category allowlist** — only laptops, desktops, GPUs, CPUs, components, monitors, and
   recognized useful gaming peripherals (mechanical keyboards, gaming mice, headsets,
   controllers, capture cards, webcams). Cables, screen protectors, warranties, gift cards,
   etc. are rejected outright.
2. **Price floor** — drops sub-$15 sticker/cable noise.
3. **Tiered discount thresholds** — lenient on core compute (open-box, 15%+, or $75+ saved),
   strict on accessories (35%+). This is what kills the "random 20% off accessory" spam.
4. **RTX 5060+ priority** — any laptop/desktop/GPU at tier ≥ your `GPU_MIN_TIER` is always
   surfaced if it has *any* discount or is open-box, and gets a big score boost.
5. **Score & rank** — % off, $ saved, category weight, GPU tier, rating, and open-box
   condition (excellent > certified > good > fair) combine into a score; results sort best-first.

> **Note on "used":** Best Buy's API exposes new/on-sale/clearance items and **Open Box**
> (the big savings lever) — not third-party *used* listings. Open Box is the closest
> equivalent and is fully covered.

## Setup

1. **Get a Best Buy API key** (free): https://developer.bestbuy.com/ → sign up → activate.
2. **Get a Discord webhook URL:** Channel Settings → Integrations → Webhooks → New Webhook → Copy URL.
3. **Install & configure:**

   ```bash
   pip install -r requirements.txt
   cp .env.example .env      # then fill in BBY_API_KEY and DISCORD_WEBHOOK_URL
   ```

4. **Confirm the API works:**

   ```bash
   python scripts/check_api.py
   ```

   Prints resolved category IDs, sample on-sale laptops, and sample open-box offers.

## Run

```bash
python main.py --watch      # continuous watcher (default): poll, dedupe, alert to Discord
python main.py --once       # single scan, alert, exit
python main.py --dry-run    # single scan, print ranked table, NO Discord send
python main.py --once -v    # verbose/debug logging
```

The watcher polls every `POLL_INTERVAL_MINUTES` (default 12), well under Best Buy's
~5 req/sec and ~50k/day limits. It remembers what it's seen in `data/seen.json` and only
alerts on **new or price-dropped** offers, so you won't get repeat pings.

## Tuning

All knobs live in `.env` (see `.env.example`) and `bestbuy_hunter/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `PRICE_CAP` | _(none)_ | Hard price ceiling; blank = rank by quality only |
| `GPU_MIN_TIER` | `1` | Min RTX 50-series tier to flag (1=5060 … 6=5090) |
| `THRESHOLD_CORE` | `15` | Min % off for laptops/desktops/GPUs/CPUs |
| `THRESHOLD_COMPONENT` | `20` | Min % off for RAM/SSD/mobo/PSU/case |
| `THRESHOLD_MONITOR` | `20` | Min % off for monitors |
| `THRESHOLD_PERIPHERAL` | `35` | Min % off for gaming peripherals |
| `CORE_DOLLAR_FLOOR` | `75` | Core items always pass if they save ≥ this many $ |
| `WATCH_SKUS` | _(none)_ | Comma-separated SKUs to stalk for open-box drops |
| `MAX_ALERTS_PER_CYCLE` | `15` | Cap on deals pushed per scan (avoids first-run spam) |

To stalk a specific laptop's open-box price, grab its SKU from the Best Buy URL
(`.../site/<name>/<SKU>.p`) and add it to `WATCH_SKUS`.

## Project layout

```
bestbuy_hunter/
  config.py          env + thresholds + category map + GPU tiers
  client.py          Best Buy API client (rate limit, pagination, retries)
  categories.py      resolve category names -> IDs (cached, with fallbacks)
  gpu.py             RTX 50-series detection + tier ranking
  models.py          Deal dataclass (normalized item)
  curate.py          the hand-pick scoring/gating engine
  notify_discord.py  rich-embed Discord webhook delivery
  state.py           dedupe store (alert only on new/price-dropped)
  hunter.py          orchestrator: scan -> normalize -> curate -> dedupe -> notify
  watcher.py         continuous loop with backoff
main.py              CLI (--watch / --once / --dry-run)
scripts/check_api.py API smoke test
tests/               curation + GPU unit tests (no network)
```

## Tests

```bash
pytest
```

Covers the curation rules (junk rejected, good deals accepted/ranked) and GPU tier detection —
all offline, no API key needed.
