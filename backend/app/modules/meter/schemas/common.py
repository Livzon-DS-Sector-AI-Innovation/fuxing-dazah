"""Meter schema 公共类型与批量请求契约。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field

StrUUID = Annotated[str, BeforeValidator(str)]


def _validate_uuid_str(value: object) -> str:
    """请求体中的 ID 字符串必须是合法 UUID，否则由 Pydantic 返回 422。"""
    text = str(value)
    UUID(text)
    return text


UUIDStr = Annotated[str, BeforeValidator(_validate_uuid_str)]


def _normalize_department(value: str | None) -> str | None:
    """去除部门字段前后空白字符。"""
    if value is None:
        return None
    return value.strip()


# 响应 schema 中 department 字段统一使用此类型，自动去除前导数字

NormalizedDepartment = Annotated[str | None, BeforeValidator(_normalize_department)]


# ═══════════════════════════════════════════
# 通用
# ═══════════════════════════════════════════





class BatchDeleteRequest(BaseModel):
    """批量删除请求。"""
    ids: list[UUIDStr] = Field(default_factory=list, min_length=1, description="仪表 ID 列表")





class ExportReportRequest(BaseModel):
    """批量导出报告请求。"""
    ids: list[UUIDStr] = Field(default_factory=list, max_length=200, description="仪表 ID 列表")


# ═══════════════════════════════════════════
# 批量上传 + 文件匹配
# ═══════════════════════════════════════════
