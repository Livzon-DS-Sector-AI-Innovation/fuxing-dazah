"""hr add position headcount and incident records

Revision ID: 79da991ca741
Revises: 1b88f752e31b
Create Date: 2026-10-19 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '79da991ca741'
down_revision: Union[str, None] = '1b88f752e31b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('hr_incident_records',
    sa.Column('incident_type', sa.String(length=32), nullable=False, comment='work_injury 工伤 / labor_dispute 劳动纠纷'),
    sa.Column('employee_name', sa.String(length=64), nullable=True, comment='当事人姓名'),
    sa.Column('employee_number', sa.String(length=64), nullable=True, comment='当事人工号'),
    sa.Column('department', sa.String(length=128), nullable=True, comment='所属部门'),
    sa.Column('occurred_date', sa.String(length=32), nullable=True, comment='发生日期 YYYY-MM-DD'),
    sa.Column('description', sa.String(length=500), nullable=True, comment='情况描述'),
    sa.Column('status', sa.String(length=32), server_default='processing', nullable=False, comment='processing 处理中 / closed 已结案'),
    sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_hr_incident_occurred_date', 'hr_incident_records', ['occurred_date'], unique=False, schema='hr')
    op.create_index('ix_hr_incident_type', 'hr_incident_records', ['incident_type'], unique=False, schema='hr')
    op.add_column('positions', sa.Column('headcount', sa.Integer(), nullable=True, comment='编制人数（人力看板编制达成率依据）'), schema='hr')
    op.create_foreign_key(None, 'positions', 'users', ['created_by'], ['id'], source_schema='hr', referent_schema='identity')
    op.create_foreign_key(None, 'positions', 'users', ['updated_by'], ['id'], source_schema='hr', referent_schema='identity')


def downgrade() -> None:
    op.drop_index('ix_hr_incident_type', table_name='hr_incident_records', schema='hr')
    op.drop_index('ix_hr_incident_occurred_date', table_name='hr_incident_records', schema='hr')
    op.drop_table('hr_incident_records', schema='hr')
    op.drop_column('positions', 'headcount', schema='hr')
