r"""chemical_inventory 直读改造开关与闸门（全部默认关闭）。

命名与 cert/central_alarm 对齐，走 SAFETY_CHEMICAL_INVENTORY_* 环境变量：

| 开关 | 默认 | 作用 |
|---|---|---|
| SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED | false | 日报/周报编排与查询路径走直读 |
| SAFETY_CHEMICAL_INVENTORY_EVENT_SYNC_ENABLED | false | Bitable 事件 -> 平台库镜像 |
| SAFETY_CHEMICAL_INVENTORY_SOURCE | bitable | 库存数据源：bitable 总表直读 \| sheet《危险品日报表》直读 |

本域是「写完再读」回写域：WRITEBACK_RISK 只罩直读路径的重算回写；
legacy 模式的既有回写行为不受影响。全默认关 = 与改造前行为逐项一致。

sheet 源（2026-10-15）：SOURCE=sheet 时隐含 direct 语义——所有读路径走
open_reader()（换 SheetsInventoryReader），回滚 = 拨回 bitable，一行不改。
"""

from __future__ import annotations

from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_CHEMICAL_INVENTORY

SOURCE_KEY = "SAFETY_CHEMICAL_INVENTORY_SOURCE"


def current_source() -> str:
    """库存数据源取值：'bitable'（默认）| 'sheet'。

    未知/拼错的值一律按 bitable（安全默认，宁可回退旧行为）。
    """
    raw = _app_config_store.get_raw(SOURCE_KEY)
    value = (raw or "").strip().lower()
    return "sheet" if value == "sheet" else "bitable"


def sheet_source_enabled() -> bool:
    """《危险品日报表》电子表格源是否生效（默认关）。"""
    return current_source() == "sheet"


def direct_enabled() -> bool:
    """直读总开关（sheet 源隐含 direct 语义，D1：读路径统一走 open_reader()）。"""
    return gates.direct_enabled(_DOMAIN) or sheet_source_enabled()


def event_sync_enabled() -> bool:
    """旧路径：Bitable 事件 -> 平台库镜像。"""
    return gates.event_sync_enabled(_DOMAIN)


def legacy_event_sync_active() -> bool:
    """事件镜像实际生效状态：总开关关闭时旧链路照常。"""
    return gates.legacy_event_sync_active(_DOMAIN)


# 直读模式下手工补录端点的统一拒绝文案（cert renew 先例：POST /records 只写
# 平台库镜像、不写 Bitable，直读模式下会写进不可见的死数据，必须拒绝）
RECEIPT_DIRECT_DISABLED_MESSAGE = (
    "直读模式下手工补录不可用，请在飞书表格或当日 Excel 日报中更新库存信息"
)


def receipt_direct_disabled_message() -> str:
    """补录拒绝文案（D7）：sheet 源指向《危险品日报表》，bitable 直读保留原文案。"""
    if sheet_source_enabled():
        return "直读模式下手工补录不可用，请在飞书《危险品日报表》对应子表更新库存"
    return RECEIPT_DIRECT_DISABLED_MESSAGE


def cache_ttl_seconds() -> int:
    """直读视图进程内 TTL 缓存秒数（默认 300；0=关）。

    库存快照表全量拉取无时间窗口概念，overview 驾驶舱聚合 stats+超储明细
    两路都走 fetch_all——仿 key_risk_op 范式兜住窗口内重复请求。
    2026-10-14 由 60 上调：看板口径 5 分钟内新鲜度足够。
    """
    return gates.int_env(
        "SAFETY_CHEMICAL_INVENTORY_DIRECT_CACHE_TTL_SECONDS", 300, minimum=0,
    )
