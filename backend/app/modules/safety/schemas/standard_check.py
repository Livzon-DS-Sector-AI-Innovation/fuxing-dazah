"""体系标准核查响应模型（S1 目标责任与绩效，2026-10-21 改造）。

信封口径与 domain_pages 三态一致；summary/groups 行字段事实源是
service/standard_check（DESIGN-…体系标准符合性核查引擎-20261021.md §5）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

StandardCheckStatus = Literal["not_connected", "live", "degraded"]


class StandardSummaryOut(BaseModel):
    total: int
    ok: int
    in_progress: int
    missed: int
    no_data: int
    compliance_rate: int | None = Field(
        default=None, description="综合符合率=达标/(达标+未达标)；无判定项为 null"
    )


class StandardGroupOut(BaseModel):
    element: str
    rows: list[dict[str, Any]]


class StandardDeptSummaryOut(BaseModel):
    name: str
    total: int
    ok: int
    in_progress: int
    missed: int
    no_data: int


class StandardCheckPageOut(BaseModel):
    status: StandardCheckStatus
    summary: StandardSummaryOut | None = None
    groups: list[StandardGroupOut] = Field(default_factory=list)
    departments: list[StandardDeptSummaryOut] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class StandardEvidenceItemOut(BaseModel):
    title: str
    date: str = ""
    type: str = ""
    url: str | None = None


class StandardEvidenceOut(BaseModel):
    status: Literal["live", "not_connected", "degraded", "not_found"]
    record_id: str | None = None
    no: str | None = None
    clause: str | None = None
    metric_key: str | None = None
    window: dict[str, str] | None = None
    verdict_status: str | None = None
    actual_display: str | None = None
    evidence: list[StandardEvidenceItemOut] = Field(default_factory=list)
    no_data_reason: str | None = None
