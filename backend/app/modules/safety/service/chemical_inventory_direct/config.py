"""chemical_inventory 直读改造开关与闸门（全部默认关闭）。

命名与 cert/central_alarm 对齐，走 SAFETY_CHEMICAL_INVENTORY_* 环境变量：

| 开关 | 默认 | 作用 |
|---|---|---|
| SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED | false | 日报/周报编排与查询路径走直读 |
| SAFETY_CHEMICAL_INVENTORY_EVENT_SYNC_ENABLED | false | Bitable 事件 -> 平台库镜像 |
| SAFETY_CHEMICAL_INVENTORY_WRITEBACK_RISK_ENABLED | false | 直读重算的风险列回写 |

本域是「写完再读」回写域：WRITEBACK_RISK 只罩直读路径的重算回写；
legacy 模式的既有回写行为不受影响。全默认关 = 与改造前行为逐项一致。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_CHEMICAL_INVENTORY


def direct_enabled() -> bool:
    """直读总开关（默认关闭）。"""
    return gates.direct_enabled(_DOMAIN)


def event_sync_enabled() -> bool:
    """旧路径：Bitable 事件 -> 平台库镜像。"""
    return gates.event_sync_enabled(_DOMAIN)


def writeback_risk_enabled() -> bool:
    """直读重算的风险列回写（默认关闭；legacy 回写不受影响）。"""
    return gates.writeback_enabled(_DOMAIN, "RISK")


def legacy_event_sync_active() -> bool:
    """事件镜像实际生效状态：总开关关闭时旧链路照常。"""
    return gates.legacy_event_sync_active(_DOMAIN)


# 直读模式下手工补录端点的统一拒绝文案（cert renew 先例：POST /records 只写
# 平台库镜像、不写 Bitable，直读模式下会写进不可见的死数据，必须拒绝）
RECEIPT_DIRECT_DISABLED_MESSAGE = (
    "直读模式下手工补录不可用，请在飞书表格或当日 Excel 日报中更新库存信息"
)
