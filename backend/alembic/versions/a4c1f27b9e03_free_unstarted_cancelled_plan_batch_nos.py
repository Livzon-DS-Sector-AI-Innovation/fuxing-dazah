"""软删历史变更删除留下的零痕迹报废计划批次，释放被占批号

背景：change_plan_order 删除计划项时，此前对从未开工的批次只置
status=cancelled 而不软删——partial unique index uq_production_batches_no
按 is_deleted=false 占号，导致"删除并补位"永远撞上自己刚删的批号。
新语义改为零痕迹批次整批软删；本迁移回收存量僵尸号（必须同时满足：
已报废、计划批次、无存活工序执行、无谱系链接、无存活计划分配——
即此前某次计划变更/删除已经断开计划关联的行）。有执行/谱系留痕的
报废批次保持可见继续占号，不受影响。
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a4c1f27b9e03'
down_revision: str | None = '7f8d7b28b55e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ZOMBIE_SQL = """
UPDATE production.batches b
SET is_deleted = true, updated_at = now()
WHERE b.is_deleted = false
  AND b.status = 'cancelled'
  AND b.creation_type = 'plan'
  AND NOT EXISTS (
      SELECT 1 FROM production.node_executions e
      WHERE e.batch_id = b.id AND e.is_deleted = false
  )
  AND NOT EXISTS (
      SELECT 1 FROM production.batch_links l
      WHERE (l.parent_batch_id = b.id OR l.child_batch_id = b.id)
        AND l.is_deleted = false
  )
  AND NOT EXISTS (
      SELECT 1 FROM production.plan_allocations pa
      WHERE pa.batch_id = b.id AND pa.is_deleted = false
  )
"""


def upgrade() -> None:
    op.execute(_ZOMBIE_SQL)


def downgrade() -> None:
    # 软删的僵尸批次无法与"删除并补位"新语义产生的行区分，不做逆操作。
    pass
