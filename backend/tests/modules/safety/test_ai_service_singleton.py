"""AI 客户端进程级单例测试（spec A6③ / S6）。

覆盖 ticket 07：
- 同配置指纹两次 ``get_ai_service`` 返回同一对象；
- 配置指纹变化（model / api_key / backup）返回新对象；
- text/vision 配置指纹相同时仍返回不同实例（config_type 参与 key）；
- 不同 event loop 返回新对象（httpx AsyncClient 不跨 loop 复用）；
- ``close_all_ai_services()`` 关闭并清空缓存；
- ``create_ai_service`` 行为不变（②⑤仍每次新建，不参与单例）。

全部 fake：monkeypatch ``_get_ai_config`` 提供指纹，不发起任何真实 AI 请求。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.modules.safety.service import config as config_module


class _FakeAIConfig:
    """可变的假 AI 配置：改字段即改配置指纹。"""

    def __init__(self) -> None:
        self.model = "model-a"
        self.api_key = "key-a"
        self.backup_model: str | None = None
        # True 时 text/vision 两个 profile 的指纹完全相同（回归 config_type 必须进 key）
        self.same_text_vision_profile = False

    def __call__(self) -> dict[str, Any]:
        backup: dict[str, Any] | None = None
        if self.backup_model:
            backup = {
                "api_key": "backup-key",
                "base_url": "https://backup.example/v1",
                "model": self.backup_model,
                "timeout": 120,
            }
        text_cfg: dict[str, Any] = {
            "api_key": self.api_key,
            "base_url": "https://ai.example/v1",
            "model": self.model,
            "temperature": 0.1,
            "timeout": 120,
            "backup": backup,
        }
        if self.same_text_vision_profile:
            # 与 text 指纹完全一致：仅去掉 backup 键（text 无 backup 时二者指纹相同）
            vision_cfg = {k: v for k, v in text_cfg.items() if k != "backup"}
        else:
            vision_cfg = {
                "api_key": "vision-key",
                "base_url": "https://ai.example/v1",
                "model": "vision-model",
                "temperature": 0.1,
                "timeout": 120,
            }
        return {"text": text_cfg, "vision": vision_cfg}


@pytest.fixture(autouse=True)
async def _clean_ai_service_cache() -> AsyncIterator[None]:
    """单例缓存为进程级：每个用例前后关闭并清空，避免串味/连接泄漏。"""
    await config_module.close_all_ai_services()
    yield
    await config_module.close_all_ai_services()


@pytest.fixture
def fake_ai_config(monkeypatch: pytest.MonkeyPatch) -> _FakeAIConfig:
    cfg = _FakeAIConfig()
    monkeypatch.setattr(config_module, "_get_ai_config", cfg)
    return cfg


# ═══════════════════════════════════════════════════════════
# 1. 指纹命中 / 变化
# ═══════════════════════════════════════════════════════════


async def test_same_fingerprint_returns_same_instance(
    fake_ai_config: _FakeAIConfig,
) -> None:
    first = config_module.get_ai_service("text")
    second = config_module.get_ai_service("text")

    assert first is second
    assert fake_ai_config.model == "model-a"


async def test_model_change_returns_new_instance(
    fake_ai_config: _FakeAIConfig,
) -> None:
    first = config_module.get_ai_service("text")
    fake_ai_config.model = "model-b"
    second = config_module.get_ai_service("text")

    assert second is not first


async def test_api_key_change_returns_new_instance(
    fake_ai_config: _FakeAIConfig,
) -> None:
    first = config_module.get_ai_service("text")
    fake_ai_config.api_key = "key-b"
    second = config_module.get_ai_service("text")

    assert second is not first


async def test_backup_change_returns_new_instance(
    fake_ai_config: _FakeAIConfig,
) -> None:
    first = config_module.get_ai_service("text")
    fake_ai_config.backup_model = "backup-model"
    second = config_module.get_ai_service("text")

    assert second is not first


async def test_different_config_type_returns_different_instance(
    fake_ai_config: _FakeAIConfig,
) -> None:
    text_service = config_module.get_ai_service("text")
    vision_service = config_module.get_ai_service("vision")

    assert text_service is not vision_service


async def test_same_fingerprint_across_config_types_returns_different_instances(
    fake_ai_config: _FakeAIConfig,
) -> None:
    """text/vision 配置指纹完全相同也不得互相顶替：config_type 参与单例 key。"""
    fake_ai_config.same_text_vision_profile = True

    text_service = config_module.get_ai_service("text")
    vision_service = config_module.get_ai_service("vision")

    assert text_service is not vision_service
    # 各自仍按 (loop, config_type, 指纹) 稳定命中
    assert config_module.get_ai_service("text") is text_service
    assert config_module.get_ai_service("vision") is vision_service


async def test_unknown_config_type_raises_value_error(
    fake_ai_config: _FakeAIConfig,
) -> None:
    with pytest.raises(ValueError):
        config_module.get_ai_service("audio")


# ═══════════════════════════════════════════════════════════
# 2. event loop 变化 → 重建
# ═══════════════════════════════════════════════════════════


def test_new_event_loop_returns_new_instance(fake_ai_config: _FakeAIConfig) -> None:
    async def _get() -> Any:
        return config_module.get_ai_service("text")

    first = asyncio.run(_get())
    second = asyncio.run(_get())

    assert first is not second


# ═══════════════════════════════════════════════════════════
# 3. close_all / create_ai_service 兼容
# ═══════════════════════════════════════════════════════════


async def test_close_all_ai_services_closes_and_clears(
    fake_ai_config: _FakeAIConfig,
) -> None:
    service = config_module.get_ai_service("text")
    assert service._client.is_closed is False

    await config_module.close_all_ai_services()

    assert service._client.is_closed is True
    # 缓存已清空：再取得到新实例
    assert config_module.get_ai_service("text") is not service


async def test_create_ai_service_still_returns_new_instances(
    fake_ai_config: _FakeAIConfig,
) -> None:
    """②⑤等既有调用方继续用 create_ai_service：行为保持「每次新建」。"""
    first = config_module.create_ai_service("text")
    second = config_module.create_ai_service("text")
    try:
        assert first is not second
        assert first._client.is_closed is False
    finally:
        await first.close()
        await second.close()


async def test_create_ai_service_does_not_populate_singleton(
    fake_ai_config: _FakeAIConfig,
) -> None:
    created = config_module.create_ai_service("text")
    try:
        singleton = config_module.get_ai_service("text")
        assert singleton is not created
    finally:
        await created.close()
