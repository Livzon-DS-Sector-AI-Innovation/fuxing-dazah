"""Quality 模块请求/响应 Schema。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


class TestTaskReviewRequest(BaseModel):
    """复核通过请求（双人复核：两名不同复核人通过后任务完成）。"""

    comment: str | None = Field(default=None, max_length=300, description="复核备注")


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
