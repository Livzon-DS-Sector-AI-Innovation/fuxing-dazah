"""直读风险重算 + 风险列回写管线（chemical_inventory-direct Ticket 05）。

与镜像版 ChemicalInventoryService.analyze_records 同口径：
- 规则引擎全量跑（ChemicalRiskRuleEngine 零改动吃视图）→ 逐行 compute_risk；
- warn/normal 计数按**计算值**；changed 仅「与当前风险列有差异」的行；
- P2 退役（2026-10-19）：Bitable 总表停写冻结，回写链路删除——本模块只做
  内存重算（供日报/查询/快照），风险值不落任何外部存储。
"""

from __future__ import annotations

import logging

from app.modules.safety.chemical_inventory.rules import (
    ChemicalRiskRuleEngine,
    compute_risk,
    hits_by_record_id,
)
from app.modules.safety.service.chemical_inventory_direct.views import InventoryView

logger = logging.getLogger(__name__)


async def scan_inventory_views(views: list[InventoryView]) -> dict[str, int]:
    """对直读视图全量重算风险；变化行按开关回写风险列。返回镜像版 scan 计数字典。"""
    if not views:
        return {"changed": 0, "warn_count": 0, "normal_count": 0}

    # 规则引擎不消费 msds_names（rules.py：当前规则不依赖），直读侧不查库
    engine = ChemicalRiskRuleEngine()
    rule_alerts = engine.scan(views)

    # 视图 id → 命中的预警类型列表（与镜像 analyze_records 同构）
    hits = hits_by_record_id(rule_alerts)

    changed: list[InventoryView] = []
    warn_count = 0
    normal_count = 0
    for view in views:
        flag, note = compute_risk(hits.get(view.id, []))
        if flag == "warn":
            warn_count += 1
        else:
            normal_count += 1
        if view.risk_flag != flag or (view.risk_note or []) != note:
            view.risk_flag = flag
            view.risk_note = note
            changed.append(view)

    # P2 退役（2026-10-19）：Bitable 总表停写冻结，风险值只在内存与快照，
    # 不再回写（原 WRITEBACK_RISK 回写块随旧链路删码）

    return {
        "changed": len(changed),
        "warn_count": warn_count,
        "normal_count": normal_count,
    }
