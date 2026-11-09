"""T03 · F2：队列饥饿修复（S6 接缝）。

覆盖：
- ``bitable_repo.search_pending_ai`` 的 ``keep`` 异步谓词：全量取数后按记录顺序
  逐条过滤、凑满 ``batch_limit`` 即停；``keep=None`` 保持原切片语义（向后兼容）；
- 死信数 > batch_limit 时新记录仍被处理（F2-1）；
- 正常路径语义不变：仍取前 batch_limit 条、每轮处理数不变（F2-2）；
- ``run_ai_analysis_round`` 预过滤：退避/死信计入 deferred、日志计数、
  死信高水位 warning；``_worker`` 内 should_retry 复检保留（TOCTOU 安全网）。

全部 fake（Bitable client / _identify_one / 写回 / 账本 / 告警），不连真实网络/Bitable。
假件（_RoundEnv/_FakeLedger/_wire_round）沿用 test_hazard_quality_gate.py 先例并复制，改契约时三处同步。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.modules.safety.service.hazard_direct import (
    ai_analysis,
    bitable_repo,
)
from app.modules.safety.service.hazard_direct import config as hazard_config

GOOD_BASIS = "《危险化学品安全管理条例》第二十条（GB 30871-2022 第5.1条）"

BATCH_LIMIT = 200

AI_LOGGER_NAME = "app.modules.safety.service.hazard_direct.ai_analysis"


@pytest.fixture
def ai_log_capture(caplog: pytest.LogCaptureFixture) -> Any:
    """捕获 ai_analysis 日志的 caplog。

    应用 logger ``app.modules.safety`` 在 import app.main 时被配置为
    ``propagate=False``（记录不到达 root，caplog 默认挂 root 会漏采）；
    这里把 caplog 的 handler 直接挂到 ai_analysis logger，测试后移除。
    """
    logger = logging.getLogger(AI_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=AI_LOGGER_NAME)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)



@pytest.fixture(autouse=True)
def _fixed_batch_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hazard_config, "batch_limit", lambda: BATCH_LIMIT)


# ═══════════════════════════════════════════════════════════════
# 假件
# ═══════════════════════════════════════════════════════════════


def _raw_record(record_id: str) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "fields": {
            "隐患编号": "HZ-20261105-001",
            "隐患描述": "3号罐区静电跨接断裂",
            "检查日期": 1762300800000,
            "检查人员": [{"id": "u1", "name": "张三"}],
            "整改责任人.部门": ["储运部"],
        },
    }


def _identified_output() -> dict[str, Any]:
    return {
        "key_defect": "3号罐区静电跨接断裂",
        "hazard_type": "unsafe_condition",
        "hazard_category": "lightning_antistatic",
        "hazard_level": "general",
        "major_hazard_basis": GOOD_BASIS,
        "defect_substance": "substantive",
        "defect_substance_reasoning": "跨接断裂导致静电无法导除",
        "rectification_suggestion": {"corrective": "重新安装跨接线", "preventive": "纳入巡检"},
    }


class _ListClient:
    """list_all_records 桩 client（记录调用参数 + 返回固定记录）。"""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[dict[str, Any]] = []

    async def list_all_records(
        self,
        *,
        filter_info: Any = None,
        page_size: int | None = None,
        strict: bool | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {"filter_info": filter_info, "page_size": page_size, "strict": strict}
        )
        return list(self.records)


class _QueueLedger:
    """ai_analysis.failure_ledger 替身：支持 retry_status 预过滤 + TOCTOU 复检。"""

    def __init__(
        self,
        *,
        dead_ids: set[str] | None = None,
        backoff_ids: set[str] | None = None,
        should_retry_result: bool = True,
    ) -> None:
        self.dead_ids = dead_ids or set()
        self.backoff_ids = backoff_ids or set()
        self.should_retry_result = should_retry_result
        self.round_seq = 7
        self.retry_status_calls: list[str] = []
        self.should_retry_calls: list[str] = []
        self.success_ids: list[str] = []
        self.failure_calls: list[tuple[str, int, str, str]] = []
        self.infra_alert_calls: list[tuple[int, int, str]] = []

    async def next_round_seq(self) -> int:
        return self.round_seq

    async def retry_status(self, record_id: str, round_seq: int) -> str:
        self.retry_status_calls.append(record_id)
        if record_id in self.dead_ids:
            return "dead"
        if record_id in self.backoff_ids:
            return "backoff"
        return "ok"

    async def should_retry(self, record_id: str, round_seq: int) -> bool:
        self.should_retry_calls.append(record_id)
        return self.should_retry_result

    async def record_failure(
        self, record_id: str, round_seq: int, category: str, reason: str
    ) -> Any:
        self.failure_calls.append((record_id, round_seq, category, reason))
        raise AssertionError("本文件正常路径/预过滤不应触发 record_failure")

    async def record_success(self, record_id: str) -> None:
        self.success_ids.append(record_id)

    async def list_dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    async def should_emit_infra_alert(
        self,
        round_seq: int,
        interval_seconds: int = 1800,
        *,
        key: str = "",
    ) -> bool:
        self.infra_alert_calls.append((round_seq, interval_seconds, key))
        return True


class _RoundEnv:
    def __init__(self, *, client: _ListClient, ledger: _QueueLedger) -> None:
        self.client = client
        self.ledger = ledger
        self.identified: list[str] = []
        self.written: list[str] = []


async def _wire_round(
    monkeypatch: pytest.MonkeyPatch, env: _RoundEnv
) -> None:
    """真取数（不 monkeypatch search_pending_ai，只换 client 与外部依赖）。"""
    import app.modules.safety.feishu.bitable_client as bitable_client

    monkeypatch.setattr(
        bitable_client, "SafetyBitableClient", lambda *a, **k: env.client
    )

    @asynccontextmanager
    async def fake_record_lock(record_id: str) -> Any:
        yield True

    monkeypatch.setattr(bitable_repo, "record_lock", fake_record_lock)

    async def fake_identify_one(
        client: Any, view: Any, *, round_id: str | None = None
    ) -> dict[str, Any]:
        env.identified.append(view.record_id)
        return _identified_output()

    monkeypatch.setattr(ai_analysis, "_identify_one", fake_identify_one)
    monkeypatch.setattr(ai_analysis, "_supervision_label", lambda view: None)

    async def fake_write_ai_analysis(
        client: Any,
        record_id: str,
        *,
        hazard_no: str | None,
        output: dict[str, Any],
        supervision_label: str | None = None,
        snapshot_fields: dict[str, Any] | None = None,
    ) -> bool:
        env.written.append(record_id)
        return True

    monkeypatch.setattr(bitable_repo, "write_ai_analysis", fake_write_ai_analysis)
    monkeypatch.setattr(ai_analysis, "failure_ledger", env.ledger)

    async def fake_notify_failures(*args: Any, **kwargs: Any) -> bool:
        return True

    async def fake_notify_admin(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(ai_analysis, "notify_failures", fake_notify_failures)
    monkeypatch.setattr(ai_analysis, "notify_admin", fake_notify_admin)


# ═══════════════════════════════════════════════════════════════
# S6 · bitable_repo.search_pending_ai（直接接缝）
# ═══════════════════════════════════════════════════════════════


class TestSearchPendingAiKeep:
    async def test_keep_none_returns_first_batch_limit(self) -> None:
        """向后兼容：keep=None → 原切片冒烟（其它调用方/测试依赖）。"""
        client: Any = _ListClient([_raw_record(f"rec-{i:03d}") for i in range(300)])

        records = await bitable_repo.search_pending_ai(client)

        assert len(records) == BATCH_LIMIT
        assert [item["record_id"] for item in records[:3]] == [
            "rec-000",
            "rec-001",
            "rec-002",
        ]
        # 仍是一次全量取数（现状即全量，无额外 Bitable API 成本）
        assert len(client.calls) == 1
        assert client.calls[0]["page_size"] == 500
        assert client.calls[0]["strict"] is True
        assert client.calls[0]["filter_info"] is not None

    async def test_keep_none_explicit_limit_slices(self) -> None:
        client: Any = _ListClient([_raw_record(f"rec-{i:03d}") for i in range(300)])

        records = await bitable_repo.search_pending_ai(client, limit=5)

        assert [item["record_id"] for item in records] == [
            f"rec-{i:03d}" for i in range(5)
        ]

    async def test_dead_letters_exceeding_batch_limit_do_not_starve_new_records(
        self,
    ) -> None:
        """F2-1：250 条死信（>batch_limit=200）在前，新记录仍被收集处理。"""
        dead = [_raw_record(f"dead-{i:03d}") for i in range(250)]
        new = [_raw_record(f"new-{i:03d}") for i in range(50)]
        client: Any = _ListClient(dead + new)

        async def keep(record: dict[str, Any]) -> bool:
            return not record["record_id"].startswith("dead-")

        records = await bitable_repo.search_pending_ai(client, keep=keep)

        assert [item["record_id"] for item in records] == [
            f"new-{i:03d}" for i in range(50)
        ]

    async def test_keep_stops_once_capacity_filled(self) -> None:
        """凑满 batch_limit 即停：不额外评估剩余记录（每轮 Redis GET 有界）。"""
        client: Any = _ListClient([_raw_record(f"rec-{i:03d}") for i in range(300)])
        evaluated: list[str] = []

        async def keep(record: dict[str, Any]) -> bool:
            evaluated.append(record["record_id"])
            return True

        records = await bitable_repo.search_pending_ai(client, keep=keep)

        assert len(records) == BATCH_LIMIT
        assert len(evaluated) == BATCH_LIMIT  # 未评估第 201 条之后的记录
        assert evaluated[-1] == f"rec-{BATCH_LIMIT - 1:03d}"

    async def test_keep_with_explicit_limit_capacity(self) -> None:
        client: Any = _ListClient([_raw_record(f"rec-{i:03d}") for i in range(300)])

        async def keep(record: dict[str, Any]) -> bool:
            return True

        records = await bitable_repo.search_pending_ai(client, limit=3, keep=keep)

        assert [item["record_id"] for item in records] == ["rec-000", "rec-001", "rec-002"]

    async def test_keep_filters_without_pre_truncation(self) -> None:
        """先截断再过滤的旧行为会漏掉第 200 条之后的可执行记录（回归钉住）。"""
        dead = [_raw_record(f"dead-{i:03d}") for i in range(BATCH_LIMIT)]
        new = [_raw_record("new-tail")]
        client: Any = _ListClient(dead + new)

        async def keep(record: dict[str, Any]) -> bool:
            return str(record["record_id"]) == "new-tail"

        records = await bitable_repo.search_pending_ai(client, keep=keep)

        assert [item["record_id"] for item in records] == ["new-tail"]


# ═══════════════════════════════════════════════════════════════
# S6 · run_ai_analysis_round 预过滤（轮级）
# ═══════════════════════════════════════════════════════════════


class TestRoundPrefilter:
    async def test_dead_letters_do_not_starve_new_records_and_log_high_watermark(
        self, monkeypatch: pytest.MonkeyPatch, ai_log_capture: Any
    ) -> None:
        dead_records = [_raw_record(f"dead-{i:03d}") for i in range(250)]
        new_records = [_raw_record(f"new-{i:03d}") for i in range(50)]
        env = _RoundEnv(
            client=_ListClient(dead_records + new_records),
            ledger=_QueueLedger(dead_ids={item["record_id"] for item in dead_records}),
        )
        await _wire_round(monkeypatch, env)

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        # 只处理可执行的 50 条新记录；250 条死信不占窗口、不调 AI
        assert result.total == 50
        assert result.succeeded == 50
        assert result.failed == 0
        assert result.deferred == 250
        assert sorted(env.identified) == [f"new-{i:03d}" for i in range(50)]
        assert len(env.written) == 50
        assert env.ledger.failure_calls == []

        messages = [record.getMessage() for record in ai_log_capture.records]
        assert any("取数预过滤" in msg for msg in messages)
        prefilter = next(msg for msg in messages if "取数预过滤" in msg)
        assert "可执行=50" in prefilter
        assert "退避中=0" in prefilter
        assert "死信=250" in prefilter
        assert "窗口=200" in prefilter
        warnings = [
            record.getMessage()
            for record in ai_log_capture.records
            if record.levelno >= logging.WARNING
        ]
        assert any("队列高水位" in msg for msg in warnings)

    async def test_normal_path_semantics_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, ai_log_capture: Any
    ) -> None:
        """F2-2：无死信/退避 → 仍取前 batch_limit 条、每轮处理数不变。"""
        all_records = [_raw_record(f"rec-{i:03d}") for i in range(300)]
        env = _RoundEnv(
            client=_ListClient(all_records),
            ledger=_QueueLedger(),
        )
        await _wire_round(monkeypatch, env)

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        assert result.total == BATCH_LIMIT  # 前 200 条
        assert result.succeeded == BATCH_LIMIT
        assert result.deferred == 0
        assert result.failed == 0
        assert env.identified == [f"rec-{i:03d}" for i in range(BATCH_LIMIT)]
        # 预过滤只评估窗口内的 200 条（死信/退避不占窗口的代价有界）
        assert len(env.ledger.retry_status_calls) == BATCH_LIMIT

        prefilter = next(
            record.getMessage()
            for record in ai_log_capture.records
            if "取数预过滤" in record.getMessage()
        )
        assert "可执行=200" in prefilter
        assert "退避中=0" in prefilter
        assert "死信=0" in prefilter
        assert not any(
            record.getMessage() for record in ai_log_capture.records
            if record.levelno >= logging.WARNING and "队列高水位" in record.getMessage()
        )

    async def test_backoff_records_count_as_deferred_not_failure(
        self, monkeypatch: pytest.MonkeyPatch, ai_log_capture: Any
    ) -> None:
        backoff_records = [_raw_record(f"backoff-{i:02d}") for i in range(10)]
        ok_records = [_raw_record(f"ok-{i:02d}") for i in range(5)]
        env = _RoundEnv(
            client=_ListClient(backoff_records + ok_records),
            ledger=_QueueLedger(
                backoff_ids={item["record_id"] for item in backoff_records}
            ),
        )
        await _wire_round(monkeypatch, env)

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        assert result.total == 5
        assert result.succeeded == 5
        assert result.failed == 0
        assert result.deferred == 10
        assert sorted(env.identified) == [f"ok-{i:02d}" for i in range(5)]
        prefilter = next(
            record.getMessage()
            for record in ai_log_capture.records
            if "取数预过滤" in record.getMessage()
        )
        assert "可执行=5" in prefilter
        assert "退避中=10" in prefilter

    async def test_worker_should_retry_recheck_keeps_toctou_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """预过滤放行但 worker 复检拒绝（TOCTOU）→ deferred，不调 AI。"""
        env = _RoundEnv(
            client=_ListClient([_raw_record("rec-1")]),
            ledger=_QueueLedger(should_retry_result=False),
        )
        await _wire_round(monkeypatch, env)

        result = await ai_analysis.run_ai_analysis_round(notify=False)

        assert result.total == 1
        assert result.deferred == 1
        assert result.failed == 0
        assert env.identified == []
        assert env.ledger.should_retry_calls == ["rec-1"]
