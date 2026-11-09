"""Safety request and response schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.modules.safety.schemas.enums import (
    HazardCategory,
    HazardLevel,
    HazardType,
)
from app.modules.safety.service.hazard_direct.field_authority import (
    normalize_level_manual,
)


def _normalize_hazard_level_manual(v: str | None) -> str | None:
    """人工等级写入归一（存储侧收口，T01/D2）。

    中文/英文/多选拼接串（直读历史「较大隐患, 一般隐患」）→ EN 单值、
    多值取最高严重度；未知值原样透传（历史行为，不静默丢弃）。
    CN↔EN 映射唯一事实源见 field_authority.HAZARD_LEVEL_MAP。
    """
    if isinstance(v, str):
        return normalize_level_manual(v) or (v.strip() or None)
    return v


class HazardStatsResponse(BaseModel):
    """隐患统计（全局，不受分页/筛选影响）"""

    total: int = 0
    pending_review: int = 0
    pending: int = 0
    in_progress: int = 0
    replied: int = 0
    verifying: int = 0
    rejected: int = 0
    closed: int = 0
    overdue: int = 0


class HazardReportBase(BaseModel):
    """隐患报告基础模式"""

    hazard_no: str = Field(..., max_length=64, description="隐患编号")
    inspection_category: str | None = Field(None, max_length=64, description="检查类别（日常检查/专项检查…）")
    # 直读模式 AI 分类列可能为空（待轮询回写），响应允许 None；镜像恒有值
    hazard_type: HazardType | None = Field(None, description="隐患分类（人/物/环/管）")
    hazard_level: HazardLevel | None = Field(
        None, description="隐患等级（AI）；直读模式 AI 列未回写时为空，展示以人工等级优先"
    )
    hazard_level_manual: str | None = Field(None, description="隐患等级（人工，督办判定以此为准；写入时中文自动归一为英文枚举）")
    hazard_category: HazardCategory | None = Field(None, description="隐患类别（设备设施/危化储存…）")
    description: str = Field(..., description="隐患描述")
    discovered_by: uuid.UUID | None = Field(None, description="发现人")
    discovered_by_name: str | None = Field(None, max_length=100, description="检查人员姓名")
    inspector_department: str | None = Field(None, max_length=500, description="检查人员部门（Bitable 多选，逗号分隔）")
    discovered_at: datetime | None = Field(None, description="检查日期")
    department: str | None = Field(None, max_length=100, description="责任部门")
    major_hazard_basis: str | None = Field(None, description="隐患判定依据（AI）")
    key_defect: str | None = Field(None, description="隐患描述（AI）")
    defect_photos: str | None = Field(None, description="缺陷图片JSON数组")
    rectification_responsible_person: uuid.UUID | None = Field(None, description="整改责任人（FK → identity.users）")
    rectification_responsible_person_name: str | None = Field(None, max_length=100, description="整改责任人姓名")
    corrective_preventive_measures: str | None = Field(None, description="AI整改建议")
    rectification_reply: str | None = Field(None, description="整改回复内容")
    deadline: datetime | None = Field(None, description="整改期限")
    actual_completion_date: datetime | None = Field(None, description="整改完成时间")
    rectification_photos: str | None = Field(None, description="整改后图片JSON数组")
    notes: str | None = Field(None, description="备注")
    progress_note: str | None = Field(None, description="目前进展（Bitable「目前进展」字段单向同步）")
    # ── ⑤ AI 评分（2026-11-05；直读模式透传，镜像模式恒 None）──
    score: float | None = Field(None, description="AI评分 D=L×E×C×X（制度 §10.3，1 位小数）")
    score_note: str | None = Field(None, description="评分说明（band｜四维=D｜评语｜依据[｜重大判定][｜⚠]）")

    _norm_level_manual = field_validator("hazard_level_manual", mode="before")(
        _normalize_hazard_level_manual
    )


class HazardReportCreate(HazardReportBase):
    """创建隐患报告"""

    hazard_no: str | None = Field(None, max_length=64, description="隐患编号（留空自动生成）")
    hazard_type: HazardType | None = Field(None, description="隐患分类")
    hazard_level: HazardLevel | None = Field(None, description="隐患等级")
    hazard_level_manual: str | None = Field(None, description="隐患等级（人工）")
    hazard_category: HazardCategory | None = Field(None, description="隐患类别")
    description: str | None = Field(None, description="隐患描述")
    discovered_at: datetime | None = Field(None, description="发现时间")


class HazardReportUpdate(BaseModel):
    """更新隐患报告"""

    hazard_no: str | None = Field(None, max_length=64, description="隐患编号")
    inspection_category: str | None = Field(None, max_length=64, description="检查类别（日常检查/专项检查…）")
    hazard_type: HazardType | None = Field(None, description="隐患分类")
    hazard_level: HazardLevel | None = Field(None, description="隐患等级（AI）")
    hazard_level_manual: str | None = Field(None, description="隐患等级（人工）")
    hazard_category: HazardCategory | None = Field(None, description="隐患类别")
    description: str | None = Field(None, description="隐患描述")
    discovered_by: uuid.UUID | None = Field(None, description="发现人（FK → identity.users）")
    discovered_by_name: str | None = Field(None, max_length=100, description="检查人员姓名")
    discovered_at: datetime | None = Field(None, description="检查日期")
    department: str | None = Field(None, max_length=100, description="责任部门")
    inspector_department: str | None = Field(None, max_length=500, description="检查人员部门（Bitable 多选，逗号分隔）")
    major_hazard_basis: str | None = Field(None, description="隐患判定依据（AI）")
    key_defect: str | None = Field(None, description="隐患描述（AI）")
    defect_photos: str | None = Field(None, description="缺陷图片JSON数组")
    rectification_responsible_person: uuid.UUID | None = Field(None, description="整改责任人（FK → identity.users）")
    rectification_responsible_person_name: str | None = Field(None, max_length=100, description="整改责任人姓名")
    corrective_preventive_measures: str | None = Field(None, description="AI整改建议")
    rectification_reply: str | None = Field(None, description="整改回复内容")
    deadline: datetime | None = Field(None, description="整改期限")
    actual_completion_date: datetime | None = Field(None, description="整改完成时间")
    rectification_photos: str | None = Field(None, description="整改后图片JSON数组")
    rectification_status: str | None = Field(None, max_length=32, description="整改进度")
    status: str | None = Field(None, max_length=32, description="状态")
    notes: str | None = Field(None, description="备注")
    progress_note: str | None = Field(None, description="目前进展（Bitable「目前进展」字段单向同步）")

    _norm_level_manual = field_validator("hazard_level_manual", mode="before")(
        _normalize_hazard_level_manual
    )
    # ── AI 流程字段 ──
    ai_node_progress: str | None = Field(None, max_length=50, description="AI流程节点进度")
    overall_status: str | None = Field(None, max_length=20, description="整体状态")
    ai_error_message: str | None = Field(None, description="AI错误信息")
    script1_review_status: str | None = Field(None, max_length=20, description="AI隐患识别审核状态")
    script2_review_status: str | None = Field(None, max_length=20, description="AI整改建议审核状态")


class HazardReportResponse(HazardReportBase):
    """隐患报告响应"""

    # 直读模式 id 为飞书记录 ID（recXXX）；created_at/updated_at 恒 None
    # （Bitable 无平台创建/更新时间）。镜像模式为正常 UUID/时间戳。
    id: uuid.UUID | str
    rectification_status: str
    status: str
    # ── 三级复核（仅状态，审核人/时间由系统自动记录）──
    verify_level_1_status: str = "pending"
    verify_level_2_status: str = "pending"
    verify_level_3_status: str = "pending"
    # ── AI 流程字段 ──
    ai_node_progress: str = "pending_input"
    overall_status: str = "draft"
    ai_error_message: str | None = None
    script1_review_status: str = "pending"
    script2_review_status: str = "pending"
    # ── AI 整改初审 ──
    ai_review_result: dict[str, Any] | None = None
    ai_review_status: str = "pending"
    ai_review_completed_at: datetime | None = None
    ai_generated: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # ── 飞书通知追踪 ──
    rectification_notified_at: datetime | None = None
    rectification_notify_status: str | None = None
    rectification_notify_error: str | None = None
    review_notified_at: datetime | None = None
    review_notified_level: int | None = None
    review_notify_status: str | None = None
    review_notify_error: str | None = None
    # ── 督办等级 ──
    supervision_level: str | None = None
    # ── 督办进展监控（系统回写，用户不可写）──
    supervision_progress_status: str | None = None
    progress_note_updated_at: datetime | None = None
    # ── 字段口径治理（P0-B）：人工优先 + AI fallback 的统一读口径 ──
    # 直读模式：人工列非空取人工，否则 fallback AI 列并标注 source；mirror 模式恒 None。
    # mismatch=True 仅人工与 AI 双方均有值且不相等（前端据此展示「AI建议」差异提示）。
    effective_level: HazardLevel | None = Field(
        None, description="隐患等级（人工优先；AI 为空时回退 AI）"
    )
    effective_level_source: str | None = Field(
        None, description="effective_level 来源：human / ai / null"
    )
    effective_level_mismatch: bool | None = Field(
        None, description="人工与 AI 等级是否不一致（双方均有值且不等）"
    )
    effective_type: HazardType | None = Field(
        None, description="隐患分类（人工优先；AI 为空时回退 AI）"
    )
    effective_type_source: str | None = Field(None, description="human / ai / null")
    effective_type_mismatch: bool | None = Field(
        None, description="人工与 AI 分类是否不一致"
    )
    effective_category: HazardCategory | None = Field(
        None, description="隐患类别（人工优先；AI 为空时回退 AI）"
    )
    effective_category_source: str | None = Field(None, description="human / ai / null")
    effective_category_mismatch: bool | None = Field(
        None, description="人工与 AI 类别是否不一致"
    )
    # ── 人工原文（D3 差异可视化：Drawer 对照展示）──
    hazard_type_manual: str | None = Field(
        None, description="隐患分类（人工原文，Bitable 原值）"
    )
    hazard_category_manual: str | None = Field(
        None, description="隐患类别（人工原文，Bitable 原值）"
    )
    # ── AI vs 人工差异结构（P1-2/D3）：三维 {manual_raw, ai_raw, effective, source, mismatch} ──
    # 权威口径=effective_*；本结构仅供详情对照展示（附「以人工为准」标注），不进筛选/统计。
    ai_vs_manual: dict[str, Any] | None = Field(
        None,
        description=(
            "等级/分类/类别三维 AI vs 人工差异："
            "{level|type|category: {manual_raw, ai_raw, effective, source, mismatch}}"
        ),
    )

    class Config:
        from_attributes = True

