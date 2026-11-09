"""labor_supply 直读开关（默认开）。

与 hazard/msds 等「镜像→直读」切换闸不同：本域**无镜像回退路径**，开关
纯粹是下线闸——关掉后面板/API/agent 全部走 not_enabled 降级，不再读
飞书。默认 True。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

DOMAIN = gates.DOMAIN_LABOR_SUPPLY

DEFAULT_CACHE_TTL_SECONDS = 300


def direct_enabled() -> bool:
    """直读开关（默认开：无镜像回退路径，仅作下线闸）。"""
    return gates.flag(gates.domain_env(DOMAIN, "DIRECT_ENABLED"), True)


def cache_ttl_seconds() -> int:
    """直读视图进程内 TTL 缓存窗口（秒，默认 300）。

    零感知读取（0=关直通）：gates.int_env 有 minimum=1 下限会吞掉 0，
    故直读 raw 解析（与 gates 同一条 env > DB 活行 > 默认链）。
    """
    from app.modules.safety.app_config.store import store as _app_config_store

    raw = _app_config_store.get_raw(
        gates.domain_env(DOMAIN, "DIRECT_CACHE_TTL_SECONDS")
    )
    try:
        return int(raw.strip()) if raw else DEFAULT_CACHE_TTL_SECONDS
    except ValueError:
        return DEFAULT_CACHE_TTL_SECONDS
