"""直读风险重算 + 风险列回写管线（chemical_inventory-direct Ticket 05）。

与镜像版 ChemicalInventoryService.analyze_records 同口径：
- 规则引擎全量跑（ChemicalRiskRuleEngine 零改动吃视图）→ 逐行 compute_risk；
- warn/normal 计数按**计算值**；changed 仅「与当前风险列有差异」的行；
- 回写复用 feishu handler 的 sync_record_flags_to_bitable（duck-typing 直接吃视图：
  feishu_record_id/risk_flag/risk_note），写请求只含 风险标记/风险说明 两列，
  写前 _set_sync_ignore 防环——零改动复用（ticket 05 验收）；
- WRITEBACK_RISK 开关只罩本管线的回写：关 = 内存算风险供日报、不写 Bitable；
  legacy 路径的既有回写不经过本模块（行为零变化）。
- 回写失败降级为日志（与 legacy analyze_records 的 try/except 语义一致），
  不阻断日报/扫描返回。
"""

from __future__ import annotations

import logging

from app.modules.safety.chemical_inventory.rules import (
    ChemicalRiskRuleEngine,
    compute_risk,
    hits_by_record_id,
)
from app.modules.safety.service.chemical_inventory_direct import config
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

    if changed and config.writeback_risk_enabled():
        try:
            # 惰性导入：测试哨兵替换点；防环/两列白名单在函数内实现
            from app.modules.safety.feishu.chemical_inventory_bitable_handler import (
                sync_record_flags_to_bitable,
            )

            await sync_record_flags_to_bitable(changed)
        except Exception:  # noqa: BLE001
            logger.exception("危化品库存直读风险标记回写失败")

    return {
        "changed": len(changed),
        "warn_count": warn_count,
        "normal_count": normal_count,
    }
