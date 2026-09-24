"""quality add specification to test tasks

Revision ID: 27375e84e8c7
Revises: f907f4abda67
Create Date: 2026-09-09 11:17:39.330174
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27375e84e8c7'
down_revision: Union[str, None] = 'f907f4abda67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.add_column('quality_test_tasks',
                  sa.Column('specification', sa.String(length=100), nullable=True,
                            comment='本批规格（从标准文档规格中选定，如 5kg/听）'),
                  schema='quality')


def downgrade() -> None:
    op.drop_column('quality_test_tasks', 'specification', schema='quality')
