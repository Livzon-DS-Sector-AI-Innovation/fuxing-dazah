"""add_reason_and_rejected_status_to_alert_records

Revision ID: f4a59df9f07f
Revises: 734214838342
Create Date: 2026-08-05 14:21:54.228241
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a59df9f07f'
down_revision: Union[str, None] = '734214838342'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 新增 reason 列
    op.add_column(
        'energy_alert_records',
        sa.Column('reason', sa.Text(), nullable=True,
                  comment='异常原因（车间负责人填写）'),
        schema='energy',
    )
    # 2. 修改 status CHECK 约束，加入 'rejected'
    op.drop_constraint('ck_energy_alert_record_status',
                       'energy_alert_records', schema='energy')
    op.create_check_constraint(
        'ck_energy_alert_record_status',
        'energy_alert_records',
        "status IN ('pending', 'processed', 'ignored', 'rejected')",
        schema='energy',
    )
    # 3. 创建 partial unique constraint 让软删除的重复添加→删除→添加模式正常工作
    #    (alert record 本身不需要，但为了一致性保留)


def downgrade() -> None:
    op.drop_constraint('ck_energy_alert_record_status',
                       'energy_alert_records', schema='energy')
    op.create_check_constraint(
        'ck_energy_alert_record_status',
        'energy_alert_records',
        "status IN ('pending', 'processed', 'ignored')",
        schema='energy',
    )
    op.drop_column('energy_alert_records', 'reason', schema='energy')
