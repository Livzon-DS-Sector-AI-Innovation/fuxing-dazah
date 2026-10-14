"""中控报警直读改造开关与闸门（全部默认关闭）。

命名与隐患 / 特殊作业 / 消防对齐，全部走 SAFETY_CENTRAL_ALARM_* 环境变量：

| 开关 | 默认 | 作用 |
|---|---|---|
| SAFETY_CENTRAL_ALARM_DIRECT_ENABLED | false | 生成/查询路径走直读 |
| SAFETY_CENTRAL_ALARM_EVENT_SYNC_ENABLED | false | Bitable 事件 -> 平台库镜像 |
| SAFETY_CENTRAL_ALARM_SYNC_JOB_ENABLED | false | 生成前全量同步兜底 |

纯只读域：无 WRITEBACK 开关（AI 分析不落 Bitable，已拍板不落盘每日重跑）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_CENTRAL_ALARM


def direct_enabled() -> bool:
    """直读总开关（默认关闭）。"""
    return gates.direct_enabled(_DOMAIN)


def event_sync_enabled() -> bool:
    """旧路径：Bitable 事件 -> 平台库镜像。"""
    return gates.event_sync_enabled(_DOMAIN)


def sync_job_enabled() -> bool:
    """旧路径：生成前全量同步兜底。"""
    return gates.sync_job_enabled(_DOMAIN)


def legacy_event_sync_active() -> bool:
    """事件镜像实际生效状态：总开关关闭时旧链路照常。"""
    return gates.legacy_event_sync_active(_DOMAIN)


def legacy_sync_job_active() -> bool:
    """全量同步实际生效状态：总开关关闭时旧链路照常。"""
    return gates.legacy_sync_job_active(_DOMAIN)


def cache_ttl_seconds() -> int:
    """窗口拉取进程内 TTL 缓存秒数（默认 300；0=关）。

    中控是 14 张同构表逐表窗口取数，总览驾驶舱每次刷新都实打 Bitable
    实测 ~4.7s——看板口径 5 分钟内复用同一窗口结果；日报编排 strict=True
    路径绕过缓存现拉。仅 open_reader() 单例创建时读取一次。
    """
    return gates.int_env(
        gates.domain_env(_DOMAIN, "DIRECT_CACHE_TTL_SECONDS"), 300, minimum=0,
    )
