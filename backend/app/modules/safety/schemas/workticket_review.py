"""作业票审核 Schema — 手动触发请求 / 审核结果响应."""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from pydantic import BaseModel, Field


class WorkTicketReviewRunRequest(BaseModel):
    """手动触发作业票审核请求。"""

    date: date_type | None = Field(default=None, description="审核日期，默认今天（Asia/Shanghai）")
    push: bool = Field(default=False, description="是否推送飞书群卡片，默认 False")


class WorkTicketReviewViolationDetail(BaseModel):
    """逐票违规/数据不足明细项。"""

    ticket_no: str
    ticket_type: str
    ticket_type_name: str
    rule_no: str
    rule_name: str
    detail: str


class WorkTicketReviewParseError(BaseModel):
    """单票解析失败记录。"""

    type: str
    serialNumber: str = Field(default="")  # noqa: N815
    error: str


class WorkTicketReviewRunResponse(BaseModel):
    """作业票审核结果响应（覆盖 run_review 返回结果字段）。"""

    date: str
    total: int
    reviewed: int
    violation_count: int
    compliant_count: int
    data_insufficient: int
    status: str
    markdown_report: str
    push_result: dict[str, Any] = Field(default_factory=dict)
    message_id: str | None = None
    violation_details: list[WorkTicketReviewViolationDetail] = Field(default_factory=list)
    data_insufficient_details: list[WorkTicketReviewViolationDetail] = Field(default_factory=list)
    parse_errors: list[WorkTicketReviewParseError] = Field(default_factory=list)
