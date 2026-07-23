"""add location assessment_method notes to annual plan items

Revision ID: 99581c9282e4
Revises: b76027d40f85
Create Date: 2026-07-23 00:07:37.966325
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '99581c9282e4'
down_revision: Union[str, None] = 'b76027d40f85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('annual_training_plan_items', sa.Column('location', sa.String(128), nullable=True, comment='培训地点'), schema='hr')
    op.add_column('annual_training_plan_items', sa.Column('assessment_method', sa.String(64), nullable=True, comment='考核方式'), schema='hr')
    op.add_column('annual_training_plan_items', sa.Column('notes', sa.String(512), nullable=True, comment='注意事项'), schema='hr')


def downgrade() -> None:
    op.drop_column('annual_training_plan_items', 'notes', schema='hr')
    op.drop_column('annual_training_plan_items', 'assessment_method', schema='hr')
    op.drop_column('annual_training_plan_items', 'location', schema='hr')
