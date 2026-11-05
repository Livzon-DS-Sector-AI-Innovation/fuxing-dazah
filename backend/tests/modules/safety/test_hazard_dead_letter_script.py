"""T09 · F8：死信 top-N 明细日志 + 只读查询脚本（S9 接缝）。

覆盖 ticket 09 验收：
- ``failure_ledger.format_dead_letter_lines``：record_id/category/attempts/
  dead_at/last_reason 摘要、top-N 截断、空列表；
- ``run_ai_analysis_round`` 轮末 INFO 日志含死信明细（不再只有计数）；
- ``scripts/hazard_dead_letters.py``：只读、支持 --limit/--category/--json、
  空清单清晰输出、FakeRedis 注入可测、import 期不解析 Redis 客户端。

全部 fake：不连真实 Redis / AI / Bitable / 网络。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.modules.safety.service.hazard_direct import (
    ai_analysis,
    bitable_repo,
    failure_ledger,
)
from app.modules.safety.service.hazard_direct import config as hazard_config
from app.modules.safety.service.hazard_direct.failure_ledger import (
    format_dead_letter_lines,
)

GOOD_BASIS = "《危险化学品安全管理条例》第二十条（GB 30871-2022 第5.1条）"
BATCH_LIMIT = 200
AI_LOGGER_NAME = "app.modules.safety.service.hazard_direct.ai_analysis"
_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "hazard_dead_letters.py"

# list_dead_letters 的输出形态：dead_at 倒序
_DEAD_ITEMS: list[dict[str, Any]] = [
    {
        "record_id": "rec-dead-1",
        "attempts": 5,
        "category": "api_error",
        "reason": "TimeoutError: 调用超时",
        "last_round": 23,
        "dead_at": 1762300800.0,
    },
    {
        "record_id": "rec-dead-2",
        "attempts": 5,
        "category": "json_invalid",
        "reason": "持续畸形输出",
        "last_round": 24,
        "dead_at": 1762300900.0,
    },
]


# ═══════════════════════════════════════════════════════════════
# 纯函数：format_dead_letter_lines
# ═══════════════════════════════════════════════════════════════


def test_format_dead_letter_lines_summarizes_each_item() -> None:
    lines = format_dead_letter_lines(_DEAD_ITEMS, limit=10)

    assert len(lines) == 2
    first = lines[0]
    assert "rec-dead-1" in first
    assert "api_error" in first
    assert "5" in first  # attempts
    assert "TimeoutError: 调用超时" in first
    assert "1762300800" not in first  # dead_at 应格式化为可读时间


def test_format_dead_letter_lines_applies_top_n_limit() -> None:
    lines = format_dead_letter_lines(_DEAD_ITEMS, limit=1)

    assert len(lines) == 1
    assert "rec-dead-1" in lines[0]


def test_format_dead_letter_lines_empty_and_zero_limit() -> None:
    assert format_dead_letter_lines([], limit=10) == []
    assert format_dead_letter_lines(_DEAD_ITEMS, limit=0) == []
    assert format_dead_letter_lines(_DEAD_ITEMS, limit=-3) == []


def test_format_dead_letter_lines_truncates_long_reason() -> None:
    long_reason = "超时" * 100
    item = {**_DEAD_ITEMS[0], "reason": long_reason}

    line = format_dead_letter_lines([item], limit=1)[0]

    assert long_reason not in line
    assert len(line) < len(long_reason) + 80


# ═══════════════════════════════════════════════════════════════
# ① 轮末明细日志（run_ai_analysis_round）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def ai_log_capture(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """捕获 ai_analysis 日志（应用 logger propagate=False，直挂 handler）。"""
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


class _FakeClient:
    """占位 Bitable client（本用例不真的取数/写回）。"""


class _DeadLetterLedger:
    """ai_analysis.failure_ledger 替身：只关心轮末死信清单。"""

    def __init__(self, dead_letters: list[dict[str, Any]]) -> None:
        self.dead_letters = dead_letters
        self.list_calls: list[int] = []

    async def next_round_seq(self) -> int:
        return 7

    async def retry_status(self, record_id: str, round_seq: int) -> str:
        return "ok"

    async def should_retry(self, record_id: str, round_seq: int) -> bool:
        return True

    async def record_failure(self, *args: Any) -> Any:
        raise AssertionError("正常路径不应触发 record_failure")

    async def record_success(self, record_id: str) -> None:
        return None

    async def list_dead_letters(self, limit: int = 100) -> list[dict[str, Any]]:
        self.list_calls.append(limit)
        return list(self.dead_letters)

    async def should_emit_infra_alert(
        self,
        round_seq: int,
        interval_seconds: int = 1800,
        *,
        key: str = failure_ledger.INFRA_ALERT_KEY,
    ) -> bool:
        return True


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


async def test_round_end_logs_dead_letter_details(
    monkeypatch: pytest.MonkeyPatch, ai_log_capture: pytest.LogCaptureFixture
) -> None:
    """轮末日志含 record_id/category/attempts 明细，不再只有累计数量。"""
    ledger = _DeadLetterLedger(dead_letters=list(_DEAD_ITEMS))
    client = _FakeClient()

    import app.modules.safety.feishu.bitable_client as bitable_client

    monkeypatch.setattr(
        bitable_client, "SafetyBitableClient", lambda *a, **k: client
    )

    async def fake_search_pending_ai(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [_raw_record("rec-live")]

    monkeypatch.setattr(bitable_repo, "search_pending_ai", fake_search_pending_ai)

    @asynccontextmanager
    async def fake_record_lock(record_id: str) -> AsyncIterator[bool]:
        yield True

    monkeypatch.setattr(bitable_repo, "record_lock", fake_record_lock)

    async def fake_identify_one(
        client: Any, view: Any, *, round_id: str | None = None
    ) -> dict[str, Any]:
        return _identified_output()

    monkeypatch.setattr(ai_analysis, "_identify_one", fake_identify_one)
    monkeypatch.setattr(ai_analysis, "_supervision_label", lambda view: None)

    async def fake_write_ai_analysis(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(bitable_repo, "write_ai_analysis", fake_write_ai_analysis)
    monkeypatch.setattr(ai_analysis, "failure_ledger", ledger)

    async def fake_notify(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(ai_analysis, "notify_admin", fake_notify)
    monkeypatch.setattr(ai_analysis, "notify_failures", fake_notify)

    result = await ai_analysis.run_ai_analysis_round(notify=False)

    assert result.succeeded == 1
    messages = [record.getMessage() for record in ai_log_capture.records]
    details = [message for message in messages if "死信明细" in message]
    assert details, messages
    assert len(details) == len(_DEAD_ITEMS)  # 每条死信一行 INFO
    assert any(
        "rec-dead-1" in message and "api_error" in message for message in details
    )


# ═══════════════════════════════════════════════════════════════
# 只读查询脚本
# ═══════════════════════════════════════════════════════════════


class _DeadLetterRedis:
    """脚本用最小 FakeRedis：只实现 list_dead_letters 需要的 HGETALL。"""

    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = {
            record_id: json.dumps(payload, ensure_ascii=False)
            for record_id, payload in payloads.items()
        }
        self.calls: list[str] = []

    async def hgetall(self, key: str) -> dict[str, str]:
        self.calls.append(key)
        if key != failure_ledger.DEAD_LETTERS_KEY:
            return {}
        return dict(self.payloads)


def _dead_redis() -> _DeadLetterRedis:
    return _DeadLetterRedis(
        {
            item["record_id"]: {
                "record_id": item["record_id"],
                "attempts": item["attempts"],
                "category": item["category"],
                "last_reason": item["reason"],
                "last_round": item["last_round"],
                "dead_at": item["dead_at"],
            }
            for item in _DEAD_ITEMS
        }
    )


def _load_script() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"缺少脚本: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("hazard_dead_letters", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script() -> ModuleType:
    return _load_script()


def test_script_import_does_not_resolve_redis_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """脚本 import 期不得解析 Redis 客户端（无副作用、可离线单测）。"""
    monkeypatch.setitem(sys.modules, "app.core.redis", None)  # 一旦 import 即失败

    module = _load_script()

    assert callable(module.main)
    assert callable(module.fetch_dead_letters)
    assert callable(module.render_dead_letters)


def test_script_parser_supports_limit_category_json(script: ModuleType) -> None:
    args = script._build_parser().parse_args(
        ["--limit", "5", "--category", "api_error", "--json"]
    )

    assert args.limit == 5
    assert args.category == "api_error"
    assert args.json is True


async def test_fetch_dead_letters_fake_redis_and_limit(script: ModuleType) -> None:
    redis = _dead_redis()

    items = await script.fetch_dead_letters(redis=redis, limit=1)

    assert len(items) == 1
    assert items[0]["record_id"] == "rec-dead-2"  # dead_at 倒序
    assert redis.calls == [failure_ledger.DEAD_LETTERS_KEY]


async def test_fetch_dead_letters_filters_by_category(script: ModuleType) -> None:
    redis = _dead_redis()

    items = await script.fetch_dead_letters(
        redis=redis, limit=50, category="api_error"
    )

    assert [item["record_id"] for item in items] == ["rec-dead-1"]


async def test_render_dead_letters_json_and_empty(script: ModuleType) -> None:
    payload = json.loads(script.render_dead_letters(list(_DEAD_ITEMS), as_json=True))
    assert [item["record_id"] for item in payload] == ["rec-dead-1", "rec-dead-2"]

    plain = script.render_dead_letters([], as_json=False)
    assert "无死信" in plain or "为空" in plain
    detail = script.render_dead_letters(list(_DEAD_ITEMS), as_json=False)
    assert "rec-dead-1" in detail


async def test_main_prints_json_and_returns_zero(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = await script.main(["--limit", "1", "--json"], redis=_dead_redis())

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["record_id"] for item in payload] == ["rec-dead-2"]


async def test_main_empty_list_is_clear(
    script: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = await script.main([], redis=_DeadLetterRedis({}))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "无死信" in out or "为空" in out
