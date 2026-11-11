"""RAG 知识层健康探活单测 — 状态机翻转/重提醒冷却/恢复通知/开关跳过。

接缝：``run_rag_health_probe`` 对 ``probe_embedding`` / ``probe_ragplus`` /
``_notify_admin`` 的调用面（monkeypatch 注入结果，不发真请求不推真卡）。
"""

from __future__ import annotations

import pytest

from app.modules.safety.knowledge import rag_health
from app.modules.safety.knowledge.rag_health import (
    _STATE,
    run_rag_health_probe,
)

# 每用例前后重置进程级状态机（探活单线程设计，测试串行不冲突）


@pytest.fixture(autouse=True)
def _reset():
    _STATE.reset()
    yield
    _STATE.reset()


def _patch_probes(monkeypatch, embedding, ragplus):
    monkeypatch.setattr(rag_health, "probe_embedding", _amock(embedding))
    monkeypatch.setattr(rag_health, "probe_ragplus", _amock(ragplus))


def _amock(value):
    """把同步值包成 AsyncMock（探活函数均无参）。"""
    from unittest.mock import AsyncMock

    m = AsyncMock(return_value=value)
    return m


def _sent_titles(monkeypatch):
    """记录 _notify_admin 收到的标题列表。"""
    titles: list[str] = []

    async def fake_notify(title: str, content: str) -> bool:
        titles.append(title)
        return True

    monkeypatch.setattr(rag_health, "_notify_admin", fake_notify)
    return titles


# ── 状态机 ────────────────────────────────────────────────────


async def test_healthy_no_alert(monkeypatch):
    titles = _sent_titles(monkeypatch)
    _patch_probes(monkeypatch, (True, "ok"), (True, "命中 1 条"))
    result = await run_rag_health_probe()
    assert result["healthy"] is True
    assert result["alerted"] is False
    assert titles == []


async def test_degraded_alerts_once(monkeypatch):
    titles = _sent_titles(monkeypatch)
    err = (False, 'HTTP 429: {"error":{"code":"1113","message":"余额不足或无可用资源包"}}')
    _patch_probes(monkeypatch, err, (False, "RagplusUnavailableError: HTTP 500"))
    await run_rag_health_probe()
    assert len(titles) == 1 and "探活失败" in titles[0]
    # 故障持续 + 冷却内 → 不重复告警
    await run_rag_health_probe()
    await run_rag_health_probe()
    assert len(titles) == 1


async def test_repeat_alert_after_cooldown(monkeypatch):
    titles = _sent_titles(monkeypatch)
    _patch_probes(monkeypatch, (False, "HTTP 429: 余额不足"), None)
    monkeypatch.setattr(rag_health, "_repeat_seconds", lambda: 0)  # 冷却归零
    await run_rag_health_probe()
    await run_rag_health_probe()  # 间隔到点 → 重提醒
    assert len(titles) == 2 and "持续" in titles[1]


async def test_recovery_notifies_with_duration(monkeypatch):
    titles = _sent_titles(monkeypatch)
    _patch_probes(monkeypatch, (False, "HTTP 429"), (True, "ok"))
    await run_rag_health_probe()
    _patch_probes(monkeypatch, (True, "ok"), (True, "ok"))
    result = await run_rag_health_probe()
    assert result["healthy"] is True
    assert len(titles) == 2 and "已恢复" in titles[1]
    # 恢复后再跑：回到常态静默
    await run_rag_health_probe()
    assert len(titles) == 2


async def test_ragplus_skipped_when_switch_off(monkeypatch):
    """ragplus 检索开关关 → 该项跳过（None），embedding 单项判定。"""
    titles = _sent_titles(monkeypatch)
    monkeypatch.setattr(
        "app.modules.safety.app_config.store.store.get_bool",
        lambda key, default=None: False,
    )
    _patch_probes(monkeypatch, (False, "HTTP 429: 余额不足"), None)
    result = await run_rag_health_probe()
    assert result["healthy"] is False
    assert result["ragplus"] is None
    assert len(titles) == 1  # ragflow 跳过但 embedding 失败仍告警


async def test_first_alert_send_failure_retries_next_round(monkeypatch):
    """首告警发送失败（False）→ 下轮继续尝试而非等冷却。"""
    titles = _sent_titles(monkeypatch)

    async def flaky(title: str, content: str) -> bool:
        titles.append(title)
        return len(titles) > 1  # 第一次失败，第二次成功

    monkeypatch.setattr(rag_health, "_notify_admin", flaky)
    _patch_probes(monkeypatch, (False, "HTTP 429"), None)
    await run_rag_health_probe()
    assert _STATE.last_alert_at is None  # 失败不记冷却锚点
    await run_rag_health_probe()
    assert len(titles) == 2
    assert _STATE.last_alert_at is not None


# ── 探活实现（真函数，网络面 mock httpx）──────────────────────


async def test_probe_embedding_no_config(monkeypatch):
    monkeypatch.delenv("SAFETY_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("SAFETY_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setattr(
        "app.modules.safety.ai_config.resolver.get_profile_config",
        lambda profile: {},
    )
    ok, detail = await rag_health.probe_embedding()
    assert ok is False and "未配置" in detail
