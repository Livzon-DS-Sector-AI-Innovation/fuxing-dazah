"""QA 偏差管理（偏差调查 + CAPA）ORM 模型。

沿用 QA 知识库的约定：部门、批次、设备等跨模块对象只保存逻辑引用和
名称快照，不声明业务外键；偏差与 CAPA 同在 ``qa`` schema，用 UUID 列
逻辑关联。流转历史独立成表，供详情页时间线和追溯使用。
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class DeviationStatus(enum.StrEnum):
    """偏差流转状态：登记 → 调查 → 评估 → 关闭。"""

    DRAFT = "draft"
    INVESTIGATING = "investigating"
    ASSESSING = "assessing"
    CLOSED = "closed"


class DeviationClassification(enum.StrEnum):
    """偏差分类：微小 / 中等 / 关键。"""

    MINOR = "minor"
    MODERATE = "moderate"
    CRITICAL = "critical"


class RootCauseCategory(enum.StrEnum):
    """根本原因分类（人员/设备仪器/物料/方法程序/环境/其他）。"""

    PERSONNEL = "personnel"
    EQUIPMENT = "equipment"
    MATERIAL = "material"
    METHOD = "method"
    ENVIRONMENT = "environment"
    OTHER = "other"


class QualityImpact(enum.StrEnum):
    AFFECTED = "affected"
    NOT_AFFECTED = "not_affected"


class DeviationItemCategory(enum.StrEnum):
    """涉及对象类别：物料/中间体/成品/中控/设备/文件/其他。"""

    MATERIAL = "material"
    INTERMEDIATE = "intermediate"
    FINISHED = "finished"
    IN_PROCESS = "in_process"
    EQUIPMENT = "equipment"
    DOCUMENT = "document"
    OTHER = "other"


class CapaStatus(enum.StrEnum):
    """CAPA 流转状态：已发起 → 实施中 → 措施完成 → 有效性评估中 → 关闭。"""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EFFECT_EVALUATING = "effect_evaluating"
    CLOSED = "closed"


class CapaSeverity(enum.StrEnum):
    """相关事件严重性评级：次要 / 重要 / 关键。"""

    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class CapaActionType(enum.StrEnum):
    CORRECTIVE = "corrective"
    PREVENTIVE = "preventive"


class CapaActionStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class EffectMethod(enum.StrEnum):
    """有效性评估方式：连续跟踪 1 周 / 至少 3 批 / 1 个月 / 自定义。"""

    TRACKING_WEEK = "tracking_week"
    TRACKING_BATCHES = "tracking_batches"
    TRACKING_MONTH = "tracking_month"
    CUSTOM = "custom"


class EffectConclusion(enum.StrEnum):
    EFFECTIVE = "effective"
    INEFFECTIVE = "ineffective"


def _enum_sql_list(values: type[enum.StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in values)


class Deviation(BaseModel):
    """偏差主记录：偏差报告表的四个部分落在同一行，按状态分阶段填写。"""

    __tablename__ = "deviations"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_enum_sql_list(DeviationStatus)})",
            name="ck_qa_deviations_status",
        ),
        CheckConstraint(
            "classification IS NULL OR classification IN "
            f"({_enum_sql_list(DeviationClassification)})",
            name="ck_qa_deviations_classification",
        ),
        CheckConstraint(
            "root_cause_category IS NULL OR root_cause_category IN "
            f"({_enum_sql_list(RootCauseCategory)})",
            name="ck_qa_deviations_root_cause_category",
        ),
        CheckConstraint(
            "quality_impact IS NULL OR quality_impact IN "
            f"({_enum_sql_list(QualityImpact)})",
            name="ck_qa_deviations_quality_impact",
        ),
        CheckConstraint("due_date >= discovery_date", name="ck_qa_deviations_due_date"),
        Index(
            "uq_qa_deviations_no",
            "deviation_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_deviations_status", "status"),
        Index("ix_qa_deviations_discovery_date", "discovery_date"),
        # 重复偏差识别：同部门同组别同根因分类在 3 个月内再发。
        Index(
            "ix_qa_deviations_repeat_key",
            "department_name",
            "group_name",
            "root_cause_category",
        ),
        {"schema": "qa"},
    )

    deviation_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="偏差编号 DE+年月+月流水，如 DE2610001"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DeviationStatus.DRAFT.value,
        server_default=DeviationStatus.DRAFT.value,
        comment="draft/investigating/assessing/closed",
    )

    # ── 第一部分：偏差报告 ──
    discovery_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="发现日期（30 天关闭期限的起点）"
    )
    occurrence_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="发生日期"
    )
    due_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="关闭期限（默认发现日期 + 30 天，可延期）"
    )
    department_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="发生部门飞书 ID（逻辑引用）"
    )
    department_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="发生部门名称快照"
    )
    group_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="组别（如理化组），用于重复偏差识别"
    )
    reporter_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="发现人/报告人"
    )
    qa_person_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="质量员"
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, comment="偏差描述（5W1H）"
    )
    emergency_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急处理措施"
    )

    # ── 第二部分：偏差调查 ──
    m1e_personnel: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="人员调查"
    )
    m1e_machine: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="设备调查"
    )
    m1e_material: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="物料调查"
    )
    m1e_method: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="方法调查"
    )
    m1e_environment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="环境调查"
    )
    m1e_other: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="其他调查"
    )
    direct_cause: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="直接原因"
    )
    root_cause: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="根本原因"
    )
    root_cause_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="根本原因分类"
    )
    why_chain: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="'[]'::jsonb",
        comment="5Why 链 [{question, answer}]",
    )
    extended_investigation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否需要扩展调查",
    )
    extended_result: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="扩展调查结果"
    )

    # ── 第三部分：偏差评估 ──
    quality_impact: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="对质量的影响结论 affected/not_affected"
    )
    quality_impact_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="影响结论的理由"
    )
    classification: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="偏差分类 minor/moderate/critical"
    )
    stability_needed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否开展稳定性研究",
    )
    stability_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_impact: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否影响验证/协议",
    )
    validation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_impact: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否影响注册资料",
    )
    registration_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notify_customer: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否通知客户",
    )
    customer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_repeat: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否重复偏差",
    )
    repeat_deviation_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="'[]'::jsonb",
        comment="关联的重复偏差 ID 列表",
    )
    # None 表示尚未决定；False 时必须填写不发起原因。
    capa_initiated: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="是否发起 CAPA"
    )
    capa_not_initiated_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="不发起 CAPA 的原因"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="其他说明")

    # ── 节点时间戳 ──
    investigating_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assessing_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extension_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="延期次数"
    )


class DeviationItem(BaseModel):
    """偏差涉及的物料/产品/设备/文件明细及处理意见。"""

    __tablename__ = "deviation_items"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({_enum_sql_list(DeviationItemCategory)})",
            name="ck_qa_deviation_items_category",
        ),
        Index("ix_qa_deviation_items_deviation", "deviation_id"),
        {"schema": "qa"},
    )

    deviation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="对象类别"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="名称")
    batch_no: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="批号/编号"
    )
    handling: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="处理意见（复测/放行/不放行等）"
    )
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )


class DeviationHypothesisTest(BaseModel):
    """假设性检验记录：查不出根因时用实验证实或排除假设。"""

    __tablename__ = "deviation_hypothesis_tests"
    __table_args__ = (
        Index("ix_qa_deviation_hypothesis_tests_deviation", "deviation_id"),
        {"schema": "qa"},
    )

    deviation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sample: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="需要检验的样品"
    )
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False, comment="假设原因")
    protocol: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="假设方案"
    )
    expected: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="预期的标准/结果"
    )
    result: Mapped[str | None] = mapped_column(Text, nullable=True, comment="检验结果")
    conclusion: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="数据评价"
    )
    tested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tested_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )


class DeviationStatusLog(BaseModel):
    """偏差流转日志：状态变更、延期、编辑等动作的时间线。"""

    __tablename__ = "deviation_status_logs"
    __table_args__ = (
        Index("ix_qa_deviation_status_logs_deviation", "deviation_id", "created_at"),
        {"schema": "qa"},
    )

    deviation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="create/start_investigation/submit_assessment/close/extend",
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    operator_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class DeviationAttachment(BaseModel):
    """偏差附件（批记录复印件、校验标签照片、COA 等）。"""

    __tablename__ = "deviation_attachments"
    __table_args__ = (
        Index("ix_qa_deviation_attachments_deviation", "deviation_id"),
        {"schema": "qa"},
    )

    deviation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Capa(BaseModel):
    """纠正与预防措施主记录。"""

    __tablename__ = "capas"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_enum_sql_list(CapaStatus)})",
            name="ck_qa_capas_status",
        ),
        CheckConstraint(
            f"severity IN ({_enum_sql_list(CapaSeverity)})",
            name="ck_qa_capas_severity",
        ),
        CheckConstraint(
            "effect_method IS NULL OR effect_method IN "
            f"({_enum_sql_list(EffectMethod)})",
            name="ck_qa_capas_effect_method",
        ),
        CheckConstraint(
            "effect_conclusion IS NULL OR effect_conclusion IN "
            f"({_enum_sql_list(EffectConclusion)})",
            name="ck_qa_capas_effect_conclusion",
        ),
        Index(
            "uq_qa_capas_no",
            "capa_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_capas_deviation", "deviation_id"),
        Index("ix_qa_capas_status", "status"),
        {"schema": "qa"},
    )

    capa_no: Mapped[str] = mapped_column(
        String(48), nullable=False, comment="CAPA-{偏差编号}，追加 CAPA 带 -N 后缀"
    )
    deviation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="来源偏差"
    )
    parent_capa_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="追加 CAPA 的上游 CAPA"
    )
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="事件严重性 minor/major/critical"
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=CapaStatus.PLANNED.value,
        server_default=CapaStatus.PLANNED.value,
    )
    summary: Mapped[str] = mapped_column(
        Text, nullable=False, comment="问题及 CAPA 要求概述"
    )
    responsible_department_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="责任部门"
    )
    planned_completion_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="计划完成日期"
    )
    effect_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="有效性评估方式"
    )
    effect_plan: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="有效性评估方案说明"
    )
    effect_due_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="有效性评估到期日（跟踪周期结束）"
    )
    effect_result: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="回顾评估结果"
    )
    effect_conclusion: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="effective/ineffective"
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    in_progress_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evaluating_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CapaAction(BaseModel):
    """CAPA 措施明细。"""

    __tablename__ = "capa_actions"
    __table_args__ = (
        CheckConstraint(
            f"action_type IN ({_enum_sql_list(CapaActionType)})",
            name="ck_qa_capa_actions_type",
        ),
        CheckConstraint(
            f"status IN ({_enum_sql_list(CapaActionStatus)})",
            name="ck_qa_capa_actions_status",
        ),
        Index("ix_qa_capa_actions_capa", "capa_id"),
        {"schema": "qa"},
    )

    capa_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="措施内容")
    action_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CapaActionType.CORRECTIVE.value,
        server_default=CapaActionType.CORRECTIVE.value,
    )
    department_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="责任部门"
    )
    owner_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="责任人"
    )
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CapaActionStatus.PENDING.value,
        server_default=CapaActionStatus.PENDING.value,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="完成说明")
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )


class CapaStatusLog(BaseModel):
    """CAPA 流转日志。"""

    __tablename__ = "capa_status_logs"
    __table_args__ = (
        Index("ix_qa_capa_status_logs_capa", "capa_id", "created_at"),
        {"schema": "qa"},
    )

    capa_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    operator_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "Capa",
    "CapaAction",
    "CapaActionStatus",
    "CapaActionType",
    "CapaSeverity",
    "CapaStatus",
    "CapaStatusLog",
    "Deviation",
    "DeviationAttachment",
    "DeviationClassification",
    "DeviationHypothesisTest",
    "DeviationItem",
    "DeviationItemCategory",
    "DeviationStatus",
    "DeviationStatusLog",
    "EffectConclusion",
    "EffectMethod",
    "QualityImpact",
    "RootCauseCategory",
]
