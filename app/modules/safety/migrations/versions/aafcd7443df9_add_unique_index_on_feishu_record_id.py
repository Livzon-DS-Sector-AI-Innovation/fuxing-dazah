"""Add partial unique index on feishu_record_id to prevent duplicate hazard creation.

当飞书 WebSocket 事件竞态（record_added + record_edited 同时触发）导致
并发 INSERT 时，此索引在数据库层面兜底防止重复记录创建。
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'aafcd7443df9'
down_revision: str | tuple[str, ...] | None = 'd640ce4ef846'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_hazard_reports_feishu_record_id",
        "hazard_reports",
        ["feishu_record_id"],
        unique=True,
        schema="safety",
        postgresql_where="is_deleted = false AND feishu_record_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_hazard_reports_feishu_record_id",
        table_name="hazard_reports",
        schema="safety",
        postgresql_where="is_deleted = false AND feishu_record_id IS NOT NULL",
    )
