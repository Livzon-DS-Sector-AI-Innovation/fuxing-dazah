"""Feishu tenant token 进程内缓存 + Bitable token 失效重试测试（spec A6② / S5）。

覆盖 ticket 07：
- 连续 10 次调用底层 token 请求只发生 1 次（进程内缓存）；
- 按响应 ``expire`` 提前刷新（margin = min(300s, 10%)，假时钟推进）；缺省 7200；
- ``invalidate_safety_tenant_token()`` 后下一次调用重新取；
- 缓存不绑定 event loop（跨 loop 复用缓存 / 单飞锁换 loop 不报错）；
- 获取失败仍抛 RuntimeError 且不污染缓存；
- 缓存按 app_id 分键（F10）：两个应用互不串用、invalidate 支持单 app 粒度；
- 主路径 ``search_records`` / ``update_record`` / ``download_attachment_from_url``
  遇到飞书 token 失效码 → invalidate 后重试一次（仅一次）。

全部 fake：假 lark client（token 外部边界）+ httpx.MockTransport（HTTP 边界），
无真实网络/真实飞书请求。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.modules.safety.feishu import bitable_client as bitable_module
from app.modules.safety.feishu import client as client_module
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.client import (
    get_safety_tenant_token,
    invalidate_safety_tenant_token,
)

# ═══════════════════════════════════════════════════════════
# fake 外部边界：假单调时钟 + 假 lark tenant_access_token API
# ═══════════════════════════════════════════════════════════


class _FakeClock:
    """假单调时钟：避免真实 sleep / 墙钟依赖。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeTokenResponse:
    """假 lark 响应：``success()`` + ``raw.content``（JSON bytes）契约。"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        code: int = 0,
        msg: str = "ok",
    ) -> None:
        self.code = code
        self.msg = msg
        content = json.dumps(payload).encode("utf-8") if payload else b"{}"
        self.raw = SimpleNamespace(content=content)

    def success(self) -> bool:
        return self.code == 0


class _FakeTenantTokenAPI:
    """假 lark ``client.auth.v3.tenant_access_token`` API（token 获取唯一外部边界）。"""

    def __init__(
        self,
        tokens: list[str],
        *,
        expire: int | None = 7200,
        fail_times: int = 0,
    ) -> None:
        self.tokens = tokens
        self.expire = expire
        self.fail_times = fail_times
        self.calls = 0

    async def ainternal(self, request: Any) -> _FakeTokenResponse:
        # sleep(0) 让并发调用真正交错，检验单飞锁
        await asyncio.sleep(0)
        call_index = self.calls
        self.calls += 1
        if call_index < self.fail_times:
            return _FakeTokenResponse({}, code=99991663, msg="invalid credential")
        token = self.tokens[min(call_index - self.fail_times, len(self.tokens) - 1)]
        payload: dict[str, Any] = {"tenant_access_token": token}
        if self.expire is not None:
            payload["expire"] = self.expire
        return _FakeTokenResponse(payload)


def _fake_lark_client(api: _FakeTenantTokenAPI) -> Any:
    """构造只暴露 token 获取路径的假 lark client。"""
    return SimpleNamespace(auth=SimpleNamespace(v3=SimpleNamespace(tenant_access_token=api)))


# ═══════════════════════════════════════════════════════════
# fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def token_cache_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeClock]:
    """每个用例：清空 token 缓存 + 注入假时钟（缓存为进程级，必须隔离）。"""
    clock = _FakeClock()
    monkeypatch.setattr(client_module, "_now", clock)
    invalidate_safety_tenant_token()
    yield clock
    invalidate_safety_tenant_token()


@pytest.fixture
def fake_tenant_api(monkeypatch: pytest.MonkeyPatch) -> _FakeTenantTokenAPI:
    """把「构建 lark client」替换为假 client（不触真实网络/凭证校验）。"""
    api = _FakeTenantTokenAPI(tokens=["tok-1", "tok-2"])
    async def _fake_client_factory() -> Any:
        return _fake_lark_client(api)

    monkeypatch.setattr(client_module, "get_safety_feishu_client", _fake_client_factory)
    return api


@pytest.fixture
def bitable(monkeypatch: pytest.MonkeyPatch) -> SafetyBitableClient:
    """构造显式 app_token/table_id 的 Bitable client（不读 DB 配置）。"""
    monkeypatch.setattr(
        bitable_module.store, "get_connection", lambda *args, **kwargs: None,
    )
    return SafetyBitableClient(app_token="app-token", table_id="table-id")


def _patch_http(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    """把 bitable 模块的 httpx.AsyncClient 换成 MockTransport 记录式假件。"""
    requests: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(_record)

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        kwargs.pop("follow_redirects", None)
        return httpx.AsyncClient(transport=transport, **kwargs)

    monkeypatch.setattr(bitable_module, "httpx", SimpleNamespace(AsyncClient=_factory))
    return requests


# ═══════════════════════════════════════════════════════════
# 1. 缓存命中
# ═══════════════════════════════════════════════════════════


async def test_ten_calls_hit_cache_with_single_token_fetch() -> None:
    api = _FakeTenantTokenAPI(tokens=["tok-1"], expire=7200)
    fake = _fake_lark_client(api)

    tokens = [await get_safety_tenant_token(fake) for _ in range(10)]

    assert tokens == ["tok-1"] * 10
    assert api.calls == 1  # 连续 10 次调用只取 1 次


async def test_concurrent_calls_single_flight() -> None:
    api = _FakeTenantTokenAPI(tokens=["tok-1"], expire=7200)
    fake = _fake_lark_client(api)

    results = await asyncio.gather(
        *(get_safety_tenant_token(fake) for _ in range(10))
    )

    assert set(results) == {"tok-1"}
    assert api.calls == 1  # 并发穿透被单飞锁挡住


async def test_cache_hit_does_not_build_lark_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeTenantTokenAPI(tokens=["tok-1"])
    await get_safety_tenant_token(_fake_lark_client(api))

    async def _explode() -> Any:
        raise AssertionError("缓存命中不应构建 lark client / 发起 token 请求")

    monkeypatch.setattr(client_module, "get_safety_feishu_client", _explode)

    assert await get_safety_tenant_token() == "tok-1"
    assert api.calls == 1


# ═══════════════════════════════════════════════════════════
# 2. 按 expire 提前刷新
# ═══════════════════════════════════════════════════════════


async def test_refresh_before_expiry_by_ten_percent(
    token_cache_env: _FakeClock,
) -> None:
    # expire=1000s → 10% = 100s < 300s，margin 取 100s，刷新点 = 900s
    api = _FakeTenantTokenAPI(tokens=["tok-1", "tok-2"], expire=1000)
    fake = _fake_lark_client(api)

    assert await get_safety_tenant_token(fake) == "tok-1"

    token_cache_env.advance(899)
    assert await get_safety_tenant_token(fake) == "tok-1"
    assert api.calls == 1

    token_cache_env.advance(2)  # 901 > 900 → 提前刷新
    assert await get_safety_tenant_token(fake) == "tok-2"
    assert api.calls == 2


async def test_refresh_uses_300s_margin_cap_for_long_expire(
    token_cache_env: _FakeClock,
) -> None:
    # expire=7200s → 10% = 720s > 300s，margin 封顶 300s，刷新点 = 6900s
    api = _FakeTenantTokenAPI(tokens=["tok-1", "tok-2"], expire=7200)
    fake = _fake_lark_client(api)

    assert await get_safety_tenant_token(fake) == "tok-1"

    token_cache_env.advance(6899)
    assert await get_safety_tenant_token(fake) == "tok-1"
    assert api.calls == 1

    token_cache_env.advance(2)  # 6901 > 6900
    assert await get_safety_tenant_token(fake) == "tok-2"
    assert api.calls == 2


async def test_missing_expire_defaults_to_7200(
    token_cache_env: _FakeClock,
) -> None:
    api = _FakeTenantTokenAPI(tokens=["tok-1", "tok-2"], expire=None)
    fake = _fake_lark_client(api)

    assert await get_safety_tenant_token(fake) == "tok-1"

    token_cache_env.advance(6899)
    assert await get_safety_tenant_token(fake) == "tok-1"
    assert api.calls == 1

    token_cache_env.advance(2)
    assert await get_safety_tenant_token(fake) == "tok-2"
    assert api.calls == 2


# ═══════════════════════════════════════════════════════════
# 3. 强制失效 / 失败语义 / 跨 event loop
# ═══════════════════════════════════════════════════════════


async def test_invalidate_forces_refetch() -> None:
    api = _FakeTenantTokenAPI(tokens=["tok-1", "tok-2"])
    fake = _fake_lark_client(api)

    assert await get_safety_tenant_token(fake) == "tok-1"
    invalidate_safety_tenant_token()
    assert await get_safety_tenant_token(fake) == "tok-2"
    assert api.calls == 2


async def test_fetch_failure_raises_runtime_error_and_does_not_poison_cache() -> None:
    api = _FakeTenantTokenAPI(tokens=["tok-1"], fail_times=1)
    fake = _fake_lark_client(api)

    with pytest.raises(RuntimeError):
        await get_safety_tenant_token(fake)

    # 失败不缓存：下一次调用重新取并成功
    assert await get_safety_tenant_token(fake) == "tok-1"
    assert api.calls == 2


def test_token_cache_and_lock_survive_new_event_loop() -> None:
    """缓存是进程级、单飞锁按 loop 重建：换 loop 不报 "bound to a different loop"。"""
    api = _FakeTenantTokenAPI(tokens=["tok-1", "tok-2"])
    fake = _fake_lark_client(api)

    async def _call() -> str:
        return await get_safety_tenant_token(fake)

    assert asyncio.run(_call()) == "tok-1"  # loop A：缓存填充 + 单飞锁首次使用
    invalidate_safety_tenant_token()
    assert asyncio.run(_call()) == "tok-2"  # loop B：cache miss 走新锁，不得抛 loop 绑定错误
    assert api.calls == 2


# ═══════════════════════════════════════════════════════════
# 4. Bitable 主路径：token 失效码 → invalidate 后重试一次
# ═══════════════════════════════════════════════════════════

_TOKEN_INVALID_BODY = {"code": 99991663, "msg": "invalid tenant_access_token"}


def _auth_of(request: httpx.Request) -> str:
    return request.headers.get("authorization", "")


async def test_search_records_retries_once_on_token_invalid(
    bitable: SafetyBitableClient,
    fake_tenant_api: _FakeTenantTokenAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _auth_of(request) == "Bearer tok-1":
            return httpx.Response(200, json=_TOKEN_INVALID_BODY)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [{"record_id": "rec-1", "fields": {}}],
                    "has_more": False,
                    "page_token": None,
                    "total": 1,
                },
            },
        )

    requests = _patch_http(monkeypatch, handler)

    result = await bitable.search_records()

    assert result["items"] == [{"record_id": "rec-1", "fields": {}}]
    assert [_auth_of(r) for r in requests] == ["Bearer tok-1", "Bearer tok-2"]
    assert fake_tenant_api.calls == 2  # 失效后真的重新取 token


async def test_update_record_retries_once_on_token_invalid(
    bitable: SafetyBitableClient,
    fake_tenant_api: _FakeTenantTokenAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if _auth_of(request) == "Bearer tok-1":
            return httpx.Response(
                200, json={"code": 99991668, "msg": "tenant_access_token expired"},
            )
        return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "rec-1"}}})

    requests = _patch_http(monkeypatch, handler)

    ok = await bitable.update_record("rec-1", {"隐患分类（AI）": "机械"})

    assert ok is True
    assert [_auth_of(r) for r in requests] == ["Bearer tok-1", "Bearer tok-2"]
    assert fake_tenant_api.calls == 2


async def test_download_attachment_from_url_retries_once_on_token_invalid(
    bitable: SafetyBitableClient,
    fake_tenant_api: _FakeTenantTokenAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jpeg = b"\xff\xd8\xff\xe0" + b"fake-jpeg" * 4

    def handler(request: httpx.Request) -> httpx.Response:
        if _auth_of(request) == "Bearer tok-1":
            return httpx.Response(
                200, json={"code": 99991661, "msg": "invalid tenant_access_token"},
            )
        return httpx.Response(
            200, content=jpeg, headers={"content-type": "image/jpeg"},
        )

    requests = _patch_http(monkeypatch, handler)

    data = await bitable.download_attachment_from_url(
        "https://open.feishu.cn/open-apis/drive/v1/medias/file-1/download"
    )

    assert data == jpeg
    assert [_auth_of(r) for r in requests] == ["Bearer tok-1", "Bearer tok-2"]
    assert fake_tenant_api.calls == 2


async def test_token_invalid_retry_happens_only_once(
    bitable: SafetyBitableClient,
    fake_tenant_api: _FakeTenantTokenAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """刷新后的 token 仍被判失效时只再试一次（共 2 次请求），不无限重试。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_TOKEN_INVALID_BODY)

    requests = _patch_http(monkeypatch, handler)

    data = await bitable.download_attachment_from_url(
        "https://open.feishu.cn/open-apis/drive/v1/medias/file-1/download"
    )

    assert data is None
    assert len(requests) == 2
    assert fake_tenant_api.calls == 2


async def test_main_paths_reuse_cached_token_without_refetch(
    bitable: SafetyBitableClient,
    fake_tenant_api: _FakeTenantTokenAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})

    requests = _patch_http(monkeypatch, handler)

    await bitable.search_records()
    await bitable.search_records()

    assert len(requests) == 2
    assert fake_tenant_api.calls == 1  # 两条主路径复用同一缓存 token


# ═══════════════════════════════════════════════════════════
# 5. F10：token 缓存按 app_id 分键 + invalidate 粒度
# ═══════════════════════════════════════════════════════════


async def test_two_apps_have_separate_token_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不同 app 凭证的 token 缓存互不串用（进程内多应用安全）。"""
    api = _FakeTenantTokenAPI(tokens=["tok-a", "tok-b"])
    fake = _fake_lark_client(api)

    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-a")
    assert await get_safety_tenant_token(fake) == "tok-a"

    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-b")
    assert await get_safety_tenant_token(fake) == "tok-b"
    assert api.calls == 2

    # 切回 app-a：命中 app-a 自己的缓存，不重新取
    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-a")
    assert await get_safety_tenant_token(fake) == "tok-a"
    assert api.calls == 2


async def test_invalidate_single_app_keeps_other_app_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """invalidate(app_id) 只清该应用；其余应用缓存保留。"""
    api = _FakeTenantTokenAPI(tokens=["tok-a", "tok-b"])
    fake = _fake_lark_client(api)

    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-a")
    assert await get_safety_tenant_token(fake) == "tok-a"
    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-b")
    assert await get_safety_tenant_token(fake) == "tok-b"
    assert api.calls == 2

    invalidate_safety_tenant_token("app-b")
    # 只清 app-b：下一次 app-b 调用重取（app-a 不受影响）
    assert await get_safety_tenant_token(fake) == "tok-b"
    assert api.calls == 3

    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-a")
    assert await get_safety_tenant_token(fake) == "tok-a"
    assert api.calls == 3  # app-a 缓存保留，未重取


async def test_invalidate_without_app_clears_all_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """invalidate() 无参 = 全部清（维持既有调用语义）。"""
    api = _FakeTenantTokenAPI(tokens=["tok-a", "tok-b"])
    fake = _fake_lark_client(api)

    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-a")
    assert await get_safety_tenant_token(fake) == "tok-a"
    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-b")
    assert await get_safety_tenant_token(fake) == "tok-b"
    assert api.calls == 2

    invalidate_safety_tenant_token()
    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-a")
    await get_safety_tenant_token(fake)
    monkeypatch.setattr(client_module, "SAFETY_FEISHU_APP_ID", "app-b")
    await get_safety_tenant_token(fake)
    assert api.calls == 4  # 全部清 → 两个 app 都重取
