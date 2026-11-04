"""直读视图 dataclass——Base 中文列 → 展示字段（与镜像序列化键对齐）。

id 统一为飞书记录 ID（rec…）；直读行不落库，仅进程内缓存只读共享。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class MaterialView:
    """material_master 一行。"""

    record_id: str
    code: str
    name: str
    category_cn: str            # 物料大类原文（原辅料/危化品/包材…）
    spec: str = ""

    @property
    def category(self) -> str:
        """本地 category CHECK 枚举（与回灌映射一致）。"""
        return CATEGORY_MAP.get(self.category_cn, "raw")


@dataclass(frozen=True)
class StockView:
    """material_stock 一行（对账口径键 代码+物料批号）。"""

    record_id: str
    code: str
    name: str
    batch_no: str
    quantity: float
    unit: str
    expiry_date: date | None
    status: str                 # normal/quarantine/frozen（QC出报/QA放行映射）
    qc_sample_status: str | None
    qc_report_status: str | None
    qc_release_status: str | None
    category_cn: str = ""

    @property
    def category(self) -> str:
        return CATEGORY_MAP.get(self.category_cn, "raw")


@dataclass(frozen=True)
class MovementView:
    """material_receipt / material_outbound 一行。"""

    record_id: str
    direction: str              # inbound / outbound
    code: str                   # 出库表无代码列 → 名称链回填
    name: str
    batch_no: str
    quantity: float
    unit: str
    occurred_at: datetime
    category_cn: str = ""
    source_type: str = ""       # 由 reader 按表赋值（purchase/production）

    @property
    def category(self) -> str:
        return CATEGORY_MAP.get(self.category_cn, "raw")


# 物料大类（中文）→ 本地 category CHECK 枚举（与回灌脚本映射同源；
# 已是枚举值的原样透传，防御上游直接给英文）
CATEGORY_MAP: dict[str, str] = {
    "原辅料": "raw", "危化品": "raw", "辅料": "auxiliary",
    "包材": "packaging", "中间体": "intermediate", "成品": "finished",
    "raw": "raw", "auxiliary": "auxiliary", "packaging": "packaging",
    "intermediate": "intermediate", "finished": "finished",
}
