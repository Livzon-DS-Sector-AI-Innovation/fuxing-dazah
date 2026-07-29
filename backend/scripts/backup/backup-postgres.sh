#!/bin/bash
# PostgreSQL 备份脚本
# 用法: ./backup-postgres.sh [保留天数]
# 示例: ./backup-postgres.sh 30

set -euo pipefail

RETENTION_DAYS="${1:-30}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups/postgres}"
LOG_FILE="$BACKUP_DIR/backup.log"
LOCK_FILE="$BACKUP_DIR/.backup.lock"

mkdir -p "$BACKUP_DIR"

# 防止重叠执行
if [ -f "$LOCK_FILE" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 上一次备份尚未完成，跳过。" | tee -a "$LOG_FILE"
  exit 0
fi
trap 'rm -f "$LOCK_FILE"' EXIT
touch "$LOCK_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始 PostgreSQL 备份..." | tee -a "$LOG_FILE"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DUMP_FILE="$BACKUP_DIR/dazah_$(date +%Y%m%d_%H%M%S).sql.gz"

START_TIME=$(date +%s)

cd "$BACKEND_DIR"
docker compose exec -T db pg_dumpall -U postgres | gzip > "$DUMP_FILE"

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
SIZE=$(du -h "$DUMP_FILE" | cut -f1)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份完成: $DUMP_FILE ($SIZE, 耗时 ${ELAPSED}s)" | tee -a "$LOG_FILE"

# 清理过期备份
DELETED=$(find "$BACKUP_DIR" -name "dazah_*.sql.gz" -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理 $DELETED 个过期备份 (>$RETENTION_DAYS 天)" | tee -a "$LOG_FILE"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 完成。" | tee -a "$LOG_FILE"
