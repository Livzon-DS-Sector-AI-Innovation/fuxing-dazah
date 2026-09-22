"""key_risk_op 直读改造开关与闸门（全部默认关闭）。

命名与 cert/chemical_inventory 对齐，走 SAFETY_KEY_RISK_OP_* 环境变量：

| 开关 | 默认 | 作用 |
|---|---|---|
| SAFETY_KEY_RISK_OP_DIRECT_ENABLED | false | 列表/统计/详情/导出/Agent 查询走直读 |
| SAFETY_KEY_RISK_OP_EVENT_SYNC_ENABLED | false | Bitable 事件 -> 平台库镜像 |

纯只读域：无 WRITEBACK（源码核实全仓零 Bitable 写入）、无 SYNC_JOB 开关
（手动全量同步入口在直读模式下整体短路，见 service.sync_from_bitable）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_KEY_RISK_OP


def direct_enabled() -> bool:
    """直读总开关（默认关闭）。"""
    return gates.direct_enabled(_DOMAIN)


def event_sync_enabled() -> bool:
    """旧路径：Bitable 事件 -> 平台库镜像。"""
    return gates.event_sync_enabled(_DOMAIN)


def legacy_event_sync_active() -> bool:
    """事件镜像实际生效状态：总开关关闭时旧链路照常。"""
    return gates.legacy_event_sync_active(_DOMAIN)


def cache_ttl_seconds() -> int:
    """直读视图进程内 TTL 缓存秒数（默认 60；0=关）。

    性能例外落档（spec §4.2）：全量拉取 1585 行 4 页串行 ~4.9s 超 <2s 验收线，
    page_token 链式无法并行——按总计划风险表预案以短 TTL 缓存兜住窗口内重复请求。
    """
    return gates.int_env("SAFETY_KEY_RISK_OP_DIRECT_CACHE_TTL_SECONDS", 60, minimum=0)
