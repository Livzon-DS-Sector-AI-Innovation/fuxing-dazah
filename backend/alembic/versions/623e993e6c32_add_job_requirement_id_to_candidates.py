"""add job_requirement_id to candidates

Revision ID: 623e993e6c32
Revises: 44c51f83fb13
Create Date: 2026-07-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '623e993e6c32'
down_revision: Union[str, None] = '44c51f83fb13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('job_requirement_id', sa.Uuid(), nullable=True, comment='关联岗位需求'), schema='hr')


def downgrade() -> None:
    op.drop_column('candidates', 'job_requirement_id', schema='hr')
