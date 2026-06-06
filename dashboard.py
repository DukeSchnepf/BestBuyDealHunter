#!/usr/bin/env python3
"""Local web dashboard for the Best Buy Deal Hunter.

A lightweight Flask app that reads the SQLite price history and shows recent
hand-picked deals + price-error glitches, summary stats, and per-product price
history. Includes a "Run scan now" button that does a live dry-run scan (no
Discord send) so you can see what's hot on demand.

Run:
    pip install -r requirements-dashboard.txt
    python dashboard.py
Then open http://127.0.0.1:5000 in your browser.

It only needs the database to *view* history; the scan button additionally needs
your API keys in .env. It opens the DB read-only, so it's safe to run alongside
the watcher.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

try:
    from flask import Flask, request, redirect, url_for
except ImportError:  # pragma: no cover
    raise SystemExit(
        "Flask is not installed. Run:  pip install -r requirements-dashboard.txt"
    )

from bestbuy_hunter.config import Config

cfg = Config.from_env()
DB_PATH = cfg.data_dir / "prices.db"
app = Flask(__name__)

# Cache one Hunter for the manual-scan button (lazy: only built when used).
_hunter = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _conn() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def _fmt_time(ts: int | None) -> str:
    if not ts:
        return "—"
    return dt.datetime.fromtimestamp(ts).strftime("%b %d %H:%M")


def _summary(c: sqlite3.Connection) -> dict:
    by_kind = {row["kind"]: row["n"] for row in
               c.execute("SELECT kind, COUNT(*) n FROM alerts GROUP BY kind")}
    return {
        "products": c.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "samples": c.execute("SELECT COUNT(*) FROM price_samples").fetchone()[0],
        "deals": by_kind.get("deal", 0),
        "glitches": by_kind.get("glitch", 0),
        "last": _fmt_time(c.execute("SELECT MAX(ts) FROM alerts").fetchone()[0]),
    }


def _recent_alerts(c: sqlite3.Connection, kind: str | None, limit: int = 100) -> list[sqlite3.Row]:
    q = ("SELECT a.ts, a.kind, a.price, a.confidence, a.reason, "
         "p.name, p.url, p.retailer, p.bucket, p.gpu_tier, p.msrp "
         "FROM alerts a LEFT JOIN products p ON a.product_key = p.product_key ")
    args: tuple = ()
    if kind in ("deal", "glitch"):
        q += "WHERE a.kind = ? "
        args = (kind,)
    q += "ORDER BY a.ts DESC LIMIT ?"
    return c.execute(q, (*args, limit)).fetchall()


# --------------------------------------------------------------------------- #
# Rendering (inline, dependency-free)
# --------------------------------------------------------------------------- #
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deal Hunter</title><style>
:root{{color-scheme:dark}}
body{{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:24px}}
h1{{margin:0 0 4px}} a{{color:#5ab0ff;text-decoration:none}} a:hover{{text-decoration:underline}}
.sub{{color:#8a93a2;margin-bottom:20px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}}
.card{{background:#1a1d24;border:1px solid #262b35;border-radius:10px;padding:14px 18px;min-width:120px}}
.card b{{font-size:24px;display:block}}
.tabs{{margin:14px 0}} .tabs a{{margin-right:14px;padding:6px 12px;border-radius:8px;background:#1a1d24;border:1px solid #262b35}}
.tabs a.on{{background:#2a3140;color:#fff}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid #20242d;vertical-align:top}}
th{{color:#8a93a2;font-weight:600}}
.glitch{{background:rgba(231,76,60,.10)}}
.tag{{font-size:11px;padding:2px 7px;border-radius:6px;background:#2a3140}}
.tag.g{{background:#7a241c;color:#ffd9d4}} .tag.gpu{{background:#16432a;color:#bdf0cf}}
.price{{font-weight:700}} .off{{color:#7fd18b}} .muted{{color:#8a93a2}}
button{{background:#2a6cf0;color:#fff;border:0;border-radius:8px;padding:9px 16px;font-size:14px;cursor:pointer}}
.scanbox{{background:#1a1d24;border:1px solid #262b35;border-radius:10px;padding:16px;margin-bottom:20px}}
.err{{color:#ff8a80}}
</style></head><body>
<h1>🛒 Deal Hunter</h1>
<div class="sub">local dashboard · DB: {db}</div>
<div class="cards">
  <div class="card"><b>{s[deals]}</b>deals alerted</div>
  <div class="card"><b style="color:#ff8a80">{s[glitches]}</b>glitches</div>
  <div class="card"><b>{s[products]:,}</b>products tracked</div>
  <div class="card"><b>{s[samples]:,}</b>price samples</div>
  <div class="card"><b>{s[last]}</b>last alert</div>
</div>
<div class="scanbox">
  <form method="post" action="/scan" style="display:inline">
    <button type="submit">⟳ Run scan now (live, no Discord)</button>
  </form>
  <span class="muted" style="margin-left:10px">Hits the live APIs — takes ~10–30s.</span>
  {scan}
</div>
<div class="tabs">
  <a class="{t_all}" href="/">All</a>
  <a class="{t_deal}" href="/?kind=deal">Deals</a>
  <a class="{t_glitch}" href="/?kind=glitch">⚡ Glitches</a>
</div>
{table}
</body></html>"""


def _row_html(r: sqlite3.Row) -> str:
    is_glitch = r["kind"] == "glitch"
    name = r["name"] or "(unknown)"
    url = r["url"] or "#"
    price = r["price"] or 0
    msrp = r["msrp"] or 0
    off = ""
    if msrp and msrp > price:
        off = f'<span class="off">{(1-price/msrp)*100:.0f}% off ${msrp:,.0f}</span>'
    tags = f'<span class="tag {"g" if is_glitch else ""}">{r["kind"]}</span> '
    if r["gpu_tier"]:
        tags += f'<span class="tag gpu">GPU t{r["gpu_tier"]}</span> '
    conf = f'{(r["confidence"] or 0)*100:.0f}%' if is_glitch else ""
    return (
        f'<tr class="{"glitch" if is_glitch else ""}">'
        f'<td class="muted">{_fmt_time(r["ts"])}</td>'
        f'<td><a href="{url}" target="_blank">{name[:80]}</a><br>'
        f'<span class="muted" style="font-size:12px">{(r["reason"] or "")[:110]}</span></td>'
        f'<td>{r["retailer"] or ""}</td>'
        f'<td class="price">${price:,.2f}<br>{off}</td>'
        f'<td>{tags}{conf}</td>'
        f'</tr>'
    )


def _table_html(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return ('<p class="muted">No alerts yet. The watcher logs deals and glitches here '
                'as it finds them — or press “Run scan now” above.</p>')
    body = "".join(_row_html(r) for r in rows)
    return ('<table><tr><th>When</th><th>Item</th><th>Retailer</th>'
            f'<th>Price</th><th>Type</th></tr>{body}</table>')


def _scan_html(deals, error: str | None) -> str:
    if error:
        return f'<div class="err" style="margin-top:12px">{error}</div>'
    if deals is None:
        return ""
    if not deals:
        return '<div class="muted" style="margin-top:12px">Scan ran — nothing passed curation right now.</div>'
    rows = "".join(
        f'<tr class="{"glitch" if d.is_glitch else ""}"><td>{i}</td>'
        f'<td><a href="{d.url}" target="_blank">{d.name[:80]}</a></td>'
        f'<td>{d.retailer}</td><td class="price">${d.price:,.2f}</td>'
        f'<td>{d.pct_off:.0f}%</td><td>{("⚡" if d.is_glitch else "")} {d.score:.0f}</td></tr>'
        for i, d in enumerate(deals[:25], 1)
    )
    return ('<table style="margin-top:14px"><tr><th>#</th><th>Item</th><th>Retailer</th>'
            f'<th>Price</th><th>Off</th><th>Score</th></tr>{rows}</table>')


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
def _render(kind: str | None, scan_deals=None, scan_error=None):
    c = _conn()
    if c is None:
        s = {"deals": 0, "glitches": 0, "products": 0, "samples": 0, "last": "—"}
        table = ('<p class="muted">No database yet at <code>%s</code>. '
                 'Start the watcher (<code>python main.py --watch</code>) or press '
                 '“Run scan now”.</p>' % DB_PATH)
    else:
        s = _summary(c)
        table = _table_html(_recent_alerts(c, kind))
        c.close()
    return PAGE.format(
        db=DB_PATH, s=s, table=table,
        scan=_scan_html(scan_deals, scan_error),
        t_all="on" if not kind else "",
        t_deal="on" if kind == "deal" else "",
        t_glitch="on" if kind == "glitch" else "",
    )


@app.route("/")
def index():
    kind = request.args.get("kind")
    return _render(kind if kind in ("deal", "glitch") else None)


@app.route("/scan", methods=["POST"])
def scan():
    global _hunter
    try:
        cfg.validate_sources()
    except Exception as exc:
        return _render(None, scan_deals=[], scan_error=str(exc))
    try:
        if _hunter is None:
            from bestbuy_hunter.hunter import Hunter
            _hunter = Hunter(cfg)
        result = _hunter.run_once(dry_run=True)
        deals = sorted(result.glitches + result.deals, key=lambda d: d.score, reverse=True)
        return _render(None, scan_deals=deals)
    except Exception as exc:  # surface API/network errors in the UI
        return _render(None, scan_deals=[], scan_error=f"Scan failed: {exc}")


if __name__ == "__main__":
    port = int(__import__("os").getenv("DASHBOARD_PORT", "5000"))
    print(f"Deal Hunter dashboard → http://127.0.0.1:{port}  (Ctrl-C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False)
