"""data: annual plan company-wide items to factory level

Revision ID: 4cb39e7a28c0
Revises: 84437cea925f
Create Date: 2026-08-31 19:13:48.203637
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cb39e7a28c0'
down_revision: Union[str, None] = '84437cea925f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """一次性数据归类：年度计划中「公司全体」类明细归入同年度「厂级」计划。

    匹配口径：target_audience 精确等于 公司全员/公司全体员工/全体员工。
    无同年度厂级计划时自动创建（状态草稿）。幂等：已归类的明细不重复处理。
    """
    op.execute(
        """
        DO $$
        DECLARE y integer; pid uuid;
        BEGIN
          FOR y IN
            SELECT DISTINCT p.year
            FROM hr.annual_training_plan_items i
            JOIN hr.annual_training_plans p ON i.plan_id = p.id
            WHERE i.is_deleted = false AND p.is_deleted = false
              AND i.target_audience IN ('公司全员', '公司全体员工', '全体员工')
          LOOP
            SELECT id INTO pid FROM hr.annual_training_plans
            WHERE department = '厂级' AND year = y AND is_deleted = false
            LIMIT 1;
            IF pid IS NULL THEN
              INSERT INTO hr.annual_training_plans (id, year, department, status)
              VALUES (gen_random_uuid(), y, '厂级', '草稿')
              RETURNING id INTO pid;
            END IF;
            UPDATE hr.annual_training_plan_items SET plan_id = pid
            WHERE is_deleted = false
              AND target_audience IN ('公司全员', '公司全体员工', '全体员工')
              AND plan_id IN (
                SELECT id FROM hr.annual_training_plans
                WHERE year = y AND is_deleted = false
              );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # 数据归类不回滚：无可靠的逆向映射（原归属部门未保留）
    pass
