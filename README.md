# 🛒 Best Buy Deal Hunter

A Python bot that **hand-picks genuinely good Best Buy deals** and pushes them to Discord —
not a firehose of "20% off a random cable."

It's tuned for one mission first: finding an **RTX 5060-or-better laptop or desktop**
(open-box / used / refurbished preferred, to save big), plus desktops, GPUs/CPUs, components,
monitors, and *useful* gaming peripherals at steep discounts. A scoring engine ranks every find
so the best deals land at the top, and a watcher only pings you about **new** ones.

**Multi-retailer + price-error detection:**
- **Best Buy** (Products + Open Box API) and **eBay** (Browse API — used/open-box/refurbished
  RTX 50-series gear) run side by side through one retailer-agnostic pipeline.
- A **price-error / glitch detector** builds a rolling price history per product and flags
  listings that collapse far below their historical low, median, or MSRP — the kind of
  short-lived pricing mistakes deal communities hunt for. Glitches get their own Discord
  alert lane with an optional `@here`/role ping, since they die within minutes.

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

> **Note on "used":** Best Buy's API covers new/on-sale/clearance + **Open Box** (no
> third-party *used*). For genuinely *used / refurbished* gear, enable the **eBay** source —
> it searches used/open-box/refurbished RTX 50-series laptops and desktops directly.

## Setup

At least one source must be configured (Best Buy and/or eBay).

1. **Best Buy API key** (free): https://developer.bestbuy.com/ → sign up → activate.
2. **eBay keyset** (free, optional but recommended for used gear): https://developer.bestbuy.com/
   → create an app → use the **production** App ID (Client ID) + Cert ID (Client Secret).
   eBay turns on automatically once both are set.
3. **Discord webhook URL:** Channel Settings → Integrations → Webhooks → New Webhook → Copy URL.
   Optionally make a second webhook for a dedicated `#glitches` channel.
4. **Install & configure:**

   ```bash
   pip install -r requirements.txt
   cp .env.example .env      # fill in keys + DISCORD_WEBHOOK_URL
   ```

5. **Confirm the APIs work:**

   ```bash
   python scripts/check_api.py
   ```

   Prints resolved category IDs, sample on-sale laptops, sample open-box offers, and (if
   configured) a sample eBay search.

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
| `MAX_ALERTS_PER_CYCLE` | `15` | Cap on *normal* deals per scan (glitches never capped) |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | _(none)_ | eBay keyset; enables the eBay source |
| `DISCORD_GLITCH_WEBHOOK_URL` | _(main)_ | Separate webhook for price-error alerts |
| `GLITCH_PING` | _(none)_ | `@here` / `<@&ROLE_ID>` to ping on a glitch |
| `GLITCH_FLOOR_RATIO` | `0.60` | Flag if price ≤ this × historical low |
| `GLITCH_MSRP_RATIO` | `0.40` | Flag if price ≤ this × MSRP (no history needed) |
| `GLITCH_MIN_CONFIDENCE` | `0.6` | Min combined confidence to fire a glitch alert |

### How glitch detection works

The bot records a rolling price history per product (`data/price_history.json`) for *every*
candidate it sees, building an honest price floor over time. Each cycle it scores survivors for
"looks like a pricing error" using three independent signals — **below historical low**,
**fraction of rolling median**, and **fraction of MSRP** — combined into a confidence (0–1).
The MSRP signal works immediately; the history signals sharpen as data accrues. High-confidence
hits are flagged `⚡ POSSIBLE PRICE ERROR`, boosted to the top, and routed to the glitch lane.
Treat them as *possible* — some get honored, some get cancelled.

To stalk a specific laptop's open-box price, grab its SKU from the Best Buy URL
(`.../site/<name>/<SKU>.p`) and add it to `WATCH_SKUS`.

## Project layout

```
bestbuy_hunter/
  config.py          env + thresholds + category map + GPU tiers + glitch + source toggles
  client.py          Best Buy API client (rate limit, pagination, retries)
  categories.py      resolve Best Buy category names -> IDs (cached, with fallbacks)
  gpu.py             RTX 50-series detection + tier ranking
  models.py          Deal dataclass (retailer-agnostic normalized item)
  curate.py          the hand-pick scoring/gating engine
  pricehistory.py    rolling per-product price history (glitch baseline)
  glitch.py          price-error detector (floor / median / MSRP signals)
  notify_discord.py  rich-embed Discord delivery (normal + glitch lanes)
  state.py           dedupe store (alert only on new/price-dropped)
  sources/
    base.py          Source interface (scan() -> list[Deal])
    bestbuy.py       Best Buy source (Products + Open Box)
    ebay.py          eBay Browse API source (used/open-box/refurbished)
  hunter.py          orchestrator: scan -> history -> curate -> glitch -> dedupe -> notify
  watcher.py         continuous loop with backoff
main.py              CLI (--watch / --once / --dry-run)
scripts/check_api.py API smoke test (Best Buy + eBay)
tests/               curation, GPU, glitch, price-history, eBay tests (no network)
```

### Adding more sources

Implement `Source.scan() -> list[Deal]` in `bestbuy_hunter/sources/`, set `Deal.retailer`,
and register it in `sources/__init__.py:build_sources`. Curation, price history, glitch
detection, and notifications all work on the shared `Deal` model, so a new retailer is a
single self-contained adapter. (Amazon via Keepa is the natural next add.)

## Tests

```bash
pytest
```

Covers the curation rules (junk rejected, good deals accepted/ranked) and GPU tier detection —
all offline, no API key needed.
