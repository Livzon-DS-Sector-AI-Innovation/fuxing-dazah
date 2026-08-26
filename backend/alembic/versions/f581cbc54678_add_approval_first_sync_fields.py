"""add approval-first sync fields

Revision ID: f581cbc54678
Revises: ae2ff4e45582
Create Date: 2026-08-19 16:45:00.000000

职称评审审批先行模式：活动增加审批定义编码，申报增加审批实例编码（防重）。
仅包含 hr.title_review 相关变更，其他模块无关变更已手工清理。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f581cbc54678'
down_revision: Union[str, None] = 'ae2ff4e45582'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('title_review_activities', sa.Column('approval_code', sa.String(length=64), nullable=True, comment='飞书审批定义编码（申报先过审批，通过后自动同步）'), schema='hr')
    op.add_column('title_review_applications', sa.Column('approval_instance_code', sa.String(length=64), nullable=True, comment='飞书审批实例编码（审批先行模式，防重复同步）'), schema='hr')
    op.create_index('uq_tapp_approval_instance', 'title_review_applications', ['approval_instance_code'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_tapp_approval_instance', table_name='title_review_applications', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_column('title_review_applications', 'approval_instance_code', schema='hr')
    op.drop_column('title_review_activities', 'approval_code', schema='hr')
