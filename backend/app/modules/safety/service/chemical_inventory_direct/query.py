"""直读侧内存查询/统计/只读分析（chemical_inventory-direct Ticket 07）。

口径与镜像一一对应：
- list_records ↔ repo.list_inventory_records（department 等值、material_name 大小写
  不敏感模糊、全量后应用侧分页；排序已由 reader 按镜像 ORDER BY 契约排好）；
- compute_stats ↔ ChemicalInventoryService.get_stats（over_limit/warn/normal/by_flag）；
- analyze_risk ↔ ChemicalInventoryService.analyze_risk（只读，规则引擎吃视图，
  不写库不写 Bitable；msds_names 引擎不消费，直读侧不查库）。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.chemical_inventory.rules import (
    ChemicalRiskRuleEngine,
    compute_risk,
    hits_by_record_id,
)
from app.modules.safety.service.chemical_inventory_direct.views import InventoryView


async def list_records(
    reader: Any,
    skip: int,
    limit: int,
    *,
    department: str | None = None,
    material_name: str | None = None,
) -> tuple[list[InventoryView], int]:
    """全量直读 + 应用侧过滤/分页（对齐镜像 repo.list_inventory_records 口径）。"""
    views = await reader.fetch_all()
    filtered = views
    if department:
        filtered = [v for v in filtered if v.department == department]
    if material_name:
        # 差异说明：镜像用 ilike '%kw%'（%/ _ 是通配符），直读是字面子串匹配——
        # 关键词含 SQL 通配符时两路径结果可能不同（直读侧按字面语义更直观）
        keyword = material_name.lower()
        filtered = [v for v in filtered if keyword in (v.material_name or "").lower()]
    total = len(filtered)
    return filtered[skip : skip + limit], total


def compute_stats(views: list[InventoryView]) -> dict[str, Any]:
    """内存统计（对齐镜像 get_stats 口径）。"""
    by_flag: dict[str, int] = {}
    over_limit = 0
    for view in views:
        by_flag[view.risk_flag] = by_flag.get(view.risk_flag, 0) + 1
        if (
            view.total_quantity_t is not None
            and view.max_limit is not None
            and view.max_limit > 0
            and view.total_quantity_t > view.max_limit
        ):
            over_limit += 1
    return {
        "total_records": len(views),
        "over_limit": over_limit,
        "warn_count": by_flag.get("warn", 0),
        "normal_count": by_flag.get("normal", 0),
        "by_flag": by_flag,
    }


def analyze_risk_views(
    views: list[InventoryView], department: str | None = None
) -> dict[str, Any]:
    """只读风险分析（对齐镜像 analyze_risk 口径；Agent 工具共用）。"""
    if department:
        views = [v for v in views if v.department == department]

    engine = ChemicalRiskRuleEngine()
    hits = hits_by_record_id(engine.scan(views))

    items: list[dict[str, Any]] = []
    for view in views:
        flag, note = compute_risk(hits.get(view.id, []))
        items.append({
            "department": view.department,
            "storage_location": view.storage_location,
            "material_name": view.material_name,
            "risk_flag": flag,
            "risk_note": note,
        })
    return {
        "alert_count": sum(1 for i in items if i["risk_flag"] == "warn"),
        "items": items,
    }
