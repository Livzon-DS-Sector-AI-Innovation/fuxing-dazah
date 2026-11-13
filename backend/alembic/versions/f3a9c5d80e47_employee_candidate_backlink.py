"""add employee.candidate_id backlink

Revision ID: f3a9c5d80e47
Revises: d8f4b2c61e90
Create Date: 2026-11-13 12:00:00.000000

员工档案加来源候选人回链：onboard 一键入职时写入，历史员工为空。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a9c5d80e47'
down_revision: Union[str, None] = '45192a298e4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'employees',
        sa.Column('candidate_id', sa.Uuid(), nullable=True,
                  comment='来源候选人（招聘入职回链）'),
        schema='hr',
    )
    op.create_index(
        'ix_employees_candidate_id', 'employees', ['candidate_id'], schema='hr',
    )
    op.create_foreign_key(
        'fk_employees_candidate', 'employees', 'candidates',
        ['candidate_id'], ['id'], source_schema='hr', referent_schema='hr',
    )


def downgrade() -> None:
    op.drop_constraint('fk_employees_candidate', 'employees', schema='hr', type_='foreignkey')
    op.drop_index('ix_employees_candidate_id', table_name='employees', schema='hr')
    op.drop_column('employees', 'candidate_id', schema='hr')
