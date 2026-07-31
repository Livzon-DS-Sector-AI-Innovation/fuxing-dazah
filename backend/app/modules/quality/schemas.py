"""Quality 模块请求/响应 Schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ─── 液相解析相关（已有）───


class QualityStandardOut(BaseModel):
    name: str
    limit: float | None = None
    oot_haf: float | None = None
    oot_haa: float | None = None
    operator: str = "≤"


class ImpurityPeakAreaOut(BaseModel):
    name: str
    first: float
    second: float


class ImpurityResultOut(BaseModel):
    name: str
    first_percent: float
    second_percent: float
    limit: float | None = None
    oot_haf: float | None = None
    oot_haa: float | None = None
    is_pass: bool = True
    is_oot: bool = False


class CalculatedResultOut(BaseModel):
    name: str
    first_percent: float
    second_percent: float
    rounded_first: float
    rounded_second: float
    limit: float | None = None
    oot_haf: float | None = None
    oot_haa: float | None = None
    is_pass: bool = True
    is_oot: bool = False


class LcReportOut(BaseModel):
    product_name: str = ""
    batch_number: str = ""
    form_id: str = ""
    standard_type: str = ""
    total_peak_area_a_first: float = 0
    total_peak_area_a_second: float = 0
    main_peak_area_a_first: float = 0
    main_peak_area_a_second: float = 0
    total_impurity_area_first: float = 0
    total_impurity_area_second: float = 0
    any_unknown_impurity_first: float = 0
    any_unknown_impurity_second: float = 0
    main_peak_area_b_first: float = 0
    main_peak_area_b_second: float = 0
    impurity_peaks: list[ImpurityPeakAreaOut] = Field(default_factory=list)
    vancomycin_b: CalculatedResultOut | None = None
    total_impurities: CalculatedResultOut | None = None
    impurity_results: list[ImpurityResultOut] = Field(default_factory=list)
    standards: list[QualityStandardOut] = Field(default_factory=list)
    all_pass: bool = True
    has_oot: bool = False


class UploadLcResponse(BaseModel):
    filename: str
    report: LcReportOut
    record_id: uuid.UUID | None = None  # 持久化后的记录 ID


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
    has_oot: bool
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
    has_oot: bool
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
    oot_haf: float | None = None
    oot_haa: float | None = None
    is_pass: bool = True
    is_oot: bool = False


# ─── 报告单 ───


class GenerateReportRequest(BaseModel):
    """生成报告单请求。"""

    inspection_record_id: uuid.UUID | None = Field(
        default=None, description="关联的检验记录 ID（从数据库加载数据自动填充）"
    )
    template: str = Field(default="万古霉素/3205.docx", description="模板路径")
    data: dict | None = Field(
        default=None, description="手动填写的数据字典（inspection_record_id 为空时使用）"
    )


class ReportRecordOut(BaseModel):
    """报告单记录输出。"""

    id: uuid.UUID
    inspection_record_id: uuid.UUID
    template_path: str
    product_name: str
    batch_number: str
    file_path: str | None = None
    file_size: int | None = None
    created_at: datetime | None = None


# ─── 汇总表 ───


class BatchSummaryOut(BaseModel):
    """单批次汇总。"""

    record: InspectionRecordDetail
    summary_text: str = ""  # 文字化判定摘要


class ProductSummaryOut(BaseModel):
    """按产品汇总统计。"""

    product_name: str
    total: int
    pass_count: int
    fail_count: int
    oot_count: int


class HistorySummaryOut(BaseModel):
    """多批次历史汇总。"""

    total: int
    pass_count: int
    fail_count: int
    oot_count: int
    pass_rate: float
    products: list[ProductSummaryOut]


# ─── 产品标准配置 ───


class ProductStandardCreate(BaseModel):
    """创建产品标准配置。"""

    product_name: str = Field(max_length=200)
    item_name: str = Field(max_length=100)
    standard_type: str | None = Field(default=None, max_length=20)
    operator: str = Field(default="≤", max_length=10)
    limit_value: float | None = None
    oot_haf: float | None = None
    oot_haa: float | None = None


class ProductStandardUpdate(BaseModel):
    """更新产品标准配置。"""

    product_name: str | None = Field(default=None, max_length=200)
    item_name: str | None = Field(default=None, max_length=100)
    standard_type: str | None = Field(default=None, max_length=20)
    operator: str | None = Field(default=None, max_length=10)
    limit_value: float | None = None
    oot_haf: float | None = None
    oot_haa: float | None = None


class ProductStandardOut(BaseModel):
    """产品标准配置输出。"""

    id: uuid.UUID
    product_name: str
    item_name: str
    standard_type: str | None = None
    operator: str = "≤"
    limit_value: float | None = None
    oot_haf: float | None = None
    oot_haa: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
