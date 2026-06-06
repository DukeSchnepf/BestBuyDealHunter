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
- A **price-error / glitch detector** keeps its own **SQLite price history** per product and
  flags listings via five signals — below historical low, below rolling median, below MSRP,
  a robust median/MAD statistical outlier, and a sudden rate-of-change crash. Glitches get
  their own Discord alert lane with an optional `@here`/role ping, since they die within minutes.
- A **fast watchlist poller** can hit just the SKUs/searches you care about every couple of
  minutes (on top of the slower full sweep) so you catch short-lived mistakes in time.
- **Self-hosted, no third-party services:** SQLite is built into Python — your price history
  is yours. Run it on your own machine ([deploy/SELF_HOST.md](deploy/SELF_HOST.md)) or 24/7 on
  a tiny AWS box ([deploy/AWS_SETUP.md](deploy/AWS_SETUP.md)).

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
| `WATCH_SKUS` | _(none)_ | Best Buy SKUs to stalk for open-box drops |
| `WATCH_TERMS` | _(none)_ | eBay search terms for the fast watchlist poll |
| `WATCH_INTERVAL_MINUTES` | `0` | Fast watchlist poll interval (0 = off); on top of the full sweep |
| `PRICE_RAW_DAYS` / `PRICE_RETENTION_DAYS` | `7` / `90` | Raw-sample window / rollup retention |
| `MAX_ALERTS_PER_CYCLE` | `15` | Cap on *normal* deals per scan (glitches never capped) |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | _(none)_ | eBay keyset; enables the eBay source |
| `DISCORD_GLITCH_WEBHOOK_URL` | _(main)_ | Separate webhook for price-error alerts |
| `GLITCH_PING` | _(none)_ | `@here` / `<@&ROLE_ID>` to ping on a glitch |
| `GLITCH_FLOOR_RATIO` | `0.60` | Flag if price ≤ this × historical low |
| `GLITCH_MSRP_RATIO` | `0.40` | Flag if price ≤ this × MSRP (no history needed) |
| `GLITCH_MIN_CONFIDENCE` | `0.6` | Min combined confidence to fire a glitch alert |

### How glitch detection works

The bot records a price sample for *every* candidate it sees, **every cycle**, into a SQLite
database (`data/prices.db`) — building an honest price floor/median over time. Old per-cycle
samples are compacted to daily min/median/high after `PRICE_RAW_DAYS` and dropped after
`PRICE_RETENTION_DAYS`, so the file stays small (typically a few hundred MB–1 GB long-term).

Each cycle it scores survivors for "looks like a pricing error" using five independent signals:

1. **Below historical low** — price ≤ `GLITCH_FLOOR_RATIO` × the lowest ever recorded.
2. **Below rolling median** — price ≤ `GLITCH_MEDIAN_RATIO` × median.
3. **Below MSRP** — price ≤ `GLITCH_MSRP_RATIO` × list price *(works with zero history)*.
4. **Robust outlier** — a median/MAD modified z-score past `GLITCH_MAD_Z` *(resists sale noise)*.
5. **Rate-of-change crash** — price dropped ≥ `GLITCH_DROP_RATIO` since the previous sample.

Signals combine (noisy-OR) into a confidence (0–1); hits over `GLITCH_MIN_CONFIDENCE` are
flagged `⚡ POSSIBLE PRICE ERROR`, boosted to the top, and routed to the glitch lane.

**Warm-up:** the MSRP signal works on the first scan; floor/median arm after a few samples
(~minutes–hour); the robust statistical signal matures over **~1–2 weeks** as history fills in.
Treat alerts as *possible* errors — some get honored, some get cancelled, so move fast.

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
  storage.py         SQLite price history + daily rollup + alert audit log
  glitch.py          price-error detector (5 signals -> confidence)
  notify_discord.py  rich-embed Discord delivery (normal + glitch lanes)
  state.py           dedupe store (alert only on new/price-dropped)
  sources/
    base.py          Source interface (scan() / scan_watchlist() -> list[Deal])
    bestbuy.py       Best Buy source (Products + Open Box)
    ebay.py          eBay Browse API source (used/open-box/refurbished)
  hunter.py          orchestrator: scan -> history -> curate -> glitch -> dedupe -> notify
  watcher.py         continuous loop: slow full sweep + fast watchlist poll
main.py              CLI (--watch / --once / --dry-run)
dashboard.py         optional local web dashboard (Flask) — deals, glitches, on-demand scan
scripts/check_api.py API smoke test (Best Buy + eBay)
deploy/              self-host guide (Linux/macOS/Windows) + AWS setup + systemd + backups
setup.bat / run_*.bat  Windows one-click setup, watcher, and dashboard launchers
tests/               curation, GPU, glitch, storage, eBay tests (no network)
```

## Web dashboard

A lightweight local UI (no cloud, reads your SQLite history read-only):

```bash
pip install -r requirements-dashboard.txt
python dashboard.py          # Windows: double-click run_dashboard.bat
# open http://127.0.0.1:5000
```

Shows summary stats, your alert history (deals + ⚡ glitches, filterable), and a
**Run scan now** button for a live dry-run across all retailers (no Discord send).

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
