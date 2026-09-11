"""Quality 模块请求/响应 Schema。"""

import uuid
from datetime import datetime
from typing import Literal

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
    task_link: dict | None = None  # 自动关联的检验任务信息：{task_id, filled, unmatched}
    components: list[dict] | None = None  # 模板配置通用解析的组分结果（旧解析器为 None）


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


class HistorySummaryOut(BaseModel):
    """多批次历史汇总。"""

    total: int
    pass_count: int
    fail_count: int
    pass_rate: float
    products: list[ProductSummaryOut]


# ─── 产品标准配置 ───


class StandardDocumentCreate(BaseModel):
    """创建质量标准文档。"""

    file_no: str = Field(max_length=100)
    product_name: str = Field(max_length=200)
    product_code: str | None = Field(default=None, max_length=64)
    product_internal_code: str | None = Field(default=None, max_length=64)
    specification: str | None = Field(default=None, max_length=200)
    valid_years: str | None = Field(default=None, max_length=32)
    effective_date: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)
    template_path: str | None = Field(default=None, max_length=500, description="绑定的 COA 报告模板路径")


class StandardDocumentUpdate(BaseModel):
    """更新质量标准文档。"""

    file_no: str | None = Field(default=None, max_length=100)
    product_name: str | None = Field(default=None, max_length=200)
    product_code: str | None = Field(default=None, max_length=64)
    product_internal_code: str | None = Field(default=None, max_length=64)
    specification: str | None = Field(default=None, max_length=200)
    valid_years: str | None = Field(default=None, max_length=32)
    effective_date: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)
    template_path: str | None = Field(default=None, max_length=500, description="绑定的 COA 报告模板路径")


class StandardItemCreate(BaseModel):
    """创建标准项目行（SOP 号为匹配键；含纯文字标准，文字标准 operator/limit 为空、人工判定）。"""

    seq: int | None = None
    category: str | None = Field(default=None, max_length=100)
    item_name: str = Field(max_length=200)
    sop_no: str = Field(max_length=64)
    standard_text: str = Field(max_length=300)
    operator: str | None = Field(default=None, max_length=10)
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=200)


class StandardItemUpdate(BaseModel):
    """更新标准项目行。"""

    seq: int | None = None
    category: str | None = Field(default=None, max_length=100)
    item_name: str | None = Field(default=None, max_length=200)
    sop_no: str | None = Field(default=None, max_length=64)
    standard_text: str | None = Field(default=None, max_length=300)
    operator: str | None = Field(default=None, max_length=10)
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=200)


# ─── 标准文档导入（预览确认流程）───


class StandardImportDocument(BaseModel):
    """导入草稿的文档头（可修改后确认）。"""

    file_no: str = Field(max_length=100)
    product_name: str = Field(max_length=200)
    product_code: str | None = Field(default=None, max_length=64)
    product_internal_code: str | None = Field(default=None, max_length=64)
    specification: str | None = Field(default=None, max_length=200)
    valid_years: str | None = Field(default=None, max_length=32)
    effective_date: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)


class StandardImportItem(BaseModel):
    """导入草稿的项目行（可修改后确认）。"""

    seq: int | None = None
    category: str | None = Field(default=None, max_length=100)
    item_name: str = Field(max_length=200)
    sop_no: str | None = Field(default=None, max_length=64)
    standard_text: str | None = Field(default=None, max_length=300)
    operator: str | None = Field(default=None, max_length=10)
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=200)


class StandardImportConfirm(BaseModel):
    """确认导入：携带人工校正后的文档头与项目行。"""

    document: StandardImportDocument
    items: list[StandardImportItem] = Field(min_length=0, max_length=500)


# ─── 检验任务填报 ───


class TestTaskCreate(BaseModel):
    """创建检验任务（从标准库快照项目行；可指定只快照选中的项目）。

    链路规则：选产品 → 填批号（开头必然含产品代号，如 HAF2608001B → HAF）
    → 按代号收敛到该代号的标准文档并选 SOP；批号未匹配代号时创建失败。
    """

    product_name: str = Field(max_length=200)
    batch_number: str = Field(max_length=100, description="批号（开头必须含该产品的产品代号，用于收敛标准文档）")
    production_date: str | None = Field(default=None, max_length=32, description="生产日期 YYYY-MM-DD")
    expiry_date: str | None = Field(default=None, max_length=32, description="效期（生产日期+x年-1天，缺省按产品标准有效期自动计算）")
    specification: str | None = Field(default=None, max_length=100, description="本批规格（从标准文档规格中选定）")
    form_id: str | None = Field(default=None, max_length=100, description="COA 表格编号")
    report_date: str | None = Field(
        default=None, max_length=32, description="出报日期 YYYY-MM-DD（可选，后续可补录；关联当日机器人任务推送）"
    )
    standard_document_id: uuid.UUID | None = Field(
        default=None, description="指定快照标准文档（单份，兼容旧调用）"
    )
    standard_document_ids: list[uuid.UUID] | None = Field(
        default=None, description="指定快照标准文件列表（一个批号可开多份报告单，标准文件可多选）；缺省按批号代号收敛全部"
    )
    standard_item_ids: list[uuid.UUID] | None = Field(
        default=None, description="仅快照选中的标准行；缺省快照该产品全部项目行"
    )


class TestTaskStatusUpdate(BaseModel):
    """任务状态流转。

    in_progress 填报中 / pending_review 待复核 / completed 已完成 / void 已作废。
    """

    status: Literal["in_progress", "pending_review", "completed", "void"]


class TestTaskReportDateUpdate(BaseModel):
    """补录/修改出报日期（传 null 清空）。"""

    report_date: str | None = Field(
        default=None, max_length=32, description="出报日期 YYYY-MM-DD；null 清空"
    )


class TestResultFill(BaseModel):
    """单行填报。auto 行以 result_value 自动判定（is_pass 忽略）；manual 行必须传 is_pass。"""

    result_id: uuid.UUID
    result_text: str | None = Field(default=None, max_length=300)
    result_value: float | None = None
    is_pass: bool | None = None


class TestResultsUpdate(BaseModel):
    """批量填报（部分行更新即可）。"""

    results: list[TestResultFill] = Field(min_length=1, max_length=500)


class TestResultCreate(BaseModel):
    """追加临时结果行（judge_mode 由后端按 operator/limit 推断）。"""

    item_name: str = Field(max_length=200)
    category: str | None = Field(default=None, max_length=100)
    sop_no: str | None = Field(default=None, max_length=64)
    standard_text: str | None = Field(default=None, max_length=300)
    operator: str | None = Field(default=None, max_length=10)
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=200)


class TestResultOut(BaseModel):
    """结果行出参。"""

    id: uuid.UUID
    seq: int | None = None
    category: str | None = None
    item_name: str
    sop_no: str | None = None
    standard_text: str | None = None
    operator: str | None = None
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = None
    remark: str | None = None
    result_text: str | None = None
    result_value: float | None = None
    is_pass: bool | None = None
    judge_mode: str
    source: str
    filled_at: datetime | None = None


class TestTaskListItem(BaseModel):
    """任务列表项（含进度统计）。"""

    id: uuid.UUID
    product_name: str
    batch_number: str
    production_date: str | None = None
    expiry_date: str | None = None
    specification: str | None = None
    form_id: str | None = None
    report_date: str | None = None
    status: str
    created_at: datetime | None = None
    results_total: int = 0
    results_filled: int = 0


class TestTaskDetail(BaseModel):
    """任务详情（含结果行）。"""

    id: uuid.UUID
    product_name: str
    batch_number: str
    production_date: str | None = None
    expiry_date: str | None = None
    specification: str | None = None
    form_id: str | None = None
    report_date: str | None = None
    standard_document_id: uuid.UUID | None = None
    status: str
    created_at: datetime | None = None
    results: list[TestResultOut] = Field(default_factory=list)


class TaskReportGenerateRequest(BaseModel):
    """从已完成任务生成 COA 报告单。"""

    template: str = Field(default="", description="模板路径；为空时取该产品标准文档绑定的模板")


