"""应急演练管理 — Pydantic 请求/响应 Schema。

三环节：计划 → 实施 → 复核。Bitable 单表镜像。
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

# ── 枚举 ──

DRILL_TYPE_OPTIONS = [
    {"value": "应急疏散演练", "label": "应急疏散演练"},
    {"value": "现场岗位处置", "label": "现场岗位处置"},
    {"value": "专项应急演练", "label": "专项应急演练"},
    {"value": "综合应急演练", "label": "综合应急演练"},
    {"value": "消防器材培训", "label": "消防器材培训"},
]

STATUS_OPTIONS = [
    {"value": "已完成", "label": "已完成"},
    {"value": "未完成", "label": "未完成"},
]

# ── 响应 ──


class DrillRecordResponse(BaseModel):
    """演练记录响应 — 映射 Bitable 单行数据。"""

    id: uuid.UUID
    feishu_record_id: str | None = None

    # 计划阶段
    plan_time: str | None = None
    plan_time_ref: date | None = None
    drill_type: str | None = None
    drill_content: str | None = None
    organizer: str | None = None
    department: str | None = None
    organizer_person: str | None = None
    participants: str | None = None
    coop_department: str | None = None
    duration: str | None = None
    notes: str | None = None
    alert_person: str | None = None
    alert_person_data: dict | None = None

    # 实施阶段
    execution_time: date | None = None
    drill_plan_file: list | None = None
    signin_file: list | None = None
    eval_form_file: list | None = None
    drill_record_file: list | None = None

    # 复核阶段
    issues: str | None = None
    rectification_person: str | None = None
    rectification_person_data: dict | None = None
    confirmer: str | None = None
    confirmer_data: dict | None = None
    status: str | None = None

    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class DrillDocumentResponse(BaseModel):
    """AI 演练方案文档。"""

    id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    doc_type: str
    title: str
    content: str | None = None
    content_json: dict | None = None
    generation_params: dict | None = None
    cited_regulations: list | None = None
    ai_model: str | None = None
    ai_tokens_used: int | None = None
    version: int = 1
    doc_status: str = "draft"
    feishu_doc_id: str | None = None
    feishu_doc_url: str | None = None
    feishu_doc_status: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class DrillStatsResponse(BaseModel):
    """演练统计仪表盘。"""

    total: int = 0
    executed: int = 0
    completed: int = 0
    pending: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_department: dict[str, int] = Field(default_factory=dict)


# ── 收录表 ──


class CollectionRecordResponse(BaseModel):
    """演练计划收录记录响应。"""

    id: uuid.UUID
    feishu_record_id: str | None = None
    upload_date: date | None = None
    attachment: list | None = None
    person_data: dict | None = None
    department: str | None = None
    parse_status: str = "pending"
    parse_result: dict | None = None
    stats_record_id: str | None = None
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
