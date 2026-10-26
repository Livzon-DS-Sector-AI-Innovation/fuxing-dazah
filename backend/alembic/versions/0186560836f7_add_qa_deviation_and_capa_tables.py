"""add qa deviation and capa tables.

偏差管理（偏差调查 + CAPA）落在既有 ``qa`` schema，与知识库同一约定：
部门、批次等跨模块对象只保留逻辑引用与名称快照，不建业务外键。

Revision ID: 0186560836f7
Revises: c3f2a9d81b47
Create Date: 2026-10-20 15:36:32.303192
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0186560836f7"
down_revision: str | None = "c3f2a9d81b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capa_actions",
        sa.Column("capa_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, comment="措施内容"),
        sa.Column(
            "action_type",
            sa.String(length=16),
            server_default="corrective",
            nullable=False,
        ),
        sa.Column(
            "department_name", sa.String(length=255), nullable=True, comment="责任部门"
        ),
        sa.Column("owner_name", sa.String(length=128), nullable=True, comment="责任人"),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("actual_date", sa.Date(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("note", sa.Text(), nullable=True, comment="完成说明"),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
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
        sa.CheckConstraint(
            "action_type IN ('corrective', 'preventive')",
            name="ck_qa_capa_actions_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'done')",
            name="ck_qa_capa_actions_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="qa",
    )
    op.create_index(
        "ix_qa_capa_actions_capa",
        "capa_actions",
        ["capa_id"],
        unique=False,
        schema="qa",
    )
    op.create_table(
        "capa_status_logs",
        sa.Column("capa_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        sa.Column("operator_name", sa.String(length=128), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="qa",
    )
    op.create_index(
        "ix_qa_capa_status_logs_capa",
        "capa_status_logs",
        ["capa_id", "created_at"],
        unique=False,
        schema="qa",
    )
    op.create_table(
        "capas",
        sa.Column(
            "capa_no",
            sa.String(length=48),
            nullable=False,
            comment="CAPA-{偏差编号}，追加 CAPA 带 -N 后缀",
        ),
        sa.Column("deviation_id", sa.Uuid(), nullable=False, comment="来源偏差"),
        sa.Column(
            "parent_capa_id", sa.Uuid(), nullable=True, comment="追加 CAPA 的上游 CAPA"
        ),
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            comment="事件严重性 minor/major/critical",
        ),
        sa.Column(
            "status", sa.String(length=24), server_default="planned", nullable=False
        ),
        sa.Column("summary", sa.Text(), nullable=False, comment="问题及 CAPA 要求概述"),
        sa.Column(
            "responsible_department_name",
            sa.String(length=255),
            nullable=True,
            comment="责任部门",
        ),
        sa.Column(
            "planned_completion_date", sa.Date(), nullable=True, comment="计划完成日期"
        ),
        sa.Column(
            "effect_method",
            sa.String(length=32),
            nullable=True,
            comment="有效性评估方式",
        ),
        sa.Column(
            "effect_plan", sa.Text(), nullable=True, comment="有效性评估方案说明"
        ),
        sa.Column(
            "effect_due_date",
            sa.Date(),
            nullable=True,
            comment="有效性评估到期日（跟踪周期结束）",
        ),
        sa.Column("effect_result", sa.Text(), nullable=True, comment="回顾评估结果"),
        sa.Column(
            "effect_conclusion",
            sa.String(length=16),
            nullable=True,
            comment="effective/ineffective",
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("in_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluating_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "effect_conclusion IS NULL OR effect_conclusion IN ('effective', 'ineffective')",
            name="ck_qa_capas_effect_conclusion",
        ),
        sa.CheckConstraint(
            "effect_method IS NULL OR effect_method IN ('tracking_week', 'tracking_batches', 'tracking_month', 'custom')",
            name="ck_qa_capas_effect_method",
        ),
        sa.CheckConstraint(
            "severity IN ('minor', 'major', 'critical')", name="ck_qa_capas_severity"
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed', 'effect_evaluating', 'closed')",
            name="ck_qa_capas_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="qa",
    )
    op.create_index(
        "ix_qa_capas_deviation", "capas", ["deviation_id"], unique=False, schema="qa"
    )
    op.create_index(
        "ix_qa_capas_status", "capas", ["status"], unique=False, schema="qa"
    )
    op.create_index(
        "uq_qa_capas_no",
        "capas",
        ["capa_no"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_table(
        "deviation_attachments",
        sa.Column("deviation_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by_name", sa.String(length=128), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="qa",
    )
    op.create_index(
        "ix_qa_deviation_attachments_deviation",
        "deviation_attachments",
        ["deviation_id"],
        unique=False,
        schema="qa",
    )
    op.create_table(
        "deviation_hypothesis_tests",
        sa.Column("deviation_id", sa.Uuid(), nullable=False),
        sa.Column("sample", sa.Text(), nullable=True, comment="需要检验的样品"),
        sa.Column("hypothesis", sa.Text(), nullable=False, comment="假设原因"),
        sa.Column("protocol", sa.Text(), nullable=True, comment="假设方案"),
        sa.Column("expected", sa.Text(), nullable=True, comment="预期的标准/结果"),
        sa.Column("result", sa.Text(), nullable=True, comment="检验结果"),
        sa.Column("conclusion", sa.Text(), nullable=True, comment="数据评价"),
        sa.Column("tested_by", sa.String(length=128), nullable=True),
        sa.Column("tested_at", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="qa",
    )
    op.create_index(
        "ix_qa_deviation_hypothesis_tests_deviation",
        "deviation_hypothesis_tests",
        ["deviation_id"],
        unique=False,
        schema="qa",
    )
    op.create_table(
        "deviation_items",
        sa.Column("deviation_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, comment="对象类别"),
        sa.Column("name", sa.String(length=255), nullable=False, comment="名称"),
        sa.Column(
            "batch_no", sa.String(length=128), nullable=True, comment="批号/编号"
        ),
        sa.Column(
            "handling",
            sa.Text(),
            nullable=True,
            comment="处理意见（复测/放行/不放行等）",
        ),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
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
        sa.CheckConstraint(
            "category IN ('material', 'intermediate', 'finished', 'in_process', 'equipment', 'document', 'other')",
            name="ck_qa_deviation_items_category",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="qa",
    )
    op.create_index(
        "ix_qa_deviation_items_deviation",
        "deviation_items",
        ["deviation_id"],
        unique=False,
        schema="qa",
    )
    op.create_table(
        "deviation_status_logs",
        sa.Column("deviation_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=True),
        sa.Column(
            "action",
            sa.String(length=32),
            nullable=False,
            comment="create/start_investigation/submit_assessment/close/extend",
        ),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        sa.Column("operator_name", sa.String(length=128), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="qa",
    )
    op.create_index(
        "ix_qa_deviation_status_logs_deviation",
        "deviation_status_logs",
        ["deviation_id", "created_at"],
        unique=False,
        schema="qa",
    )
    op.create_table(
        "deviations",
        sa.Column(
            "deviation_no",
            sa.String(length=32),
            nullable=False,
            comment="偏差编号 DE+年月+月流水，如 DE2610001",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="draft",
            nullable=False,
            comment="draft/investigating/assessing/closed",
        ),
        sa.Column(
            "discovery_date",
            sa.Date(),
            nullable=False,
            comment="发现日期（30 天关闭期限的起点）",
        ),
        sa.Column("occurrence_date", sa.Date(), nullable=True, comment="发生日期"),
        sa.Column(
            "due_date",
            sa.Date(),
            nullable=False,
            comment="关闭期限（默认发现日期 + 30 天，可延期）",
        ),
        sa.Column(
            "department_id",
            sa.String(length=128),
            nullable=True,
            comment="发生部门飞书 ID（逻辑引用）",
        ),
        sa.Column(
            "department_name",
            sa.String(length=255),
            nullable=True,
            comment="发生部门名称快照",
        ),
        sa.Column(
            "group_name",
            sa.String(length=128),
            nullable=True,
            comment="组别（如理化组），用于重复偏差识别",
        ),
        sa.Column(
            "reporter_name",
            sa.String(length=128),
            nullable=True,
            comment="发现人/报告人",
        ),
        sa.Column(
            "qa_person_name", sa.String(length=128), nullable=True, comment="质量员"
        ),
        sa.Column("description", sa.Text(), nullable=False, comment="偏差描述（5W1H）"),
        sa.Column(
            "emergency_measures", sa.Text(), nullable=True, comment="应急处理措施"
        ),
        sa.Column("m1e_personnel", sa.Text(), nullable=True, comment="人员调查"),
        sa.Column("m1e_machine", sa.Text(), nullable=True, comment="设备调查"),
        sa.Column("m1e_material", sa.Text(), nullable=True, comment="物料调查"),
        sa.Column("m1e_method", sa.Text(), nullable=True, comment="方法调查"),
        sa.Column("m1e_environment", sa.Text(), nullable=True, comment="环境调查"),
        sa.Column("m1e_other", sa.Text(), nullable=True, comment="其他调查"),
        sa.Column("direct_cause", sa.Text(), nullable=True, comment="直接原因"),
        sa.Column("root_cause", sa.Text(), nullable=True, comment="根本原因"),
        sa.Column(
            "root_cause_category",
            sa.String(length=32),
            nullable=True,
            comment="根本原因分类",
        ),
        sa.Column(
            "why_chain",
            sa.JSON(),
            server_default="[]",
            nullable=False,
            comment="5Why 链 [{question, answer}]",
        ),
        sa.Column(
            "extended_investigation",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="是否需要扩展调查",
        ),
        sa.Column("extended_result", sa.Text(), nullable=True, comment="扩展调查结果"),
        sa.Column(
            "quality_impact",
            sa.String(length=16),
            nullable=True,
            comment="对质量的影响结论 affected/not_affected",
        ),
        sa.Column(
            "quality_impact_reason", sa.Text(), nullable=True, comment="影响结论的理由"
        ),
        sa.Column(
            "classification",
            sa.String(length=16),
            nullable=True,
            comment="偏差分类 minor/moderate/critical",
        ),
        sa.Column(
            "stability_needed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="是否开展稳定性研究",
        ),
        sa.Column("stability_note", sa.Text(), nullable=True),
        sa.Column(
            "validation_impact",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="是否影响验证/协议",
        ),
        sa.Column("validation_note", sa.Text(), nullable=True),
        sa.Column(
            "registration_impact",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="是否影响注册资料",
        ),
        sa.Column("registration_note", sa.Text(), nullable=True),
        sa.Column(
            "notify_customer",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="是否通知客户",
        ),
        sa.Column("customer_note", sa.Text(), nullable=True),
        sa.Column(
            "is_repeat",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="是否重复偏差",
        ),
        sa.Column(
            "repeat_deviation_ids",
            sa.JSON(),
            server_default="[]",
            nullable=False,
            comment="关联的重复偏差 ID 列表",
        ),
        sa.Column(
            "capa_initiated", sa.Boolean(), nullable=True, comment="是否发起 CAPA"
        ),
        sa.Column(
            "capa_not_initiated_reason",
            sa.Text(),
            nullable=True,
            comment="不发起 CAPA 的原因",
        ),
        sa.Column("remark", sa.Text(), nullable=True, comment="其他说明"),
        sa.Column("investigating_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assessing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extension_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="延期次数",
        ),
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
        sa.CheckConstraint(
            "classification IS NULL OR classification IN ('minor', 'moderate', 'critical')",
            name="ck_qa_deviations_classification",
        ),
        sa.CheckConstraint(
            "quality_impact IS NULL OR quality_impact IN ('affected', 'not_affected')",
            name="ck_qa_deviations_quality_impact",
        ),
        sa.CheckConstraint(
            "root_cause_category IS NULL OR root_cause_category IN ('personnel', 'equipment', 'material', 'method', 'environment', 'other')",
            name="ck_qa_deviations_root_cause_category",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'investigating', 'assessing', 'closed')",
            name="ck_qa_deviations_status",
        ),
        sa.CheckConstraint(
            "due_date >= discovery_date", name="ck_qa_deviations_due_date"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["identity.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["identity.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="qa",
    )
    op.create_index(
        "ix_qa_deviations_discovery_date",
        "deviations",
        ["discovery_date"],
        unique=False,
        schema="qa",
    )
    op.create_index(
        "ix_qa_deviations_repeat_key",
        "deviations",
        ["department_name", "group_name", "root_cause_category"],
        unique=False,
        schema="qa",
    )
    op.create_index(
        "ix_qa_deviations_status", "deviations", ["status"], unique=False, schema="qa"
    )
    op.create_index(
        "uq_qa_deviations_no",
        "deviations",
        ["deviation_no"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_qa_deviations_no",
        table_name="deviations",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_index("ix_qa_deviations_status", table_name="deviations", schema="qa")
    op.drop_index("ix_qa_deviations_repeat_key", table_name="deviations", schema="qa")
    op.drop_index(
        "ix_qa_deviations_discovery_date", table_name="deviations", schema="qa"
    )
    op.drop_table("deviations", schema="qa")
    op.drop_index(
        "ix_qa_deviation_status_logs_deviation",
        table_name="deviation_status_logs",
        schema="qa",
    )
    op.drop_table("deviation_status_logs", schema="qa")
    op.drop_index(
        "ix_qa_deviation_items_deviation", table_name="deviation_items", schema="qa"
    )
    op.drop_table("deviation_items", schema="qa")
    op.drop_index(
        "ix_qa_deviation_hypothesis_tests_deviation",
        table_name="deviation_hypothesis_tests",
        schema="qa",
    )
    op.drop_table("deviation_hypothesis_tests", schema="qa")
    op.drop_index(
        "ix_qa_deviation_attachments_deviation",
        table_name="deviation_attachments",
        schema="qa",
    )
    op.drop_table("deviation_attachments", schema="qa")
    op.drop_index(
        "uq_qa_capas_no",
        table_name="capas",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_index("ix_qa_capas_status", table_name="capas", schema="qa")
    op.drop_index("ix_qa_capas_deviation", table_name="capas", schema="qa")
    op.drop_table("capas", schema="qa")
    op.drop_index(
        "ix_qa_capa_status_logs_capa", table_name="capa_status_logs", schema="qa"
    )
    op.drop_table("capa_status_logs", schema="qa")
    op.drop_index("ix_qa_capa_actions_capa", table_name="capa_actions", schema="qa")
    op.drop_table("capa_actions", schema="qa")
