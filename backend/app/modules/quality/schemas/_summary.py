"""Quality 模块请求/响应 Schema。"""


from pydantic import BaseModel

from app.modules.quality.schemas._inspection import InspectionRecordDetail

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
    in_progress: int = 0


class HistorySummaryOut(BaseModel):
    """多批次历史汇总。"""

    total: int
    pass_count: int
    fail_count: int
    pass_rate: float
    in_progress: int = 0
    products: list[ProductSummaryOut]
