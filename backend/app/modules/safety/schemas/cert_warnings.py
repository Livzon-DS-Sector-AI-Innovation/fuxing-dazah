"""持证到期预警 Schema — Pydantic v2。

对齐 backend-design.md §3 与 spec.md。只做请求/响应模型与 Enum + OPTIONS，
不 import ORM model（CLAUDE.md schema 隔离要求）。预警等级由 CertWarningEngine
派生后注入 CertWarningDetail，ORM 无对应列。
"""
from __future__ import annotations

import uuid
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CertCategory(str, Enum):  # noqa: UP042
    """证件类别：特种作业证 / 监护人 A 证 / 监护人 B 证。"""  # noqa: UP042

    SPECIAL_OP = "special_op"     # 特种作业证
    GUARDIAN_A = "guardian_a"     # 监护人 A 证
    GUARDIAN_B = "guardian_b"     # 监护人 B 证


CERT_CATEGORY_OPTIONS = [
    {"value": CertCategory.SPECIAL_OP, "label": "特种作业证", "color": "blue"},
    {"value": CertCategory.GUARDIAN_A, "label": "监护人A证", "color": "green"},
    {"value": CertCategory.GUARDIAN_B, "label": "监护人B证", "color": "purple"},
]


class WarningLevel(str, Enum):  # noqa: UP042
    """预警等级（6 档，>90 / 61-90 / 31-60 / 8-30 / 0-7 / <0）。"""  # noqa: UP042

    NORMAL = "normal"              # >90 正常（暂不提醒）
    EARLY_NOTICE = "early_notice"  # 61-90 提前关注
    TO_SCHEDULE = "to_schedule"    # 31-60 待安排
    KEY_WARNING = "key_warning"    # 8-30 重点预警
    URGENT = "urgent"              # 0-7 紧急预警
    OVERDUE = "overdue"            # <0 已逾期


WARNING_LEVEL_OPTIONS = [
    {"value": WarningLevel.NORMAL,       "label": "正常",     "color": "default"},
    {"value": WarningLevel.EARLY_NOTICE, "label": "提前关注", "color": "blue"},
    {"value": WarningLevel.TO_SCHEDULE,  "label": "待安排",   "color": "gold"},
    {"value": WarningLevel.KEY_WARNING,  "label": "重点预警", "color": "orange"},
    {"value": WarningLevel.URGENT,       "label": "紧急预警", "color": "red"},
    {"value": WarningLevel.OVERDUE,      "label": "已逾期",   "color": "red"},
]


class CertWarningQuery(BaseModel):
    """GET /cert-warnings 查询参数（Query 形式，见 backend-design.md §6.1）。"""

    model_config = ConfigDict(use_enum_values=True)

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)
    status_level: WarningLevel | None = Field(None, description="预警状态筛选（6 档）")
    department: str | None = Field(None, description="部门")
    cert_category: CertCategory | None = Field(None, description="证件类别")
    days_within: int | None = Field(None, ge=0, description="剩余天数 ≤ N 筛选")


class CertWarningDetail(BaseModel):
    """单条到期明细响应（含引擎派生字段）。"""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: uuid.UUID
    cert_category: CertCategory
    person_name: str
    department: str | None = None
    employee_no: str | None = None
    phone: str | None = None
    operation_type: str | None = None
    project: str | None = None
    certificate_no: str | None = None
    issue_date: date | None = None
    next_review_date: date | None = None
    review_frequency: str | None = None
    first_review_deadline: date | None = None
    second_review_deadline: date | None = None
    should_renew_date: date | None = None
    renewed_date: date | None = None
    certificate_file_path: str | None = None
    notes: str | None = None
    # —— 引擎派生字段（不在 ORM，由 CertWarningEngine 计算后注入）——
    current_node: str | None = Field(None, description="当前节点描述（如'复审/2026-09-01'）")
    deadline: date | None = Field(None, description="当前节点截止日期")
    remaining_days: int | None = Field(None, description="剩余天数（负=已逾期）")
    status_level: WarningLevel = Field(WarningLevel.NORMAL)
    suggestion: str | None = Field(None, description="建议措施")


class CertWarningSummary(BaseModel):
    """GET /cert-warnings/summary 汇总响应。"""

    model_config = ConfigDict(use_enum_values=True)

    # 6 档人数
    overdue_count: int = 0
    urgent_count: int = 0       # 0-7
    key_warning_count: int = 0  # 8-30
    to_schedule_count: int = 0   # 31-60
    early_notice_count: int = 0  # 61-90
    normal_count: int = 0        # >90
    total: int = 0
    # 涉及事项统计（spec US-1 顶部汇总）
    by_category: dict[str, int] = Field(
        default_factory=dict, description="按 cert_category 计数"
    )
    by_event: dict[str, int] = Field(
        default_factory=dict,
        description="按当前事项计数（special_op_review / guardian_a_first_review / ...）",
    )


class RenewRequest(BaseModel):
    """POST /cert-warnings/{id}/renew 回填请求。"""

    model_config = ConfigDict(use_enum_values=True)

    renewed_date: date | None = Field(
        None, description="监护人证已换证日期（回填后进入下一周期）"
    )
    next_review_date: date | None = Field(
        None, description="特种作业证再复审时间（回填后重算剩余天数）"
    )
    notes: str | None = Field(None, description="备注（可选）")
    # 校验：renewed_date 与 next_review_date 二选一（Service 层 enforce）


# 供前端 OPTIONS 统一导出（与模块其他 OPTIONS 命名一致）
__all__: list[str] = [
    "CERT_CATEGORY_OPTIONS",
    "WARNING_LEVEL_OPTIONS",
    "CertCategory",
    "CertWarningDetail",
    "CertWarningQuery",
    "CertWarningSummary",
    "RenewRequest",
    "WarningLevel",
]
