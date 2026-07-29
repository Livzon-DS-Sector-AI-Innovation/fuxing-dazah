# 数据库 & 文件备份

生产环境 PostgreSQL 和 MinIO 默认**没有自动备份**，本目录提供最简备份方案。

## 快速部署

在**生产服务器**上执行：

```bash
# 1. 创建备份目录
sudo mkdir -p /opt/backups/postgres /opt/backups/minio
sudo chown $USER:$USER /opt/backups/postgres /opt/backups/minio

# 2. 赋予脚本执行权限
chmod +x scripts/backup/backup-postgres.sh
chmod +x scripts/backup/backup-minio.sh

# 3. 手动跑一次确认能正常备份
BACKUP_DIR=/opt/backups/postgres ./scripts/backup/backup-postgres.sh
BACKUP_DIR=/opt/backups/minio ./scripts/backup/backup-minio.sh

# 4. 确认备份文件生成
ls -lh /opt/backups/postgres/
ls -lh /opt/backups/minio/
```

## 配置定时任务

```bash
# 编辑 crontab
crontab -e

# 添加以下两行：
# PostgreSQL：每天凌晨 2 点备份，保留 30 天
0 2 * * * BACKUP_DIR=/opt/backups/postgres /path/to/backend/scripts/backup/backup-postgres.sh 30 >> /opt/backups/postgres/cron.log 2>&1

# MinIO：每周日凌晨 3 点同步
0 3 * * 0 BACKUP_DIR=/opt/backups/minio /path/to/backend/scripts/backup/backup-minio.sh >> /opt/backups/minio/cron.log 2>&1
```

> 把 `/path/to/backend` 替换为实际的 `backend/` 目录绝对路径。

## 备份策略说明

| 服务 | 方式 | 频率 | 保留 | 空间占用 |
|------|------|------|------|----------|
| PostgreSQL | `pg_dumpall` 全量导出 | 每天 | 30 天历史 | 随备份次数增长，自动清理 |
| MinIO | `mc mirror` 镜像同步 | 每周 | 当前快照 | = MinIO 实际数据量，不增长 |

MinIO 用的是镜像同步（当前状态），不保留历史版本。因为 MinIO 存储的主要是巡检照片等文件，增量大但总量可控，需要历史版本的话改为 `mc mirror` 到带日期后缀的目录即可。

## 恢复

### PostgreSQL 恢复

```bash
# 停掉 app 容器（避免写入冲突）
cd /path/to/backend
docker compose stop app

# 恢复
gunzip -c /opt/backups/postgres/dazah_20260722_020000.sql.gz | \
  docker compose exec -T db psql -U postgres -d dazah

# 重启
docker compose up -d app
```

### MinIO 恢复

```bash
# 反向同步到 MinIO
docker run --rm --network host \
  -v /opt/backups/minio:/backup \
  minio/mc:latest \
  sh -c "
    mc alias set local http://localhost:9000 minioadmin minioadmin &&
    for dir in /backup/*/; do
      bucket=\$(basename \"\$dir\")
      echo \"恢复 bucket: \$bucket\"
      mc mirror --overwrite /backup/\$bucket local/\$bucket
    done
  "
```

> macOS 上把 `--network host` 去掉，把 `localhost` 换成 `host.docker.internal`。

## 异地备份（推荐）

将备份目录同步到另一台机器或云存储：

```bash
# rsync 到远程机器
0 4 * * * rsync -avz /opt/backups/ backup@192.168.x.x:/backups/

# 或 rclone 到云存储（S3/OSS/COS）
0 4 * * * rclone sync /opt/backups/ remote:bucket-name/
```

## 监控建议

至少做两件事：
1. 定期检查 `/opt/backups/*/backup.log` 是否正常
2. 每季度做一次恢复演练，确认备份文件可用
