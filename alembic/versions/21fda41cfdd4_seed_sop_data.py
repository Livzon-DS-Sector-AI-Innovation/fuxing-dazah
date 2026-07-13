"""seed SOP catalog and position trainings data

Revision ID: 21fda41cfdd4
Revises: 20fda41cfdd3
Create Date: 2026-07-13 20:40:00.000000
"""
from typing import Sequence, Union
from alembic import op
from pathlib import Path

revision: str = '21fda41cfdd4'
down_revision: Union[str, None] = '20fda41cfdd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    seed_file = Path(__file__).parent.parent.parent / "scripts" / "seed_sop_data.sql"
    if seed_file.exists():
        with open(seed_file) as f:
            sql = f.read()
        for stmt in sql.split(';\n'):
            stmt = stmt.strip()
            if stmt and not stmt.startswith('--'):
                try:
                    op.execute(stmt)
                except Exception:
                    pass  # 已存在的跳过


def downgrade() -> None:
    pass
