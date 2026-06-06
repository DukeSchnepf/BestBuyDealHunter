# Self-hosting on your own machine

Run the deal hunter 24/7 on your own computer (no AWS needed). Works on Linux,
macOS, and Windows. eBay is included automatically — as soon as your eBay keys
are in `.env`, the bot scans Best Buy **and** eBay every cycle.

---

## 1. Prerequisites

- **Python 3.11+** — check with `python3 --version` (Windows: `python --version`).
  Get it from [python.org](https://www.python.org/downloads/) if missing.
- **git** — to clone and pull updates.

## 2. Get the code & install

```bash
git clone <your-repo-url> BestBuyDealHunter
cd BestBuyDealHunter
python3 -m venv .venv
# activate the virtualenv:
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows (PowerShell)
pip install -r requirements.txt
```

## 3. Configure your keys

```bash
cp .env.example .env             # Windows: copy .env.example .env
```
Edit `.env` and fill in:
```
BBY_API_KEY=...                  # Best Buy
EBAY_CLIENT_ID=...               # eBay production App ID (Client ID)
EBAY_CLIENT_SECRET=...           # eBay production Cert ID (Client Secret)
DISCORD_WEBHOOK_URL=...          # where alerts go
# optional fast glitch poller:
WATCH_INTERVAL_MINUTES=2
WATCH_TERMS=RTX 5090 laptop, RTX 5080 laptop
```
> eBay turns on **automatically** when both eBay values are present — nothing else to flip.

## 4. Verify it works

```bash
python scripts/check_api.py      # confirms Best Buy AND eBay keys work
python main.py --dry-run         # ranked deals from both retailers, no Discord send
```
You should see Best Buy + eBay candidates ranked together, and the startup log
listing `Sources enabled: bestbuy, ebay`.

## 5. Run it continuously

`python main.py --watch` runs forever. To keep it alive across reboots/crashes,
pick the option for your OS:

### Linux (systemd — recommended)
Use the included unit (edit the paths/user inside it first):
```bash
sudo cp deploy/bestbuy-hunter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bestbuy-hunter
journalctl -u bestbuy-hunter -f      # watch logs
```

### Linux/macOS (quick & dirty — tmux)
```bash
tmux new -s hunter
source .venv/bin/activate && python main.py --watch
# detach with Ctrl-b then d ; reattach later with: tmux attach -t hunter
```

### macOS (launchd — survives reboot)
Create `~/Library/LaunchAgents/com.dealhunter.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.dealhunter</string>
  <key>ProgramArguments</key>
  <array>
    <string>/full/path/BestBuyDealHunter/.venv/bin/python</string>
    <string>/full/path/BestBuyDealHunter/main.py</string>
    <string>--watch</string>
  </array>
  <key>WorkingDirectory</key><string>/full/path/BestBuyDealHunter</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/dealhunter.log</string>
  <key>StandardErrorPath</key><string>/tmp/dealhunter.err</string>
</dict></plist>
```
Then: `launchctl load ~/Library/LaunchAgents/com.dealhunter.plist`

### Windows (NSSM — run as a service)
1. Download [NSSM](https://nssm.cc/download), then in an admin prompt:
   ```
   nssm install DealHunter
   ```
2. In the dialog: **Path** = `...\BestBuyDealHunter\.venv\Scripts\python.exe`,
   **Arguments** = `main.py --watch`,
   **Startup directory** = `...\BestBuyDealHunter`.
3. Start it: `nssm start DealHunter`. It now runs in the background and on boot.

*(Simplest Windows alternative: open a terminal, `python main.py --watch`, and
leave it running. Or use Task Scheduler with "At log on" → start the script.)*

## 6. Day-to-day

- **Update:** `git pull` then restart (systemd: `sudo systemctl restart bestbuy-hunter`;
  others: stop and re-run).
- **Logs:** systemd → `journalctl -u bestbuy-hunter -f`; launchd → `/tmp/dealhunter.log`;
  tmux → the attached window.
- **Inspect price history:** `sqlite3 data/prices.db 'SELECT kind, COUNT(*) FROM alerts GROUP BY kind;'`
- **Footprint:** tiny — a single Python process and a SQLite file (a few hundred
  MB to ~1 GB long-term). Leave your machine on for it to keep polling.

## 7. Keep your keys safe

`.env` and `data/` are gitignored — never commit them. If a key leaks, rotate it
in the provider's portal (Best Buy / eBay / Discord).
