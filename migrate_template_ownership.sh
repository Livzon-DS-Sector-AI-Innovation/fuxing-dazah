#!/bin/bash
# 将历史巡检模板迁移到指定部门（宿主机执行）
# 用法: bash migrate_template_ownership.sh <部门名称>
# 示例: bash migrate_template_ownership.sh 动力部

DEPT="${1:?用法: bash migrate_template_ownership.sh <部门名称>}"

docker compose exec db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-dazah}" -c "
-- 1. 查看目标用户
SELECT id, name, department
FROM identity.users
WHERE department LIKE '%${DEPT}%' AND is_deleted = false
LIMIT 3;
"

echo ""
read -p "确认用上面第一个用户执行迁移？(y/N) " confirm
[ "$confirm" != "y" ] && echo "已取消" && exit 0

docker compose exec db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-dazah}" -c "
WITH target_user AS (
    SELECT id FROM identity.users
    WHERE department LIKE '%${DEPT}%' AND is_deleted = false
    LIMIT 1
)
UPDATE equipment.inspection_templates
SET created_by = (SELECT id FROM target_user),
    updated_by = (SELECT id FROM target_user),
    updated_at = now()
WHERE created_by IS NULL AND is_deleted = false;
"

echo "✅ 迁移完成"
