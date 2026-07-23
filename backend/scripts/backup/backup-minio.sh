#!/bin/bash
# MinIO 备份脚本 — 将全部 bucket 同步到本地
# 用法: ./backup-minio.sh
# 说明: 此脚本做镜像同步（当前状态快照），不是历史版本备份。
#       空间占用 = MinIO 实际数据量，不会持续增长，无需定期清理。

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/backups/minio}"
LOG_FILE="$BACKUP_DIR/backup.log"

# MinIO 连接信息（与 .env.production 一致，宿主机通过端口映射访问）
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始 MinIO 备份..." | tee -a "$LOG_FILE"

# Linux 用 host 网络，macOS/Windows 用 host.docker.internal
if [ "$(uname)" = "Linux" ]; then
  MC_ENDPOINT="http://localhost:9000"
  NETWORK_ARG="--network host"
else
  MC_ENDPOINT="http://host.docker.internal:9000"
  NETWORK_ARG=""
fi

# 同步所有 bucket 到本地（mirror 只传输差异，首次慢后续快）
docker run --rm $NETWORK_ARG \
  --entrypoint sh \
  -v "$BACKUP_DIR:/backup" \
  minio/mc:latest \
  -c "
    mc alias set local $MC_ENDPOINT $MINIO_ACCESS_KEY $MINIO_SECRET_KEY &&
    mc ls local | while read -r _ _ _ _ name; do
      bucket=\"\${name%/}\"
      echo \"同步 bucket: \$bucket\"
      mc mirror --overwrite local/\$bucket /backup/\$bucket
    done
  "

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份完成。" | tee -a "$LOG_FILE"
