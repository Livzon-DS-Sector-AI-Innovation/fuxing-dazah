"""quality: report audit fields

Revision ID: 3187ab7fb5cd
Revises: 42b64f1303c1
Create Date: 2026-10-08 15:51:26.260460
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3187ab7fb5cd'
down_revision: Union[str, None] = '42b64f1303c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('report_records', sa.Column('audit_status', sa.String(length=20), server_default='pending', nullable=False, comment='报告单审核状态：pending 待初审 / approved 已通过 / rejected 已退回'), schema='quality')
    op.add_column('report_records', sa.Column('audited_by', sa.Uuid(), nullable=True, comment='审核人，逻辑引用 identity.users.id'), schema='quality')
    op.add_column('report_records', sa.Column('audited_at', sa.DateTime(timezone=True), nullable=True, comment='审核时间'), schema='quality')
    op.add_column('report_records', sa.Column('audit_comment', sa.String(length=500), nullable=True, comment='审核备注/退回原因'), schema='quality')



def downgrade() -> None:
    op.drop_column('report_records', 'audit_comment', schema='quality')
    op.drop_column('report_records', 'audited_at', schema='quality')
    op.drop_column('report_records', 'audited_by', schema='quality')
    op.drop_column('report_records', 'audit_status', schema='quality')
