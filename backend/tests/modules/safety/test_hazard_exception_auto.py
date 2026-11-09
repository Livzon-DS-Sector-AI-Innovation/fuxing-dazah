"""P2-1 T2 —— auto 模式分级处置：mode 开关 + ``auto_writeback_pass`` 分级 +
定时/入口集成。observe 档行为与 P1-3 逐字节一致（零写、返回体不变）。

分级拍板（Q2C，2026-11-09）：
- direct：action=adopt_ai 且 effective_rescued 且 level∈{general,serious}
  （**serious 同 general 直写**——§4.4 人工确认仅针对重大隐患=major）；
- confirm：action=escalate 或（action=adopt_ai 且 level=major）→ pending_confirm；
- skip：其余（keep_manual/insufficient/adopt_ai 未 rescued/人工 useless 改判）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from app.modules.safety.service.hazard_direct import exception_reviewer
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    REVIEWS_KEY,
    ExceptionReviewReport,
    ProposedAction,
    ReviewDeps,
)
from app.modules.safety.service.hazard_direct.exception_writeback import (
    WB_PENDING_CONFIRM,
    WB_SUCCESS,
    auto_writeback_pass,
    classify_writeback_action,
)
from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis
from tests.modules.safety.test_hazard_exception_reviewer_runner import (
    FakeRecordReader,
    FakeSearcher,
    _stub_audit_session,  # noqa: F401 — autouse 语义明确借用（防真写库）
)
from tests.modules.safety.test_hazard_exception_writeback import (
    FakeReader,
    FakeWriter,
)
from tests.modules.safety.test_hazard_exception_writeback import (
    _report as _wb_report,
)


class _NoopAuditFactory:  # pragma: no cover - 兜底（import 失败时独立定义）
    pass


# ── 分级判定（纯函数）───────────────────────────────────────────────────────


def test_classify_direct_general_and_serious() -> None:
    assert classify_writeback_action(_wb_report(level="general")) == "direct"
    # Q2C 歧义消解钉死：serious 同 general 直写
    assert classify_writeback_action(_wb_report(level="serious")) == "direct"


def test_classify_confirm_major_and_escalate() -> None:
    assert classify_writeback_action(_wb_report(level="major")) == "confirm"
    escalate = _wb_report()
    escalate.proposed_action = ProposedAction.ESCALATE
    assert classify_writeback_action(escalate) == "confirm"


def test_classify_skip_matrix() -> None:
    keep = _wb_report()
    keep.proposed_action = ProposedAction.KEEP_MANUAL
    assert classify_writeback_action(keep) == "skip"
    insufficient = _wb_report()
    insufficient.proposed_action = ProposedAction.INSUFFICIENT
    assert classify_writeback_action(insufficient) == "skip"
    assert classify_writeback_action(_wb_report(rescued=False)) == "skip"
    useless = _wb_report()
    useless.human_feedback = "useless"  # 人工改判否决 → 不自动写
    assert classify_writeback_action(useless) == "skip"


# ── mode 开关（config + registry）──────────────────────────────────────────


def test_review_mode_default_observe(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety.app_config.store import store as app_config_store
    from app.modules.safety.service.hazard_direct import config as hazard_config

    monkeypatch.delenv("SAFETY_HAZARD_REVIEW_MODE", raising=False)
    monkeypatch.setattr(app_config_store, "_fetch_rows", lambda: {})
    app_config_store.invalidate()
    assert hazard_config.review_mode() == "observe"


def test_review_mode_env_auto_and_invalid_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.app_config.store import store as app_config_store
    from app.modules.safety.service.hazard_direct import config as hazard_config

    monkeypatch.setattr(app_config_store, "_fetch_rows", lambda: {})
    app_config_store.invalidate()
    monkeypatch.setenv("SAFETY_HAZARD_REVIEW_MODE", "auto")
    assert hazard_config.review_mode() == "auto"
    monkeypatch.setenv("SAFETY_HAZARD_REVIEW_MODE", "yolo")  # 非法值回落 observe
    assert hazard_config.review_mode() == "observe"


def test_review_mode_key_registered() -> None:
    from app.modules.safety.app_config import registry

    item = registry.get_item("SAFETY_HAZARD_REVIEW_MODE")
    assert item.type == "str"
    assert item.default == "observe"


# ── auto_writeback_pass（全 fake）───────────────────────────────────────────


async def test_auto_pass_direct_writes_general_and_serious() -> None:
    writer = FakeWriter(ok=True)
    reports = [_wb_report(record_id="recG", level="general"),
               _wb_report(record_id="recS", level="serious")]
    counts = await auto_writeback_pass(
        reports, reader=FakeReader(), writer=writer, redis=FakeRedis()
    )
    assert counts == {"success": 2, "failed": 0, "pending_confirm": 0, "skipped": 0}
    assert {rid for rid, _ in writer.calls} == {"recG", "recS"}
    assert all(r.writeback == WB_SUCCESS for r in reports)


async def test_auto_pass_major_and_escalate_pending_confirm_zero_write() -> None:
    writer = FakeWriter()
    major = _wb_report(record_id="recM", level="major")
    escalate = _wb_report(record_id="recE")
    escalate.proposed_action = ProposedAction.ESCALATE
    counts = await auto_writeback_pass(
        [major, escalate], reader=FakeReader(), writer=writer, redis=FakeRedis()
    )
    assert counts["pending_confirm"] == 2
    assert counts["success"] == 0
    assert writer.calls == []
    assert major.writeback == WB_PENDING_CONFIRM
    assert escalate.writeback == WB_PENDING_CONFIRM


async def test_auto_pass_skips_not_adopt_ai_and_unrescued() -> None:
    writer = FakeWriter()
    keep = _wb_report(record_id="recK")
    keep.proposed_action = ProposedAction.KEEP_MANUAL
    unrescued = _wb_report(record_id="recU", rescued=False)
    counts = await auto_writeback_pass(
        [keep, unrescued], reader=FakeReader(), writer=writer, redis=FakeRedis()
    )
    assert counts["skipped"] == 2
    assert writer.calls == []
    assert keep.writeback == "not_attempted"
    assert unrescued.writeback == "not_attempted"


# ── run_exception_review 集成（observe 零写 / auto 直写）──────────────────


def _auto_model() -> Any:
    """先调一次检索工具（积累可验证证据）→ 再产出 general+adopt_ai 结论。"""
    from pydantic_ai.messages import ToolCallPart

    state = {"searched": False}

    async def _fn(messages: list[Any], info: Any) -> ModelResponse:
        if not state["searched"]:
            state["searched"] = True
            return ModelResponse(
                parts=[ToolCallPart(tool_name="search_regulations", args={"query": "防护栏杆"})]
            )
        return ModelResponse(
            parts=[
                TextPart(
                    content=json.dumps(
                        {
                            "classification": "unsafe_condition",
                            "hazard_level": "general",
                            "major_hazard_basis": "《消防法》第10条：'应设置防护栏杆'",
                            "rectification_suggestion": "补装防护栏杆",
                            "proposed_action": "adopt_ai",
                            "note": "",
                        },
                        ensure_ascii=False,
                    )
                )
            ]
        )

    return FunctionModel(_fn)


def _auto_deps(
    redis: FakeRedis,
    writer: FakeWriter,
    *,
    mode: str = "auto",
    reader: FakeRecordReader | None = None,
) -> ReviewDeps:
    return ReviewDeps(
        reader=reader or FakeRecordReader(
            fields={
                "recDead1": {
                    "隐患描述": "栏杆缺失",
                    "隐患级别（AI）": None,
                    "隐患分类（AI）": None,
                    "隐患类别（AI）": None,
                    "隐患描述（AI）": None,
                    "隐患判定依据（AI）": None,
                    "整改建议（AI）": None,
                }
            }
        ),
        searcher=FakeSearcher(),
        model_factory=_auto_model,
        redis=redis,
        mode=mode,
        writer=writer,
    )


async def test_run_exception_review_auto_writes_general() -> None:
    redis = FakeRedis()
    writer = FakeWriter(ok=True)
    deps = _auto_deps(redis, writer)
    item = exception_reviewer.ExceptionItem(
        record_id="recDead1",
        source="dead_letter",
        category="json_invalid",
        reason="视觉输出持续非法",
        attempts=3,
        label=exception_reviewer.ExceptionLabel.JSON_INVALID,
    )
    result = await exception_reviewer.run_exception_review([item], deps=deps)
    assert result.reviewed == 1
    assert result.writeback_success == 1
    assert len(writer.calls) == 1
    rid, fields = writer.calls[0]
    assert rid == "recDead1"
    assert fields["隐患级别（AI）"] == "一般隐患"
    # 报告状态回写 Redis
    persisted = ExceptionReviewReport.model_validate_json(
        redis.store[REVIEWS_KEY]["recDead1"]
    )
    assert persisted.writeback == WB_SUCCESS


async def test_run_exception_review_observe_zero_write_unchanged() -> None:
    """observe 档：auto 分支整体跳过——零写、计数零、报告 not_attempted。"""
    redis = FakeRedis()
    writer = FakeWriter()
    deps = _auto_deps(redis, writer, mode="observe")
    item = exception_reviewer.ExceptionItem(
        record_id="recDead1",
        source="dead_letter",
        category="json_invalid",
        reason="视觉输出持续非法",
        attempts=3,
        label=exception_reviewer.ExceptionLabel.JSON_INVALID,
    )
    result = await exception_reviewer.run_exception_review([item], deps=deps)
    assert result.reviewed == 1
    assert result.writeback_success == 0
    assert result.pending_confirm == 0
    assert writer.calls == []
    persisted = ExceptionReviewReport.model_validate_json(
        redis.store[REVIEWS_KEY]["recDead1"]
    )
    assert persisted.writeback == "not_attempted"


async def test_run_exception_review_invalid_mode_falls_back_observe() -> None:
    """mode 非法值（注入侧）按 observe 处理——不写。"""
    writer = FakeWriter()
    deps = _auto_deps(FakeRedis(), writer, mode="yolo")
    item = exception_reviewer.ExceptionItem(
        record_id="recDead1",
        source="dead_letter",
        category="json_invalid",
        reason="x",
        attempts=1,
        label=exception_reviewer.ExceptionLabel.JSON_INVALID,
    )
    result = await exception_reviewer.run_exception_review([item], deps=deps)
    assert writer.calls == []
    assert result.writeback_success == 0


# ── 定时任务与入口工具（auto 标注/返回体）─────────────────────────────────


async def test_run_scheduled_review_auto_annotates_pending_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    redis.store["safety:hazard:ai:dead_letters"] = {
        "recDead1": json.dumps({"record_id": "recDead1", "dead": True})
    }
    writer = FakeWriter()
    sent: dict[str, Any] = {}

    async def fake_card(chat_id: str, result: Any) -> str:
        sent["chat_id"] = chat_id
        sent["summary"] = result
        return "om_fake"

    monkeypatch.setattr(exception_reviewer, "review_redis_client", lambda: redis)

    def _fake_builder(db: Any = None) -> ReviewDeps:
        return _auto_deps(redis, writer)

    import app.modules.safety.feishu.exception_review_card as erc

    monkeypatch.setattr(erc, "send_review_summary_card", fake_card)
    # scheduled 内部以模块属性引用 build_default_review_deps
    monkeypatch.setattr(exception_reviewer, "build_default_review_deps", _fake_builder)
    monkeypatch.setattr(exception_reviewer, "run_exception_review", _fake_runner())

    out = await exception_reviewer.run_scheduled_review("oc_test")
    assert out["reviewed"] == 2
    assert out["writeback_success"] == 1
    assert out["pending_confirm"] == 1
    assert sent["chat_id"] == "oc_test"


def _fake_runner() -> Any:
    """run_exception_review 替身：产一条 success + 一条 pending_confirm。"""
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        ReviewRunResult,
    )

    async def _run(items: list[Any], *, deps: Any) -> Any:
        result = ReviewRunResult()
        result.reviewed = 2
        result.rescued = 2
        result.writeback_success = 1
        result.pending_confirm = 1
        result.reports = [_wb_report(record_id="recA"), _wb_report(record_id="recB", level="major")]
        return result

    return _run


async def test_summary_card_auto_annotation_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto 批汇总卡含 待人工确认 标注（Q2C：定时路径 major/escalate 只标注）。"""
    import app.modules.safety.feishu.exception_review_card as erc
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        ReviewRunResult,
    )

    captured: dict[str, str] = {}

    async def fake_send(chat_id: str, title: str, content: str, **kw: Any) -> str:
        captured["content"] = content
        captured["title"] = title
        return "om_x"

    async def fake_raw(chat_id: str, card: Any) -> str | None:
        captured["result_card"] = str(card)
        return "om_r"

    monkeypatch.setattr(erc, "send_group_card", fake_send)
    monkeypatch.setattr(erc, "_send_card_raw", fake_raw)
    result = ReviewRunResult()
    result.reviewed = 2
    result.rescued = 1
    result.writeback_success = 1
    result.pending_confirm = 1
    message_id = await erc.send_review_summary_card("oc_t", result)
    assert message_id == "om_x"
    assert "待人工确认" in captured["content"]
    assert "写回成功" in captured["content"]
    assert captured["title"] == "例外复核汇总 — auto"
    assert "auto 写回结果" in captured["result_card"]


async def test_summary_card_observe_unchanged_when_no_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """observe 批（计数全零）汇总文案与 P1-3 一致——不含 auto 标注行。"""
    import app.modules.safety.feishu.exception_review_card as erc
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        ReviewRunResult,
    )

    captured: dict[str, str] = {}

    async def fake_send(chat_id: str, title: str, content: str, **kw: Any) -> str:
        captured["content"] = content
        captured["title"] = title
        return "om_x"

    monkeypatch.setattr(erc, "send_group_card", fake_send)
    result = ReviewRunResult()
    result.reviewed = 3
    message_id = await erc.send_review_summary_card("oc_t", result)
    assert message_id == "om_x"
    assert captured["title"] == "例外复核汇总 — observe"
    assert "写回成功" not in captured["content"]
    assert "待人工确认" not in captured["content"]
