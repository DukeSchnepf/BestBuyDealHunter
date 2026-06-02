#!/usr/bin/env bash
# Back up the SQLite price history to S3. Uses SQLite's online .backup so it's
# safe to run while the watcher is writing (no half-written WAL copies).
#
# Schedule it with cron, e.g. nightly at 03:30:
#   crontab -e
#   30 3 * * * /home/ubuntu/BestBuyDealHunter/deploy/backup_to_s3.sh >> /home/ubuntu/backup.log 2>&1
set -euo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/BestBuyDealHunter}"
DB="${APP_DIR}/data/prices.db"
BUCKET="${BACKUP_BUCKET:-s3://CHANGE-ME/bestbuy-hunter}"   # set BACKUP_BUCKET or edit this
STAMP="$(date +%Y%m%d-%H%M%S)"
TMP="/tmp/prices-${STAMP}.db"

if [[ ! -f "$DB" ]]; then
  echo "No DB at $DB yet; nothing to back up."
  exit 0
fi

sqlite3 "$DB" ".backup '${TMP}'"
gzip -f "$TMP"
aws s3 cp "${TMP}.gz" "${BUCKET}/prices-${STAMP}.db.gz"
rm -f "${TMP}.gz"
echo "Backed up to ${BUCKET}/prices-${STAMP}.db.gz"
