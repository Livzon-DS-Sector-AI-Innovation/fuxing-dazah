from __future__ import annotations

from app.modules.energy.adapters.base import BasePlatformAdapter, CollectResult
from app.modules.energy.adapters.platform_a import PlatformAAdapter
from app.modules.energy.adapters.platform_b import PlatformBAdapter
from app.modules.energy.adapters.platform_c import PlatformCAdapter

ADAPTERS: dict[str, BasePlatformAdapter] = {
    "platform_a": PlatformAAdapter(),
    "platform_b": PlatformBAdapter(),
    "platform_c": PlatformCAdapter(),
}

__all__ = [
    "BasePlatformAdapter",
    "CollectResult",
    "PlatformAAdapter",
    "PlatformBAdapter",
    "PlatformCAdapter",
    "ADAPTERS",
]
