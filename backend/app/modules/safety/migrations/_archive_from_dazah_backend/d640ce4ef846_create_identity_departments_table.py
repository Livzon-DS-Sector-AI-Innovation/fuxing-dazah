"""create identity.departments table

Revision ID: d640ce4ef846
Revises: 9a75c1875018
Create Date: 2026-06-18 16:50:53.881605
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd640ce4ef846'
down_revision: Union[str, None] = '9a75c1875018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── identity.departments ──
    # 使用 IF NOT EXISTS 避免表已存在时报错（多人协作/手动建表场景）
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")
    op.execute("""
        CREATE TABLE IF NOT EXISTS identity.departments (
            feishu_department_id VARCHAR(64) NOT NULL,
            name VARCHAR(200) NOT NULL,
            parent_feishu_department_id VARCHAR(64),
            leader_user_id VARCHAR(128),
            member_count INTEGER,
            status_is_deleted BOOLEAN,
            path TEXT,
            "order" INTEGER,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            created_by UUID,
            updated_by UUID,
            is_deleted BOOLEAN DEFAULT false NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY (created_by) REFERENCES identity.users (id),
            FOREIGN KEY (updated_by) REFERENCES identity.users (id),
            UNIQUE (feishu_department_id),
            CONSTRAINT uq_identity_departments_feishu_id UNIQUE (feishu_department_id)
        )
    """)


def downgrade() -> None:
    op.drop_table('departments', schema='identity')
