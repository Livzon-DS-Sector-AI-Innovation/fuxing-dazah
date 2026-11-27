"""五金审批配置迁系统配置 —— 播种八个运行参数键（2026-11-26）

审批配置（通道/定义编码/对账开关/节点 ID/报废与退料分支分流键+控件 JSON）
由 env 迁入 runtime_configs（系统配置运行参数页可改，60s 内热生效；env 降级
为兜底通道）。runtime_registry +8 键后 live 库需有对应行
（test_live_system_config.test_seeded_row_counts_match_registries 断言行数
=注册表长度）。

播种值=注册表默认（未配置态：manual/空串/开关 1）——行存在后 DB 通道生效；
env 里的现值（如 .env.development 的 channel=feishu+定义编码+分支配置）经
registry env_var 兜底继续生效，行为零变化；管理员在系统配置页写入真值即
覆盖 env。int 键必须落真值（coerce 失败回落默认不看 env）。

Revision ID: 68d1846e8145
Revises: e44c4806a50c
Create Date: 2026-11-26 14:48:50.385168
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "68d1846e8145"
down_revision: str | None = "e44c4806a50c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: key → 播种值（=runtime_registry 默认；未配置态）
SEED_VALUES = {
    "hardware_approval_channel": "manual",
    "hardware_approval_code": "",
    "hardware_approval_reconcile_enabled": 1,
    "hardware_approval_node_id": "",
    "hardware_scrap_kind_value": "",
    "hardware_scrap_form_widgets": "",
    "hardware_return_kind_value": "",
    "hardware_return_form_widgets": "",
}


def upgrade() -> None:
    op.execute(
        postgresql.insert(
            sa.table(
                "runtime_configs",
                sa.column("id", postgresql.UUID()),
                sa.column("key", sa.String(64)),
                sa.column("value", postgresql.JSONB()),
                sa.column("is_deleted", sa.Boolean()),
                sa.column("created_at", sa.DateTime()),
                sa.column("updated_at", sa.DateTime()),
                schema="warehouse",
            )
        ).values(
            [
                {
                    "id": uuid.uuid4(),
                    "key": key,
                    "value": value,
                    "is_deleted": False,
                    "created_at": sa.func.now(),
                    "updated_at": sa.func.now(),
                }
                for key, value in SEED_VALUES.items()
            ]
        ).on_conflict_do_nothing()
    )


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in SEED_VALUES)
    op.execute(f"DELETE FROM warehouse.runtime_configs WHERE key IN ({keys})")
