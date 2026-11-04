"""直读开关与缓存参数（仓库自有 runtime，2026-11-04 直读改造）。

- ``warehouse_direct_read_enabled``：默认 **1=直读**（用户拍板路线）；0=一键
  回退镜像原路径（逐字节不变）。真值集对齐安全模块 gates.flag。
- ``warehouse_direct_cache_ttl_seconds``：三域统一 TTL，默认 300；0=关
  （每次直读，无缓存）。改值后下一次取数生效（无需重启）。
"""

from __future__ import annotations

from app.modules.warehouse.ops_config.runtime_store import runtime_store

_TRUE = {"1", "true", "yes", "on"}


def direct_read_enabled() -> bool:
    """展示/分析类端点是否走直读（fail-safe：非法值按 1=直读，用户已定路线）。"""
    raw = str(runtime_store.get_value("warehouse_direct_read_enabled") or "").strip().lower()
    if raw in _TRUE | {"0", "false", "no", "off"}:
        return raw in _TRUE
    return True


def cache_ttl_seconds() -> int:
    """直读缓存 TTL 秒（≤0 = 关闭缓存）。"""
    try:
        return int(runtime_store.get_value("warehouse_direct_cache_ttl_seconds"))
    except (TypeError, ValueError):
        return 300
