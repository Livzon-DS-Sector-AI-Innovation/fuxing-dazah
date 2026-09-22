"""危化品库存直读视图对象与镜像口径排序（chemical_inventory-direct Ticket 01）。

照 cert_direct/reader.py 模式：

1. InventoryView：字段名与 ChemicalInventoryRecord ORM 完全同名（id/feishu_record_id/
   created_at/updated_at/is_deleted 由本模块给直读语义的值），规则引擎
   ChemicalRiskRuleEngine 与 daily_report.compute_daily_analysis duck-typing 直接吃。
2. view_from_record_id：复用 enum_maps._map_inventory_fields（与镜像 upsert 同一口径，
   含未映射标签透传）。
3. sort_like_inventory：镜像 list_inventory_records 的 ORDER BY 契约
   （department ASC, material_name ASC）内存复现。

updated_at 语义说明：Bitable「最后更新时间」是 type=1002 ModifiedTime 自动字段
（记录任何修改都会刷新），直读侧同时落到 last_updated_at（镜像同名映射列）与
updated_at（数据新鲜度信号，daily_report 以 updated_at 判定「今日是否真更新过」）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.modules.safety.chemical_inventory.enum_maps import _map_inventory_fields

__all__ = [
    "InventoryView",
    "sort_like_inventory",
    "view_from_record_id",
]


@dataclass
class InventoryView:
    """危化品库存固定行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与元数据（id/feishu_record_id 同值 recXXX：本域镜像按 feishu_record_id 对齐）
    id: str = ""
    feishu_record_id: str | None = None
    created_at: datetime | None = None
    # Bitable「最后更新时间」（ModifiedTime 自动字段）→ 数据新鲜度信号
    updated_at: datetime | None = None
    is_deleted: bool = False

    # 与 ORM 同名的业务列
    department: str = ""
    storage_location: str | None = None
    material_name: str = ""
    package_spec: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    total_quantity_t: Decimal | None = None
    max_limit: Decimal | None = None
    max_limit_unit: str | None = None
    # 默认 None 对齐 ORM（NULL）：直读列表 API 对「危险性为空」行返回 null 与镜像一致
    hazard_classes: list[Any] | None = None
    category: str | None = None
    last_updated_at: datetime | None = None
    remark: str | None = None
    risk_flag: str = "normal"
    risk_note: list[Any] | None = None


def view_from_record_id(
    record_id: str, fields: dict[str, Any]
) -> InventoryView:
    """Bitable 原始 fields dict → 视图对象。

    映射复用镜像同一纯函数（_map_inventory_fields，含透传语义）；
    镜像 upsert 的「无物料名称跳过」由 reader 层负责（与 sync 同位）。
    """
    mapped = _map_inventory_fields(fields)
    view = InventoryView(id=record_id, feishu_record_id=record_id)
    for key, value in mapped.items():
        setattr(view, key, value)
    # 直读侧新鲜度信号：与 last_updated_at 同源（ModifiedTime 自动字段）
    view.updated_at = view.last_updated_at
    return view


def sort_like_inventory(views: list[InventoryView]) -> list[InventoryView]:
    """按镜像 list_inventory_records 的 ORDER BY 契约内存排序（返回新列表）。

    对应 SQL：department ASC, material_name ASC（无第三键；同键组内保持输入顺序，
    Bitable 无时间戳，双路径 tie 组内行序差异属预期，verify 脚本做行序归一比对）。
    注意：中文物料名的码点排序与 PG collation 不保证逐位一致——非 tie 的页内行序
    若出现环境性差异，以此处码点序为准（直读侧确定性排序）。
    """
    rows = list(views)
    rows.sort(key=lambda v: v.material_name)
    rows.sort(key=lambda v: v.department)
    return rows
