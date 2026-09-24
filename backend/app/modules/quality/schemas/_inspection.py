"""Quality 模块请求/响应 Schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.quality.schemas._lc import LcReportOut

# ─── 检验记录查询 ───


class InspectionQueryParams(BaseModel):
    """检验记录分页查询参数。"""

    product_name: str | None = Field(default=None, description="产品名称（模糊搜索）")
    batch_number: str | None = Field(default=None, description="批号（模糊搜索）")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class InspectionRecordListItem(BaseModel):
    """检验记录列表项。"""

    id: uuid.UUID
    product_name: str
    batch_number: str
    form_id: str | None = None
    standard_type: str | None = None
    all_pass: bool
    excel_filename: str | None = None
    created_at: datetime | None = None


class InspectionRecordDetail(BaseModel):
    """检验记录详情（含完整解析结果和杂质明细）。"""

    id: uuid.UUID
    product_name: str
    batch_number: str
    form_id: str | None = None
    standard_type: str | None = None
    all_pass: bool
    excel_filename: str | None = None
    created_at: datetime | None = None
    report: LcReportOut
    impurities: list["ImpurityDetailOut"] = Field(default_factory=list)


class ImpurityDetailOut(BaseModel):
    """杂质明细输出。"""

    id: uuid.UUID
    name: str
    first_percent: float | None = None
    second_percent: float | None = None
    limit_value: float | None = None
    is_pass: bool = True
