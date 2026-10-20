"""安全设备设施管理响应模型（facilities-p1）。

三台账信封字段口径见 facilities/ledger.py 标准字段；任务中心模型在票 03
随 API 一并补齐。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

FacilitiesStatus = Literal["not_connected", "live", "degraded"]


class FacilitiesLedgerMetaOut(BaseModel):
    total: int
    page: int
    page_size: int


class FacilitiesLedgerDataOut(BaseModel):
    data: list[dict[str, Any]]
    meta: FacilitiesLedgerMetaOut


class FacilitiesLedgerPageOut(BaseModel):
    """三台账三态信封：summary=live 态统计组（含信息不全计数）。"""

    status: FacilitiesStatus
    summary: dict[str, Any] | None = None
    ledger: FacilitiesLedgerDataOut
    errors: list[str] = Field(default_factory=list)


class FacilityTaskActionIn(BaseModel):
    """管理员干预入参：cancel 必填原因（min_length 校验），reopen 可选。"""

    reason: str | None = Field(default=None, max_length=500)
