"""labor_supply 模块级取数函数（API/档案/agent 共用，仿 oh_direct/ledger.py）。

模块级单例持有 CachedLaborReader（TTL 见 config）；测试经 monkeypatch
本模块 ``enabled`` / ``fetch_products`` / ``fetch_position_standards``。
"""

from __future__ import annotations

import logging

from . import config
from .cache import CachedLaborReader
from .reader import (
    DOMAIN,
    KIND_PRODUCT,
    LaborProductView,
    PositionStandardView,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DOMAIN",
    "KIND_PRODUCT",
    "enabled",
    "fetch_products",
    "fetch_position_standards",
    "reset_reader",
]

_reader: CachedLaborReader | None = None


def enabled() -> bool:
    """直读开关（默认开；关=全链路降级不触达飞书）。"""
    return config.direct_enabled()


def _get_reader() -> CachedLaborReader:
    global _reader
    if _reader is None:
        from .reader import open_reader

        _reader = open_reader()
    return _reader


def reset_reader() -> None:
    """丢弃单例（配置变更/测试用）。"""
    global _reader
    _reader = None


async def fetch_products() -> list[LaborProductView]:
    """产品目录全量视图（TTL 缓存；strict 上抛由调用方降级）。"""
    return await _get_reader().fetch_products()


async def fetch_position_standards() -> list[PositionStandardView]:
    """岗位/部门配备标准全量视图（TTL 缓存）。"""
    return await _get_reader().fetch_position_standards()
