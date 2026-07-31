"""ensure heads and auto_notify_enabled on meter.departments

Revision ID: 0416a0f10a33
Revises: 393e668958f2
Create Date: 2026-07-31 09:57:56.131058

补救迁移：7419e6f7039e 在多分支合并时被 Alembic 跳过，导致服务器数据库缺少这两列。
此迁移用 DO 块检查列是否存在，仅对缺失的列执行 ADD COLUMN，本地和服务器均可安全执行。
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0416a0f10a33'
down_revision: str | None = '393e668958f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'meter'
                  AND table_name   = 'departments'
                  AND column_name  = 'heads'
            ) THEN
                ALTER TABLE meter.departments
                    ADD COLUMN heads JSONB DEFAULT '[]'::jsonb;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'meter'
                  AND table_name   = 'departments'
                  AND column_name  = 'auto_notify_enabled'
            ) THEN
                ALTER TABLE meter.departments
                    ADD COLUMN auto_notify_enabled BOOLEAN DEFAULT false;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    """不下掉列——这是补救缺失迁移，downgrade 不应破坏数据。"""
    pass
