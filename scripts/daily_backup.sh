#!/bin/bash
# Daily douyin.db backup
set -e

DB_PATH="/Users/claw/work/douyin-recorder/douyin.db"
BACKUP_DIR="/Users/claw/work/douyin-recorder"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/douyin.db.backup.${TIMESTAMP}"

# Create backup
cp "$DB_PATH" "$BACKUP_FILE"
chmod 600 "$BACKUP_FILE"

# Clean backups older than 30 days
find "$BACKUP_DIR" -name "douyin.db.backup.*" -mtime +30 -delete 2>/dev/null || true

echo "$(date '+%Y-%m-%d %H:%M:%S') Backup created: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
