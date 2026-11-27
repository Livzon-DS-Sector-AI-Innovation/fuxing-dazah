"""SOP 二级表口径调整：二级表的操作是「生成材料」而非「转培训」

生成材料即完成：状态 待转训/已转训 → 待生成/已生成；
transferred_by/transferred_at（转培训操作人/时间）更名
generated_by/generated_at（生成材料操作人/时间）。

Revision ID: a3f7c1d9e5b2
Revises: c9d2e5a8b1f4
Create Date: 2026-11-26 18:40:00.000000
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f7c1d9e5b2'
down_revision: str | None = 'c9d2e5a8b1f4'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("UPDATE hr.sop_training_entries SET status = '已生成' WHERE status = '已转训'")
    op.alter_column(
        'sop_training_entries', 'status',
        existing_type=sa.String(length=16),
        server_default='待生成',
        comment='待生成/已生成',
        schema='hr',
    )
    op.alter_column(
        'sop_training_entries', 'transferred_by',
        existing_type=sa.String(length=64),
        new_column_name='generated_by',
        comment='生成材料操作人',
        schema='hr',
    )
    op.alter_column(
        'sop_training_entries', 'transferred_at',
        existing_type=sa.DateTime(timezone=True),
        new_column_name='generated_at',
        comment='生成材料时间',
        schema='hr',
    )


def downgrade() -> None:
    op.alter_column(
        'sop_training_entries', 'generated_at',
        existing_type=sa.DateTime(timezone=True),
        new_column_name='transferred_at',
        comment='转培训时间',
        schema='hr',
    )
    op.alter_column(
        'sop_training_entries', 'generated_by',
        existing_type=sa.String(length=64),
        new_column_name='transferred_by',
        comment='转培训操作人',
        schema='hr',
    )
    op.alter_column(
        'sop_training_entries', 'status',
        existing_type=sa.String(length=16),
        server_default='待转训',
        comment='待转训/已转训',
        schema='hr',
    )
    op.execute("UPDATE hr.sop_training_entries SET status = '已转训' WHERE status = '已生成'")
