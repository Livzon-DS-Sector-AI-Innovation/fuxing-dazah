"""Quality 模块请求/响应 Schema。"""

import uuid
from typing import Any

from pydantic import BaseModel, Field

# ─── 液相解析相关（已有）───


class QualityStandardOut(BaseModel):
    name: str
    limit: float | None = None
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
    is_pass: bool = True


class CalculatedResultOut(BaseModel):
    name: str
    first_percent: float
    second_percent: float
    rounded_first: float
    rounded_second: float
    limit: float | None = None
    is_pass: bool = True


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


class UploadLcResponse(BaseModel):
    filename: str
    report: LcReportOut
    record_id: uuid.UUID | None = None  # 持久化后的记录 ID
    task_link: dict[str, Any] | None = None  # 自动关联的检验任务信息：{task_id, filled, unmatched}
    components: list[dict[str, Any]] | None = None  # 模板配置通用解析的组分结果（旧解析器为 None）
