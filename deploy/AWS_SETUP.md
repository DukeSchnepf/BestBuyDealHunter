# Hosting the Deal Hunter on AWS (24/7)

The bot is a small always-on poller with a local SQLite file, so the right home is a
**tiny Linux VM** — EC2 `t4g.micro` (cheapest, ARM/Graviton) or Lightsail (simplest). Don't
use Lambda: its disk is ephemeral and SQLite needs to persist. You don't need RDS/DynamoDB —
SQLite on the instance is plenty at this scale.

**Cost:** ~free for the first 12 months on the AWS Free Tier (750 instance-hours/month), then
roughly **$3–6/month** all-in. The DB stays well under a few GB.

---

## Option A — EC2 `t4g.micro` (recommended)

1. **Launch the instance**
   - AMI: *Ubuntu Server 24.04 (ARM64)*; type: `t4g.micro`.
   - Storage: 8–20 GB gp3 is plenty.
   - Security group: **no inbound rules needed** except SSH (port 22) from your IP. The bot
     only makes *outbound* calls (Best Buy, eBay, Discord), so keep it locked down.

2. **Connect & install prerequisites**
   ```bash
   ssh ubuntu@<instance-ip>
   sudo apt update && sudo apt install -y python3-venv python3-pip git sqlite3 awscli
   ```

3. **Get the code & configure**
   ```bash
   git clone <your-repo-url> ~/BestBuyDealHunter
   cd ~/BestBuyDealHunter
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   cp .env.example .env
   nano .env          # add BBY_API_KEY, eBay keys, DISCORD_WEBHOOK_URL, etc.
   .venv/bin/python scripts/check_api.py   # confirm keys work
   ```

4. **Run it as a service (auto-starts, auto-restarts)**
   ```bash
   sudo cp deploy/bestbuy-hunter.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now bestbuy-hunter
   journalctl -u bestbuy-hunter -f          # follow the logs
   ```
   The unit file assumes user `ubuntu` and `~/BestBuyDealHunter`; edit paths if different.

---

## Option B — Lightsail (simplest)

1. Create a Lightsail instance → **Linux/Ubuntu**, the **$3.50–5/mo** plan.
2. Use the browser SSH, then follow steps 2–4 above identically.
Lightsail bundles instance + storage + bandwidth into one fixed monthly price.

---

## Backups to S3 (optional, pennies/month)

1. Create an S3 bucket (e.g. `my-dealhunter-backups`).
2. Give the instance access: attach an **IAM role** with `s3:PutObject` on that bucket
   (EC2 → Actions → Security → Modify IAM role), or run `aws configure` with a key.
3. Schedule the backup script:
   ```bash
   export BACKUP_BUCKET=s3://my-dealhunter-backups/bestbuy-hunter
   crontab -e
   # nightly at 03:30:
   30 3 * * * BACKUP_BUCKET=s3://my-dealhunter-backups/bestbuy-hunter /home/ubuntu/BestBuyDealHunter/deploy/backup_to_s3.sh >> /home/ubuntu/backup.log 2>&1
   ```
   It uses SQLite's online `.backup`, so it's safe to run while the watcher is live.

---

## Operating notes

- **Update the bot:** `cd ~/BestBuyDealHunter && git pull && sudo systemctl restart bestbuy-hunter`
- **Inspect history any time:** `sqlite3 data/prices.db 'SELECT kind, COUNT(*) FROM alerts GROUP BY kind;'`
- **Tune polling:** set `POLL_INTERVAL_MINUTES` (full sweep) and `WATCH_INTERVAL_MINUTES`
  + `WATCH_SKUS`/`WATCH_TERMS` (fast glitch poll) in `.env`, then restart. Stay under
  Best Buy (~5 req/s, ~50k/day) and eBay (~5k Browse calls/day) limits.
- **Give glitch detection time:** MSRP-based glitches fire immediately; the history-based
  signals sharpen over ~1–2 weeks as `prices.db` fills in.
