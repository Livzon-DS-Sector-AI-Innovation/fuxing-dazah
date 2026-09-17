"""消防报警直读改造开关与闸门（全部默认关闭）。

命名与隐患 / 特殊作业对齐，全部走 SAFETY_FIRE_ALARM_* 环境变量：

| 开关 | 默认 | 作用 |
|---|---|---|
| SAFETY_FIRE_ALARM_DIRECT_ENABLED | false | 生成路径走直读 |
| SAFETY_FIRE_ALARM_EVENT_SYNC_ENABLED | false | Bitable 事件 -> 平台库镜像 |
| SAFETY_FIRE_ALARM_SYNC_JOB_ENABLED | false | 生成前全量同步兜底 |
| SAFETY_FIRE_ALARM_WRITEBACK_AI_ENABLED | false | AI 结果回写 Bitable |

既有开关 SAFETY_FIRE_ALARM_DAILY_DM_ENABLED 语义与默认值不变。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_FIRE_ALARM


def direct_enabled() -> bool:
    """生成路径直读总开关（默认关闭）。"""
    return gates.direct_enabled(_DOMAIN)


def event_sync_enabled() -> bool:
    """旧路径：Bitable 事件 -> 平台库镜像。"""
    return gates.event_sync_enabled(_DOMAIN)


def sync_job_enabled() -> bool:
    """旧路径：生成前全量同步兜底。"""
    return gates.sync_job_enabled(_DOMAIN)


def writeback_ai_enabled() -> bool:
    """AI 结果回写 Bitable（默认关闭）。"""
    return gates.writeback_enabled(_DOMAIN, "AI")


def legacy_event_sync_active() -> bool:
    """事件镜像实际生效状态：总开关关闭时旧链路照常。"""
    return gates.legacy_event_sync_active(_DOMAIN)


def legacy_sync_job_active() -> bool:
    """全量同步实际生效状态：总开关关闭时旧链路照常。"""
    return gates.legacy_sync_job_active(_DOMAIN)
