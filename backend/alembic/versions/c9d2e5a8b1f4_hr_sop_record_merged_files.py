"""SOP 登记支持一条记录含多份培训文件（合并登记）

新列 files：JSON 数组 [{file_name, file_no}]；为空时回落到单文件列
file_name/file_no（历史数据不动）。合并登记时 file_name/file_no 存
「；」连接的展示串，题库匹配等结构化访问走 files。
file_no 拓宽到 512，容纳多份编号连接后的展示串。

Revision ID: c9d2e5a8b1f4
Revises: b6e04c8f12a7
Create Date: 2026-11-26 15:30:00.000000
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9d2e5a8b1f4'
down_revision: str | None = 'b6e04c8f12a7'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        'sop_training_records',
        sa.Column('files', sa.Text(), nullable=True, comment='登记的培训文件列表 JSON [{file_name, file_no}]；空=单文件（看 file_name/file_no）'),
        schema='hr',
    )
    op.alter_column(
        'sop_training_records',
        'file_no',
        existing_type=sa.String(length=128),
        type_=sa.String(length=512),
        schema='hr',
    )


def downgrade() -> None:
    op.alter_column(
        'sop_training_records',
        'file_no',
        existing_type=sa.String(length=512),
        type_=sa.String(length=128),
        schema='hr',
    )
    op.drop_column('sop_training_records', 'files', schema='hr')
