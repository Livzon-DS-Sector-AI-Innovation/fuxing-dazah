"""周期汇总 AI prompt 单测——ticket 01 RED。"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.safety.service.central_alarm.aggregator import aggregate_period
from app.modules.safety.service.central_alarm.prompts import (
    EXPECTED_KEYS_PERIOD_SUMMARY,
    build_period_summary_messages,
)


def _agg(kind: str = "weekly"):
    return aggregate_period(
        [], kind=kind,
        period_start=date(2026, 11, 2), period_end=date(2026, 11, 8),
    )


def test_expected_keys_contract() -> None:
    # 改进意见是独立键（用户需求：报告中给出改进意见）
    assert EXPECTED_KEYS_PERIOD_SUMMARY == [
        "summary", "key_issues", "improvement_suggestions",
    ]


def test_messages_structure_and_payload() -> None:
    agg = _agg()
    messages = build_period_summary_messages(agg)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    # system 为稳定常量（前缀缓存友好）：不含周期数据
    assert "2026" not in messages[0]["content"]
    user = messages[1]["content"]
    assert "周报" in user
    assert "报警总数" in user
    assert "高频报警点" in user
    assert "无效报警比例" in user


def test_monthly_kind_in_payload() -> None:
    agg = _agg(kind="monthly")
    user = build_period_summary_messages(agg)[1]["content"]
    assert "月报" in user


async def test_period_summary_retries_on_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """周期汇总 AI 限流抖动：失败后退避重试，第二次成功不返回 None。"""
    import asyncio as _asyncio

    from datetime import date

    from app.modules.safety.service.central_alarm.analyst import CentralAlarmAnalyst
    from app.modules.safety.service.central_alarm import analyst as ca_analyst

    class _FlakyAI:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_parsed(self, **kw: object) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("rate limited")
            return {"summary": "ok", "key_issues": [], "improvement_suggestions": []}

    async def _no_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(ca_analyst.asyncio, "sleep", _no_sleep)
    analyst = CentralAlarmAnalyst(None, ai_service=_FlakyAI())
    agg = _agg()
    out = await analyst.analyze_period_summary(agg, channel="test")
    assert out is not None and out["summary"] == "ok"


async def test_period_summary_gives_up_after_three_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连续失败 3 次后放弃，返回 None（报告降级纯数据版）。"""
    from app.modules.safety.service.central_alarm.analyst import CentralAlarmAnalyst
    from app.modules.safety.service.central_alarm import analyst as ca_analyst

    class _DeadAI:
        async def chat_parsed(self, **kw: object) -> dict[str, object]:
            raise RuntimeError("down")

    async def _no_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(ca_analyst.asyncio, "sleep", _no_sleep)
    analyst = CentralAlarmAnalyst(None, ai_service=_DeadAI())
    out = await analyst.analyze_period_summary(_agg(), channel="test")
    assert out is None
