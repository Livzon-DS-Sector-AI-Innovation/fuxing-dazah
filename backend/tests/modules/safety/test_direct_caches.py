"""cert / chemical_inventory 直读 TTL 缓存测试（仿 key_risk_op 既有范式）。

spec Testing Decisions 兑现：TTL 命中返回浅拷贝、过期重拉、strict 恒绕过、
ttl<=0 直通。
"""

from __future__ import annotations

import pytest

from app.modules.safety.service.cert_direct.cache import CachedCertReader
from app.modules.safety.service.chemical_inventory_direct.cache import (
    CachedInventoryReader,
)


class _FakeCertInner:
    def __init__(self) -> None:
        self.calls = 0

    async def get_all_active(self, *, strict: bool = False) -> list[str]:
        self.calls += 1
        if strict:
            raise RuntimeError("inner strict path")
        return ["cert-a"]


class _FakeInventoryInner:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_all(self, *, strict: bool = False) -> list[str]:
        self.calls += 1
        if strict:
            raise RuntimeError("inner strict path")
        return ["mat-a"]


async def test_cert_cache_hit_within_ttl() -> None:
    inner = _FakeCertInner()
    cached = CachedCertReader(inner, ttl_seconds=60)
    first = await cached.get_all_active()
    second = await cached.get_all_active()
    assert first == ["cert-a"]
    assert second == ["cert-a"]
    assert second is not first  # 浅拷贝，调用方改 list 不污染缓存
    assert inner.calls == 1  # TTL 窗口内只拉一次
    assert cached.cached is True


async def test_cert_disabled_ttl_passes_through() -> None:
    inner = _FakeCertInner()
    cached = CachedCertReader(inner, ttl_seconds=0)
    await cached.get_all_active()
    await cached.get_all_active()
    assert inner.calls == 2  # ttl<=0 直通
    assert cached.cached is False


async def test_cert_strict_bypasses_cache() -> None:
    inner = _FakeCertInner()
    cached = CachedCertReader(inner, ttl_seconds=60)
    await cached.get_all_active()  # 预热
    with pytest.raises(RuntimeError):
        await cached.get_all_active(strict=True)
    assert inner.calls == 2  # strict 不吃缓存


async def test_inventory_cache_hit_within_ttl() -> None:
    inner = _FakeInventoryInner()
    cached = CachedInventoryReader(inner, ttl_seconds=60)
    first = await cached.fetch_all()
    second = await cached.fetch_all()
    assert first == ["mat-a"]
    assert second is not first
    assert inner.calls == 1
    assert cached.cached is True


async def test_inventory_disabled_ttl_passes_through() -> None:
    inner = _FakeInventoryInner()
    cached = CachedInventoryReader(inner, ttl_seconds=0)
    await cached.fetch_all()
    await cached.fetch_all()
    assert inner.calls == 2


async def test_inventory_strict_bypasses_cache() -> None:
    inner = _FakeInventoryInner()
    cached = CachedInventoryReader(inner, ttl_seconds=60)
    await cached.fetch_all()  # 预热
    with pytest.raises(RuntimeError):
        await cached.fetch_all(strict=True)
    assert inner.calls == 2
