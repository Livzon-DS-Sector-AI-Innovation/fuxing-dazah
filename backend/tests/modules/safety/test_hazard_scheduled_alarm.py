"""T02 · F3：调度器告警收敛（S7 接缝）。

覆盖 ``scheduled._hazard_single_round``：
- RAG 降级 7 轮（failed=N、infra_failed=N）→ 不触发 ``notify_rounds_exceeded``，
  连续失败计数保持 0（infra-only 轮不计入、按「连续」语义清零）；
- 混合轮（infra + record-level）→ 按 ``non_infra_failed`` 累计，连续 3 轮告警一次；
- ②③④⑤ 老结果类型（无 ``non_infra_failed``）→ 回退 ``failed``，原语义不变；
- 单轮异常分支不变（异常轮仍计一次连续失败）。

手法复用 test_safety_scheduled_bridge.py::_reset_round_state（新文件，不改 WIP 测试）。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.hazard_direct.round_result import RoundResult


def _reset_round_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """重置进程级轮询状态（同 test_safety_scheduled_bridge.py 手法）。"""
    from app.modules.safety import scheduled as sched

    monkeypatch.setattr(sched, "_RUNNING", set())
    monkeypatch.setattr(sched, "_CONSECUTIVE_FAILURES", {})
    # 错开判定：视为启动已久（错开已过）
    monkeypatch.setattr(sched, "_STARTED_AT", time.monotonic() - 10_000)
    return sched


def _capture_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, int, str]]:
    """捕获 notify_rounds_exceeded 调用（label, rounds, error）。"""
    from app.modules.safety.service.hazard_direct import alert

    alerts: list[tuple[str, int, str]] = []

    async def fake_notify(label: str, rounds: int, error: str = "") -> bool:
        alerts.append((label, rounds, error))
        return True

    monkeypatch.setattr(alert, "notify_rounds_exceeded", fake_notify)
    return alerts


def _run_rounds(sched: Any, round_fn: Any, rounds: int) -> None:
    async def scenario() -> None:
        for _ in range(rounds):
            await sched._hazard_single_round(
                "ai", "隐患AI分析轮询", 0, lambda: True, round_fn
            )

    asyncio.run(scenario())


class TestInfraOnlyRoundsDoNotAlert:
    def test_seven_infra_only_rounds_do_not_trigger_rounds_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RAG 降级 7 轮：每轮 failed 非零但都是 infra → 不触发连续失败告警。"""
        sched = _reset_round_state(monkeypatch)
        alerts = _capture_alerts(monkeypatch)

        async def infra_round() -> RoundResult:
            return RoundResult(
                job_label="隐患AI分析轮询",
                total=5,
                failed=5,
                infra_failed=5,
                infra_failures=[
                    {
                        "record_id": f"rec-{i}",
                        "category": "retrieval_degraded",
                        "reason": "RAG 检索降级",
                    }
                    for i in range(5)
                ],
            )

        _run_rounds(sched, infra_round, 7)

        assert alerts == []  # 连续失败轮数告警未触发
        assert sched._CONSECUTIVE_FAILURES.get("ai", 0) == 0

    def test_infra_only_round_resets_consecutive_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2 轮混合失败后 1 轮 infra-only：按连续语义清零，第 3 轮混合不告警。"""
        sched = _reset_round_state(monkeypatch)
        alerts = _capture_alerts(monkeypatch)
        rounds = [
            RoundResult(job_label="x", total=2, failed=2, infra_failed=1),
            RoundResult(job_label="x", total=2, failed=2, infra_failed=1),
            RoundResult(job_label="x", total=2, failed=2, infra_failed=2),
            RoundResult(job_label="x", total=2, failed=2, infra_failed=1),
            RoundResult(job_label="x", total=2, failed=2, infra_failed=1),
        ]
        iterator = iter(rounds)

        async def round_fn() -> RoundResult:
            return next(iterator)

        _run_rounds(sched, round_fn, 5)

        assert alerts == []  # 3、4 轮只累计到 2
        assert sched._CONSECUTIVE_FAILURES["ai"] == 2


class TestMixedRoundsKeepOriginalSemantics:
    def test_mixed_rounds_count_non_infra_and_alert_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """混合轮（infra+record-level）按非 infra 失败累计，连续 3 轮告警一次。"""
        sched = _reset_round_state(monkeypatch)
        alerts = _capture_alerts(monkeypatch)

        async def mixed_round() -> RoundResult:
            return RoundResult(
                job_label="隐患AI分析轮询",
                total=4,
                failed=4,
                infra_failed=3,
                failures=[{"record_id": "rec-1", "reason": "校验失败"}],
            )

        _run_rounds(sched, mixed_round, 3)

        assert len(alerts) == 1
        label, consecutive, error = alerts[0]
        assert label == "隐患AI分析轮询"
        assert consecutive == 3
        assert "4 条失败" in error  # 失败明细仍按 failed 全量展示
        assert sched._CONSECUTIVE_FAILURES["ai"] == 0  # 告警后重置

    def test_non_infra_failure_alongside_infra_counts_each_round(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sched = _reset_round_state(monkeypatch)
        alerts = _capture_alerts(monkeypatch)

        async def mixed_round() -> RoundResult:
            return RoundResult(job_label="x", total=3, failed=3, infra_failed=2)

        _run_rounds(sched, mixed_round, 2)
        assert alerts == []
        assert sched._CONSECUTIVE_FAILURES["ai"] == 2

        _run_rounds(sched, mixed_round, 1)
        assert len(alerts) == 1
        assert alerts[0][1] == 3


class TestLegacyResultTypesFallback:
    def test_result_without_non_infra_field_falls_back_to_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """②③④⑤ 老结果类型（SimpleNamespace 无 infra 字段）→ 回退 failed。"""
        sched = _reset_round_state(monkeypatch)
        alerts = _capture_alerts(monkeypatch)

        async def legacy_round() -> SimpleNamespace:
            return SimpleNamespace(
                failed=2, failures=[{"record_id": "r1", "reason": "x"}]
            )

        _run_rounds(sched, legacy_round, 3)

        assert len(alerts) == 1
        assert alerts[0][1] == 3
        assert sched._CONSECUTIVE_FAILURES["ai"] == 0

    def test_legacy_zero_failure_round_resets_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sched = _reset_round_state(monkeypatch)
        _capture_alerts(monkeypatch)

        async def failing_round() -> SimpleNamespace:
            return SimpleNamespace(failed=1, failures=[])

        async def healthy_round() -> SimpleNamespace:
            return SimpleNamespace(failed=0, failures=[])

        _run_rounds(sched, failing_round, 2)
        assert sched._CONSECUTIVE_FAILURES["ai"] == 2
        _run_rounds(sched, healthy_round, 1)
        assert sched._CONSECUTIVE_FAILURES["ai"] == 0


class TestExceptionBranchUnchanged:
    def test_exception_rounds_still_count_toward_alert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sched = _reset_round_state(monkeypatch)
        alerts = _capture_alerts(monkeypatch)

        async def boom() -> RoundResult:
            raise RuntimeError("boom")

        _run_rounds(sched, boom, 3)

        assert len(alerts) == 1
        assert alerts[0][1] == 3
        assert "RuntimeError" in alerts[0][2]
        assert sched._CONSECUTIVE_FAILURES["ai"] == 0
