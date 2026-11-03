"""superagent 迁移 G —— agent_policies.seq 单调列（现行版本判定确定性缺陷修复）

R1 验收发现：get_current_policy 取 ORDER BY created_at DESC LIMIT 1，同事务/
同秒落多版本时（迁移播种+启动 ensure 同秒属真实触发面）取序不稳定，现行
版本可能读到旧行——ensure_r1_policy 因此间歇性沿用错误 accept_mode。
修复 = 加单调 seq 列，现行 = max(seq)。存量行按 (created_at, id) 回填。

Revision ID: b7c9d1e3f5a2
Revises: a1b3c5d7e9f1
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c9d1e3f5a2"
down_revision: str | None = "a1b3c5d7e9f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "superagent"


def upgrade() -> None:
    op.add_column(
        "agent_policies",
        sa.Column("seq", sa.BigInteger(), nullable=True,
                  comment="单调版本序（现行版本 = max(seq)；插入时 max+1）"),
        schema=_SCHEMA,
    )
    # 存量回填：按落库时间排（同秒并列按 id 定序，仅决定回填值，不影响语义）
    op.execute(
        """
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (
                ORDER BY created_at ASC, id ASC
            ) AS rn
            FROM superagent.agent_policies
        )
        UPDATE superagent.agent_policies AS p
        SET seq = ordered.rn
        FROM ordered
        WHERE p.id = ordered.id
        """
    )
    op.alter_column(
        "agent_policies", "seq", existing_type=sa.BigInteger(),
        nullable=False, schema=_SCHEMA,
    )
    op.create_index(
        "uq_agent_policies_seq", "agent_policies", ["seq"],
        unique=True, schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("uq_agent_policies_seq", table_name="agent_policies",
                  schema=_SCHEMA)
    op.drop_column("agent_policies", "seq", schema=_SCHEMA)
