"""safety training_attendees（参训人明细表）

签到表/成绩单 vision 解析名单落库（一人一场一行）：
(training_record_id, person_name) 唯一（软删除外），person_name 索引供
档案页按人查询。培训主事实仍在 Bitable，本表只存个人粒度明细+快照。

Revision ID: c3d5e7f9a1b2
Revises: b6f2d8e4a9c1
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d5e7f9a1b2"
down_revision: str | None = "b6f2d8e4a9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
    ]


def _base_fks() -> list:
    return [
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
    ]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    op.create_table(
        "training_attendees",
        sa.Column(
            "training_record_id",
            sa.String(length=64),
            nullable=False,
            comment="培训行 Bitable record_id",
        ),
        sa.Column("training_name", sa.String(length=255), nullable=True, comment="培训名称快照"),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=True,
            comment="培训类别快照: 入厂三级教育/年度复训/专项培训/转岗培训/外来人员培训",
        ),
        sa.Column("form", sa.String(length=16), nullable=True, comment="培训形式快照: 线下/线上/实操"),
        sa.Column(
            "held_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="实施日期快照（UTC）",
        ),
        sa.Column("hours", sa.Float(), nullable=True, comment="培训学时快照"),
        sa.Column(
            "assessment",
            sa.String(length=32),
            nullable=True,
            comment="考核方式快照: 考试/签到/实操评估/无需考核",
        ),
        sa.Column(
            "training_department",
            sa.String(length=255),
            nullable=True,
            comment="组织部门快照（多选拼接）",
        ),
        sa.Column("person_name", sa.String(length=100), nullable=False, comment="参训人姓名（OCR 转录）"),
        sa.Column(
            "score",
            sa.Float(),
            nullable=True,
            comment="考核成绩（成绩单明细按名匹配；无则 None）",
        ),
        sa.Column("passed", sa.Boolean(), nullable=True, comment="是否合格（成绩单明细；无则 None）"),
        sa.Column(
            "unrecognized",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="姓名辨认不清（原样转录，展示需灰显）",
        ),
        sa.Column("confidence", sa.String(length=16), nullable=True, comment="解析置信度: high/medium/low"),
        sa.Column(
            "source",
            sa.String(length=16),
            server_default="ai_parse",
            nullable=False,
            comment="来源: ai_parse | manual",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_training_attendees_record_person",
        "training_attendees",
        ["training_record_id", "person_name"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_training_attendees_person_name",
        "training_attendees",
        ["person_name"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_training_attendees_person_name",
        table_name="training_attendees",
        schema="safety",
    )
    op.drop_index(
        "uq_training_attendees_record_person",
        table_name="training_attendees",
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("training_attendees", schema="safety")
