"""AI 调用审计 API 契约。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

PREVIEW_CHARS = 200


class AICallAuditListItem(BaseModel):
    """列表项（input/output 仅前 200 字预览）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    trace_id: str | None = None
    scenario: str
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    session_id: str | None = None
    channel: str | None = None
    user_name: str | None = None
    model: str
    prompt_version: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None
    latency_ms: int | None = None
    status: str
    degradation_level: str | None = None


class AICallAuditDetail(AICallAuditListItem):
    """详情（含全文与依据）。"""

    input_text: str | None = None
    input_truncated: bool = False
    output_text: str | None = None
    output_truncated: bool = False
    ip_address: str | None = None
    error: str | None = None
    cited_sources: list | None = None
    guard_hits: list | None = None
    extra: dict | None = None
