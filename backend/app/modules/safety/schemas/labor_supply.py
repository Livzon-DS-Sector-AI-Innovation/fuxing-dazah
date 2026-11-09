"""labor_supply schemas（劳保用品目录 API 响应模型）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LaborProductAttachment(BaseModel):
    file_token: str
    name: str = ""


class LaborProductItem(BaseModel):
    record_id: str
    name: str
    model: str = ""
    category: str = ""
    protection_type: str = ""
    unit: str = ""
    vendor: str = ""
    lifespan_years: float | None = None
    report_attachments: list[LaborProductAttachment] = Field(default_factory=list)
    manual_attachments: list[LaborProductAttachment] = Field(default_factory=list)


class LaborSupplyStats(BaseModel):
    total: int = 0
    protection_types: dict[str, int] = Field(default_factory=dict)
    vendor_filled: int = 0
    report_filled: int = 0
    manual_filled: int = 0
    lifespan_filled: int = 0
    vendor_coverage: float = 0.0
    report_coverage: float = 0.0
    manual_coverage: float = 0.0
    lifespan_coverage: float = 0.0


class LaborSupplyProductsData(BaseModel):
    """GET /labor-supply/products 响应体（source 三态：bitable/degraded/not_enabled）。"""

    items: list[LaborProductItem] = Field(default_factory=list)
    total: int = 0
    stats: LaborSupplyStats = Field(default_factory=LaborSupplyStats)
    source: str = "bitable"
    meta: dict[str, Any] = Field(default_factory=dict)
