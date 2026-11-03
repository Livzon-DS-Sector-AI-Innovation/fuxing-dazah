"""QA 偏差管理（偏差 + CAPA）请求/响应模型。"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.qa.models import (
    CapaActionStatus,
    CapaActionType,
    CapaSeverity,
    DeviationClassification,
    DeviationItemCategory,
    EffectConclusion,
    EffectMethod,
    QualityImpact,
    RootCauseCategory,
)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


class WhyStep(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(default="", max_length=4000)

    @field_validator("question")
    @classmethod
    def _trim_question(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("问题不能为空")
        return text


class DeviationItemIn(BaseModel):
    category: DeviationItemCategory
    name: str = Field(min_length=1, max_length=255)
    batch_no: str | None = Field(default=None, max_length=128)
    handling: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("名称不能为空")
        return text

    @field_validator("batch_no", "handling")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class HypothesisTestIn(BaseModel):
    sample: str | None = Field(default=None, max_length=4000)
    hypothesis: str = Field(min_length=1, max_length=4000)
    protocol: str | None = Field(default=None, max_length=4000)
    expected: str | None = Field(default=None, max_length=4000)
    result: str | None = Field(default=None, max_length=4000)
    conclusion: str | None = Field(default=None, max_length=4000)
    tested_by: str | None = Field(default=None, max_length=128)
    tested_at: date | None = None

    @field_validator("hypothesis")
    @classmethod
    def _trim_hypothesis(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("假设原因不能为空")
        return text

    @field_validator(
        "sample", "protocol", "expected", "result", "conclusion", "tested_by"
    )
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class DeviationCreate(BaseModel):
    """QA 登记偏差（偏差报告表第一部分）。"""

    discovery_date: date
    occurrence_date: date | None = None
    due_date: date | None = Field(default=None, description="默认发现日期 + 30 天")
    department_id: str | None = Field(default=None, max_length=128)
    department_name: str | None = Field(default=None, max_length=255)
    group_name: str | None = Field(default=None, max_length=128)
    reporter_name: str | None = Field(default=None, max_length=128)
    qa_person_name: str | None = Field(default=None, max_length=128)
    description: str = Field(min_length=1, max_length=20000)
    emergency_measures: str | None = Field(default=None, max_length=8000)
    remark: str | None = Field(default=None, max_length=8000)
    items: list[DeviationItemIn] = Field(default_factory=list, max_length=200)

    @field_validator("description")
    @classmethod
    def _trim_description(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("偏差描述不能为空")
        return text

    @field_validator(
        "department_id",
        "department_name",
        "group_name",
        "reporter_name",
        "qa_person_name",
        "emergency_measures",
        "remark",
    )
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class DeviationUpdate(BaseModel):
    """按阶段编辑偏差；未传字段不改，列表字段传空数组即清空。"""

    # ── 报告 ──
    discovery_date: date | None = None
    occurrence_date: date | None = None
    department_id: str | None = Field(default=None, max_length=128)
    department_name: str | None = Field(default=None, max_length=255)
    group_name: str | None = Field(default=None, max_length=128)
    reporter_name: str | None = Field(default=None, max_length=128)
    qa_person_name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, min_length=1, max_length=20000)
    emergency_measures: str | None = Field(default=None, max_length=8000)
    remark: str | None = Field(default=None, max_length=8000)
    items: list[DeviationItemIn] | None = Field(default=None, max_length=200)
    # ── 调查 ──
    m1e_personnel: str | None = Field(default=None, max_length=8000)
    m1e_machine: str | None = Field(default=None, max_length=8000)
    m1e_material: str | None = Field(default=None, max_length=8000)
    m1e_method: str | None = Field(default=None, max_length=8000)
    m1e_environment: str | None = Field(default=None, max_length=8000)
    m1e_other: str | None = Field(default=None, max_length=8000)
    direct_cause: str | None = Field(default=None, max_length=8000)
    root_cause: str | None = Field(default=None, max_length=8000)
    root_cause_category: RootCauseCategory | None = None
    why_chain: list[WhyStep] | None = Field(default=None, max_length=20)
    extended_investigation: bool | None = None
    extended_result: str | None = Field(default=None, max_length=8000)
    hypothesis_tests: list[HypothesisTestIn] | None = Field(default=None, max_length=50)
    # ── 评估 ──
    quality_impact: QualityImpact | None = None
    quality_impact_reason: str | None = Field(default=None, max_length=8000)
    classification: DeviationClassification | None = None
    stability_needed: bool | None = None
    stability_note: str | None = Field(default=None, max_length=4000)
    validation_impact: bool | None = None
    validation_note: str | None = Field(default=None, max_length=4000)
    registration_impact: bool | None = None
    registration_note: str | None = Field(default=None, max_length=4000)
    notify_customer: bool | None = None
    customer_note: str | None = Field(default=None, max_length=4000)
    is_repeat: bool | None = None
    repeat_deviation_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    capa_initiated: bool | None = None
    capa_not_initiated_reason: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "discovery_date",
        "is_repeat",
        "extended_investigation",
        "stability_needed",
        "validation_impact",
        "registration_impact",
        "notify_customer",
    )
    @classmethod
    def _reject_null(cls, value: object) -> object:
        # Optional 用于表达“未传”，但这些列不允许清空；显式 null 直接 422。
        if value is None:
            raise ValueError("该字段不能为空")
        return value

    @field_validator(
        "department_id",
        "department_name",
        "group_name",
        "reporter_name",
        "qa_person_name",
        "description",
        "emergency_measures",
        "remark",
        "m1e_personnel",
        "m1e_machine",
        "m1e_material",
        "m1e_method",
        "m1e_environment",
        "m1e_other",
        "direct_cause",
        "root_cause",
        "extended_result",
        "quality_impact_reason",
        "stability_note",
        "validation_note",
        "registration_note",
        "customer_note",
        "capa_not_initiated_reason",
    )
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


# ───────────────────────── AI 辅助 ─────────────────────────


DeviationAiAssistKind = Literal["describe", "m1e", "why", "hypothesis"]


class DeviationAiAssistIn(BaseModel):
    """偏差 AI 辅助请求：携带当前表单快照换取建议，服务端不落库。

    登记辅助发生在创建前（偏差尚无 id），调查辅助也要能看到未保存的
    草稿内容，因此无状态地由前端传上下文；``deviation_id`` 仅用于审计
    归属，可选。
    """

    kind: DeviationAiAssistKind
    deviation_id: uuid.UUID | None = None
    description: str = Field(min_length=10, max_length=20000)
    department_name: str | None = Field(default=None, max_length=255)
    group_name: str | None = Field(default=None, max_length=128)
    reporter_name: str | None = Field(default=None, max_length=128)
    emergency_measures: str | None = Field(default=None, max_length=8000)
    items: list[DeviationItemIn] = Field(default_factory=list, max_length=50)
    m1e_personnel: str | None = Field(default=None, max_length=8000)
    m1e_machine: str | None = Field(default=None, max_length=8000)
    m1e_material: str | None = Field(default=None, max_length=8000)
    m1e_method: str | None = Field(default=None, max_length=8000)
    m1e_environment: str | None = Field(default=None, max_length=8000)
    m1e_other: str | None = Field(default=None, max_length=8000)
    direct_cause: str | None = Field(default=None, max_length=8000)
    root_cause: str | None = Field(default=None, max_length=8000)
    why_chain: list[WhyStep] = Field(default_factory=list, max_length=20)
    hypothesis_tests: list[HypothesisTestIn] = Field(default_factory=list, max_length=50)

    @field_validator("description")
    @classmethod
    def _trim_description(cls, value: str) -> str:
        # 过短的描述没有可规范化的信息量，直接挡在 422。
        text = value.strip()
        if len(text) < 10:
            raise ValueError("偏差描述过短，无法进行 AI 辅助")
        return text

    @field_validator(
        "department_name",
        "group_name",
        "reporter_name",
        "emergency_measures",
        "m1e_personnel",
        "m1e_machine",
        "m1e_material",
        "m1e_method",
        "m1e_environment",
        "m1e_other",
        "direct_cause",
        "root_cause",
    )
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


DeviationTransitionAction = Literal["start_investigation", "submit_assessment", "close"]


class DeviationTransitionIn(BaseModel):
    action: DeviationTransitionAction
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def _trim_comment(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class DeviationExtendIn(BaseModel):
    new_due_date: date
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("延期原因不能为空")
        return text


# ───────────────────────── CAPA ─────────────────────────


class CapaActionIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    action_type: CapaActionType = CapaActionType.CORRECTIVE
    department_name: str | None = Field(default=None, max_length=255)
    owner_name: str | None = Field(default=None, max_length=128)
    planned_date: date | None = None
    actual_date: date | None = None
    status: CapaActionStatus = CapaActionStatus.PENDING
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("content")
    @classmethod
    def _trim_content(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("措施内容不能为空")
        return text

    @field_validator("department_name", "owner_name", "note")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class CapaCreate(BaseModel):
    deviation_id: uuid.UUID
    parent_capa_id: uuid.UUID | None = None
    severity: CapaSeverity
    summary: str = Field(min_length=1, max_length=20000)
    responsible_department_name: str | None = Field(default=None, max_length=255)
    planned_completion_date: date | None = None
    effect_method: EffectMethod | None = None
    effect_plan: str | None = Field(default=None, max_length=4000)
    effect_due_date: date | None = None
    remark: str | None = Field(default=None, max_length=4000)
    actions: list[CapaActionIn] = Field(default_factory=list, max_length=50)

    @field_validator("summary")
    @classmethod
    def _trim_summary(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("问题及 CAPA 要求概述不能为空")
        return text

    @field_validator("responsible_department_name", "effect_plan", "remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class CapaUpdate(BaseModel):
    severity: CapaSeverity | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=20000)
    responsible_department_name: str | None = Field(default=None, max_length=255)
    planned_completion_date: date | None = None
    effect_method: EffectMethod | None = None
    effect_plan: str | None = Field(default=None, max_length=4000)
    effect_due_date: date | None = None
    effect_result: str | None = Field(default=None, max_length=8000)
    effect_conclusion: EffectConclusion | None = None
    remark: str | None = Field(default=None, max_length=4000)
    actions: list[CapaActionIn] | None = Field(default=None, max_length=50)

    @field_validator("severity")
    @classmethod
    def _reject_null(cls, value: object) -> object:
        # severity 是 NOT NULL 列，Optional 只表示“未传”。
        if value is None:
            raise ValueError("该字段不能为空")
        return value

    @field_validator("summary")
    @classmethod
    def _trim_summary(cls, value: str | None) -> str:
        # summary 是 NOT NULL 列；空白字符串必须先拒绝，不能 trim 成 None。
        text = (value or "").strip()
        if not text:
            raise ValueError("问题及 CAPA 要求概述不能为空")
        return text

    @field_validator(
        "responsible_department_name",
        "effect_plan",
        "effect_result",
        "remark",
    )
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class CapaActionPatch(BaseModel):
    """单条措施的进度更新。"""

    status: CapaActionStatus | None = None
    actual_date: date | None = None
    note: str | None = Field(default=None, max_length=4000)
    owner_name: str | None = Field(default=None, max_length=128)
    planned_date: date | None = None

    @field_validator("status")
    @classmethod
    def _reject_null(cls, value: object) -> object:
        # status 是 NOT NULL 列，Optional 只表示“未传”。
        if value is None:
            raise ValueError("该字段不能为空")
        return value

    @field_validator("note", "owner_name")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


CapaTransitionAction = Literal["start", "complete", "start_evaluation", "close"]


class CapaTransitionIn(BaseModel):
    action: CapaTransitionAction
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def _trim_comment(cls, value: str | None) -> str | None:
        return _strip_optional(value)
