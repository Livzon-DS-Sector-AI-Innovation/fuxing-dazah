"""五金库紧急领用补办跟进 —— 催办标签列 + 逾期通报幂等锚 + 推送任务行

制度 5.3.4 先发后补（2026-11-19 拍板）：紧急单发料后 T-12h/T-2h 催办申请人
（patch_reminders 记已发标签防重发）；逾期未补办每日一次通报仓管通知目标
（last_overdue_notified_at 跨日才重发）。并播种 hardware_urgent_overdue
推送任务行（渲染器已在 push_center/events.py 注册，此前 registry 无任务行
事件投不出去）。

Revision ID: i4d6f8a0c2e5
Revises: h8c1f3a5d9e2
Create Date: 2026-11-19
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "i4d6f8a0c2e5"
down_revision: str | None = "h8c1f3a5d9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"

NEW_PUSH_TASKS = ("hardware_urgent_overdue",)


def upgrade() -> None:
    op.add_column(
        "hardware_requisitions",
        sa.Column(
            "patch_reminders",
            postgresql.JSONB(),
            nullable=True,
            comment="补办催办已发标签（t12/t2，幂等锚）",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "hardware_requisitions",
        sa.Column(
            "last_overdue_notified_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="逾期通报最近一次时间（每日一次幂等锚）",
        ),
        schema=SCHEMA,
    )
    # 推送任务播种（registry 单一事实源 → DB 行；ON CONFLICT 幂等）
    from app.modules.warehouse.push_center import registry as push_registry

    now = datetime.now(UTC)
    task_rows = sa.table(
        "push_tasks",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("task_name", sa.String(64)),
        sa.column("enabled", sa.Boolean()),
        sa.column("schedule", postgresql.JSONB()),
        sa.column("targets", sa.String(512)),
        sa.column("is_deleted", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    seed_rows = [
        {
            "id": uuid4(),
            "task_name": info.task_name,
            "enabled": True,
            "schedule": info.default_schedule,
            "targets": None,
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }
        for info in push_registry.iter_tasks()
        if info.task_name in NEW_PUSH_TASKS
    ]
    # registry 已退役该任务（o3a5c7e9b1d3 起 hardware_urgent_overdue 下线）时
    # 取到空列表，直接跳过——否则 postgresql.insert([]) 会退化成
    # `INSERT ... DEFAULT VALUES`，撞 task_name NOT NULL 约束。
    if seed_rows:
        op.execute(
            postgresql.insert(task_rows).values(seed_rows).on_conflict_do_nothing()
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM warehouse.push_tasks WHERE task_name IN "
            "('hardware_urgent_overdue')"
        )
    )
    op.drop_column("hardware_requisitions", "last_overdue_notified_at", schema=SCHEMA)
    op.drop_column("hardware_requisitions", "patch_reminders", schema=SCHEMA)
