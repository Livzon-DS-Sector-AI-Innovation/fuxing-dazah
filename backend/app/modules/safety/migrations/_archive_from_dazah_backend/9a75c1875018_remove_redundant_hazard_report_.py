"""remove_redundant_hazard_report_rectification_and_verify_fields

Revision ID: 9a75c1875018
Revises: 5ed72e04c090
Create Date: 2026-06-18 16:45:43.654686
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9a75c1875018'
down_revision: Union[str, None] = '5ed72e04c090'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 先删除外键约束 ──
    op.drop_constraint(
        'hazard_reports_rectification_replied_by_fkey',
        'hazard_reports', schema='safety', type_='foreignkey',
    )
    op.drop_constraint(
        'hazard_reports_verify_level_1_by_fkey',
        'hazard_reports', schema='safety', type_='foreignkey',
    )
    op.drop_constraint(
        'hazard_reports_verify_level_2_by_fkey',
        'hazard_reports', schema='safety', type_='foreignkey',
    )
    op.drop_constraint(
        'hazard_reports_verify_level_3_by_fkey',
        'hazard_reports', schema='safety', type_='foreignkey',
    )

    # ── 删除 16 个冗余列 ──
    # 整改回复 4 列
    op.drop_column('hazard_reports', 'rectification_reply', schema='safety')
    op.drop_column('hazard_reports', 'rectification_replied_at', schema='safety')
    op.drop_column('hazard_reports', 'rectification_replied_by', schema='safety')
    op.drop_column('hazard_reports', 'rectification_replied_by_name', schema='safety')
    # 一级复核 4 列
    op.drop_column('hazard_reports', 'verify_level_1_by', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_1_by_name', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_1_at', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_1_opinion', schema='safety')
    # 二级复核 4 列
    op.drop_column('hazard_reports', 'verify_level_2_by', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_2_by_name', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_2_at', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_2_opinion', schema='safety')
    # 三级复核 4 列
    op.drop_column('hazard_reports', 'verify_level_3_by', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_3_by_name', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_3_at', schema='safety')
    op.drop_column('hazard_reports', 'verify_level_3_opinion', schema='safety')


def downgrade() -> None:
    # ── 恢复 16 个列 ──
    op.add_column('hazard_reports', sa.Column('rectification_reply', sa.TEXT(), nullable=True, comment='整改回复内容'), schema='safety')
    op.add_column('hazard_reports', sa.Column('rectification_replied_at', postgresql.TIMESTAMP(timezone=True), nullable=True, comment='整改回复时间'), schema='safety')
    op.add_column('hazard_reports', sa.Column('rectification_replied_by', sa.UUID(), nullable=True, comment='整改回复人ID'), schema='safety')
    op.add_column('hazard_reports', sa.Column('rectification_replied_by_name', sa.VARCHAR(length=100), nullable=True, comment='整改回复人姓名'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_1_by', sa.UUID(), nullable=True, comment='部门负责人复核人ID'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_1_by_name', sa.VARCHAR(length=100), nullable=True, comment='部门负责人复核人姓名'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_1_at', postgresql.TIMESTAMP(timezone=True), nullable=True, comment='部门负责人复核时间'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_1_opinion', sa.TEXT(), nullable=True, comment='部门负责人复核意见'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_2_by', sa.UUID(), nullable=True, comment='分管领导复核人ID'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_2_by_name', sa.VARCHAR(length=100), nullable=True, comment='分管领导复核人姓名'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_2_at', postgresql.TIMESTAMP(timezone=True), nullable=True, comment='分管领导复核时间'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_2_opinion', sa.TEXT(), nullable=True, comment='分管领导复核意见'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_3_by', sa.UUID(), nullable=True, comment='检查人员复核人ID'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_3_by_name', sa.VARCHAR(length=100), nullable=True, comment='检查人员复核人姓名'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_3_at', postgresql.TIMESTAMP(timezone=True), nullable=True, comment='检查人员复核时间'), schema='safety')
    op.add_column('hazard_reports', sa.Column('verify_level_3_opinion', sa.TEXT(), nullable=True, comment='检查人员复核意见'), schema='safety')

    # ── 恢复外键约束 ──
    op.create_foreign_key(
        'hazard_reports_rectification_replied_by_fkey',
        'hazard_reports', 'users', ['rectification_replied_by'], ['id'],
        source_schema='safety', referent_schema='identity',
    )
    op.create_foreign_key(
        'hazard_reports_verify_level_1_by_fkey',
        'hazard_reports', 'users', ['verify_level_1_by'], ['id'],
        source_schema='safety', referent_schema='identity',
    )
    op.create_foreign_key(
        'hazard_reports_verify_level_2_by_fkey',
        'hazard_reports', 'users', ['verify_level_2_by'], ['id'],
        source_schema='safety', referent_schema='identity',
    )
    op.create_foreign_key(
        'hazard_reports_verify_level_3_by_fkey',
        'hazard_reports', 'users', ['verify_level_3_by'], ['id'],
        source_schema='safety', referent_schema='identity',
    )
