"""Quality 模块请求/响应 Schema。"""

from pydantic import BaseModel, Field


class QualityStandardOut(BaseModel):
    name: str; limit: float | None = None; oot_haf: float | None = None; oot_haa: float | None = None; operator: str = "≤"


class ImpurityPeakAreaOut(BaseModel):
    name: str; first: float; second: float


class ImpurityResultOut(BaseModel):
    name: str; first_percent: float; second_percent: float; limit: float | None = None
    oot_haf: float | None = None; oot_haa: float | None = None; is_pass: bool = True; is_oot: bool = False


class CalculatedResultOut(BaseModel):
    name: str; first_percent: float; second_percent: float; rounded_first: float; rounded_second: float
    limit: float | None = None; oot_haf: float | None = None; oot_haa: float | None = None
    is_pass: bool = True; is_oot: bool = False


class LcReportOut(BaseModel):
    product_name: str = ""; batch_number: str = ""; form_id: str = ""; standard_type: str = ""
    total_peak_area_a_first: float = 0; total_peak_area_a_second: float = 0
    main_peak_area_a_first: float = 0; main_peak_area_a_second: float = 0
    total_impurity_area_first: float = 0; total_impurity_area_second: float = 0
    any_unknown_impurity_first: float = 0; any_unknown_impurity_second: float = 0
    main_peak_area_b_first: float = 0; main_peak_area_b_second: float = 0
    impurity_peaks: list[ImpurityPeakAreaOut] = Field(default_factory=list)
    vancomycin_b: CalculatedResultOut | None = None; total_impurities: CalculatedResultOut | None = None
    impurity_results: list[ImpurityResultOut] = Field(default_factory=list)
    standards: list[QualityStandardOut] = Field(default_factory=list)
    all_pass: bool = True; has_oot: bool = False


class UploadLcResponse(BaseModel):
    filename: str; report: LcReportOut
