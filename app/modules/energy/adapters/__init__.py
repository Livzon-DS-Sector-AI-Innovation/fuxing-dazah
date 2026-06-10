from __future__ import annotations

from app.modules.energy.adapters.base import BasePlatformAdapter, CollectResult
from app.modules.energy.adapters.platform_a import ZhihengWaterAdapter
from app.modules.energy.adapters.platform_b import PlatformBAdapter
from app.modules.energy.adapters.platform_c import PlatformCAdapter

ADAPTERS: dict[str, BasePlatformAdapter] = {
    "zhiheng": ZhihengWaterAdapter(),
    "platform_b": PlatformBAdapter(),
    "platform_c": PlatformCAdapter(),
}

__all__ = [
    "BasePlatformAdapter",
    "CollectResult",
    "ZhihengWaterAdapter",
    "PlatformBAdapter",
    "PlatformCAdapter",
    "ADAPTERS",
]
