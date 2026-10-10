#!/usr/bin/env bash
# Consistent SQLite backup + photos archive into data/backups, keeping 14 days.
# IMPORTANT: also copy data/backups OFF this server (another machine or cloud storage).
set -euo pipefail
cd "$(dirname "$0")"
stamp=$(date +%F)
mkdir -p data/backups
sudo docker compose exec -T app python - <<PY
import sqlite3
src = sqlite3.connect("/data/bagkeeper.sqlite")
dst = sqlite3.connect("/data/backups/db-$stamp.sqlite")
src.backup(dst)
PY
tar -czf "data/backups/uploads-$stamp.tgz" -C data uploads
find data/backups -type f -mtime +14 -delete
