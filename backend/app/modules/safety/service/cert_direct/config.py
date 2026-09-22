"""cert 持证到期直读改造开关与闸门（全部默认关闭）。

命名与 central_alarm 对齐，走 SAFETY_CERT_* 环境变量：

| 开关 | 默认 | 作用 |
|---|---|---|
| SAFETY_CERT_DIRECT_ENABLED | false | 预警任务/查询路径走直读 |
| SAFETY_CERT_EVENT_SYNC_ENABLED | false | Bitable 事件 -> 平台库镜像 |

纯只读域：无 SYNC_JOB（cert 无同步兜底任务）、无 WRITEBACK
（已拍板：renew 回填闭环在直读模式下禁用，不建列不回写 Bitable）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_CERT


def direct_enabled() -> bool:
    """直读总开关（默认关闭）。"""
    return gates.direct_enabled(_DOMAIN)


def event_sync_enabled() -> bool:
    """旧路径：Bitable 事件 -> 平台库镜像。"""
    return gates.event_sync_enabled(_DOMAIN)


def legacy_event_sync_active() -> bool:
    """事件镜像实际生效状态：总开关关闭时旧链路照常。"""
    return gates.legacy_event_sync_active(_DOMAIN)


# renew 回填闭环在直读模式下的统一拒绝文案（API 400 与 Agent error 同口径）
RENEW_DIRECT_DISABLED_MESSAGE = "直读模式下回填不可用，请在飞书表格中更新证件信息"
