#!/usr/bin/env bash
# 数据库备份脚本：pg_dump + gzip + AES-256 加密 + 保留轮转
# 用法：backup.sh [数据库名] [保留份数(默认7)]
# 环境变量：BACKUP_DIR（默认 ./backups）、BACKUP_PASSPHRASE（必填，可用 MAXKB_DB_PASSWORD 之外的独立口令）
# 恢复示例：
#   openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in backup.enc | gunzip | psql -h <host> -U postgres <db>
set -euo pipefail

DB_NAME="${1:-maxkb}"
KEEP="${2:-7}"
BACKUP_DIR="${BACKUP_DIR:-$(pwd)/backups}"
PASSPHRASE="${BACKUP_PASSPHRASE:-}"

if [ -z "$PASSPHRASE" ]; then
  echo "ERROR: BACKUP_PASSPHRASE is required (use a dedicated key, not the DB password)" >&2
  exit 1
fi

PGHOST="${MAXKB_DB_HOST:-127.0.0.1}"
PGPORT="${MAXKB_DB_PORT:-5432}"
PGUSER="${MAXKB_DB_USER:-postgres}"
PGPASSWORD="${MAXKB_DB_PASSWORD:-}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/${DB_NAME}-${STAMP}.dump.enc"
TMP="$(mktemp)"

echo "[backup] dumping $DB_NAME -> $OUT"
PGPASSWORD="$PGPASSWORD" pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$DB_NAME" -Fc | gzip | \
  openssl enc -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -out "$OUT"
rm -f "$TMP"
echo "[backup] done: $(du -h "$OUT" | cut -f1)"

# 轮转：按 mtime 保留最近 KEEP 份
ls -1t "$BACKUP_DIR"/${DB_NAME}-*.dump.enc 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  echo "[backup] rotate out: $old"
  rm -f "$old"
done
echo "[backup] kept: $KEEP"
