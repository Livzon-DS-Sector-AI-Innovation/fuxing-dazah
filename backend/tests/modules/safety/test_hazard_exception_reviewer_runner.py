"""P1-3 T2 —— 例外复核员 runner：多步补检循环 + 成本护栏 + observe 零写。

覆盖 ticket 02 验收（服务层单接缝 run_exception_review）：
- 五工具 impl（fake 依赖直测）；
- runner 产出报告落 Redis、审计行 scenario=hazard_exception_review；
- 成本护栏：单条 LLM≤3 / 工具≤8（超限截断为 insufficient 报告）、每日≤20；
- observe 零写：全链路跑完 Bitable 写 canary 零调用；模块源码无 Bitable 写调用。
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.modules.safety.service.hazard_direct import failure_ledger
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    REVIEWER_PROMPT,
    ExceptionItem,
    ExceptionReviewReport,
    ReviewBudget,
    ReviewDeps,
    ReviewerFinalOutput,
    build_proposal,
    cross_check_conclusion,
    fetch_record_context,
    run_exception_review,
    search_regulation_chunks,
)
from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis


class _NoopAuditFactory:
    """审计写入桩：记录调用、绝不触真实 DB（防测试真写 dev 库）。"""

    def __init__(self) -> None:
        self.commits = 0

    def __call__(self) -> _NoopAuditFactory:
        return self

    async def __aenter__(self) -> _NoopAuditFactory:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def add(self, row: object) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture(autouse=True)
def _stub_audit_session(monkeypatch: pytest.MonkeyPatch) -> _NoopAuditFactory:
    import app.core.database as core_db

    factory = _NoopAuditFactory()
    monkeypatch.setattr(core_db, "async_session_factory", factory)
    return factory

# ── fake 依赖 ───────────────────────────────────────────────────────────────


class FakeRecordReader:
    """记录读取假件（含 Bitable 写 canary——observe 期必须零命中）。"""

    def __init__(self, fields: dict[str, Any] | None = None) -> None:
        self.fields = fields or {}
        self.write_calls: list[str] = []
        # 任何写方法（update/create/delete）——被调用即 observe 铁律被破坏
        self.update_record = self._forbidden
        self.create_record = self._forbidden
        self.delete_record = self._forbidden

    async def _forbidden(self, *args: Any, **kwargs: Any) -> Any:
        self.write_calls.append("forbidden")
        raise AssertionError("observe 期不得写 Bitable")

    async def get_fields(self, record_id: str) -> dict[str, Any] | None:
        return self.fields.get(record_id)

    async def defect_images(self, record_id: str) -> list[str]:
        return ["data:image/jpeg;base64,ZmFrZQ=="]


class FakeSearcher:
    """法规检索假件：返回可验证 chunk（与 EvidenceEntry 字段对齐）。"""

    async def search(self, query: str) -> list[dict[str, Any]]:
        return [
            {
                "source_doc": "消防法",
                "source_article": "第10条",
                "chunk_text": "应设置防护栏杆。",
                "chunk_id": "chunk-1",
            }
        ]


def _final_output_json() -> str:
    return json.dumps(
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


def _fake_model(script: list[ModelResponse]) -> Any:
    """按脚本出牌的 fake 模型；脚本耗尽后重复最后一个响应。"""
    state = {"i": 0}

    async def _fn(messages: list[Any], info: Any) -> ModelResponse:
        idx = min(state["i"], len(script) - 1)
        state["i"] += 1
        return script[idx]

    return FunctionModel(_fn)


def _cooperative_model() -> Any:
    """先调一轮全部五工具→再产出最终结论的「好复核员」。"""

    async def _fn(messages: list[Any], info: Any) -> ModelResponse:
        last = messages[-1]
        parts = getattr(last, "parts", [])
        kinds = [getattr(p, "part_kind", "") for p in parts]
        if "tool-return" not in kinds:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="get_record_context", args={}),
                    ToolCallPart(tool_name="view_images", args={}),
                    ToolCallPart(
                        tool_name="search_regulations", args={"query": "防护栏杆 法规"}
                    ),
                ]
            )
        # 工具结果已回来：若还没交叉核对/建议，先补这两步
        called = {
            getattr(p, "tool_name", "")
            for m in messages
            for p in getattr(m, "parts", [])
            if getattr(p, "part_kind", "") == "tool-call"
        }
        if "cross_check" not in called:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="cross_check",
                        args={"ai_conclusion": {"hazard_level": "general"}},
                    ),
                    ToolCallPart(
                        tool_name="propose_writeback",
                        args={"proposal": {"hazard_level": "general"}},
                    ),
                ]
            )
        return ModelResponse(parts=[TextPart(content=_final_output_json())])

    return FunctionModel(_fn)


def _item(record_id: str = "recD1", source: str = "dead_letter") -> ExceptionItem:
    return ExceptionItem(
        record_id=record_id,
        source=source,
        category="json_invalid",
        reason="视觉输出持续非法",
        attempts=5,
        label="json_invalid",  # type: ignore[arg-type]
    )


def _deps(
    redis: FakeRedis,
    reader: FakeRecordReader | None = None,
    searcher: FakeSearcher | None = None,
    model: Any = None,
    budget: ReviewBudget | None = None,
) -> ReviewDeps:
    return ReviewDeps(
        reader=reader or FakeRecordReader(
            fields={
                "recD1": {
                    "隐患级别": "general",
                    "隐患分类": "物的因素",
                    "隐患类别": "设备设施缺陷",
                    "隐患描述": "平台无防护栏杆",
                }
            }
        ),
        searcher=searcher or FakeSearcher(),
        model_factory=lambda: model or _cooperative_model(),
        redis=redis,
        budget=budget or ReviewBudget(),
    )


# ── runner：正常路径 ────────────────────────────────────────────────────────


async def test_run_exception_review_happy_path() -> None:
    redis = FakeRedis()
    result = await run_exception_review([_item()], deps=_deps(redis))

    assert result.reviewed == 1
    assert result.skipped == 0
    report = result.reports[0]
    assert report.record_id == "recD1"
    assert report.exception_label.value == "json_invalid"
    assert report.review_source.value == "dead_letter"
    # 证据来自检索工具
    assert report.evidence and report.evidence[0].doc_name == "消防法"
    # rescued：结论非占位且引用可验证
    assert report.rescued is True
    # diff：与人工结论比对
    assert any(d.field == "hazard_level" and d.agree for d in report.diff)
    # 报告已落 Redis hash
    stored = redis.store["safety:hazard:ai:exception_reviews"]["recD1"]
    assert ExceptionReviewReport.model_validate_json(stored).record_id == "recD1"


async def test_run_exception_review_daily_budget() -> None:
    redis = FakeRedis()
    items = [_item(f"rec{i}") for i in range(25)]
    reader = FakeRecordReader(
        fields={
            f"rec{i}": {"隐患级别": "general", "隐患描述": "平台无防护栏杆"}
            for i in range(25)
        }
    )
    result = await run_exception_review(
        items, deps=_deps(redis, reader=reader, budget=ReviewBudget(daily_limit=20))
    )

    assert result.reviewed == 20
    assert result.skipped == 5
    assert result.rescued == 20


async def test_run_exception_review_llm_budget_truncates(
) -> None:
    """单条第 4 次 LLM 调用被截断 → insufficient 报告（不炸、仍留痕）。"""
    redis = FakeRedis()

    async def _chatty(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(tool_name="get_record_context", args={})]
        )

    deps = _deps(redis, model=FunctionModel(_chatty))
    result = await run_exception_review([_item()], deps=deps)

    report = result.reports[0]
    assert report.proposed_action.value == "insufficient"
    assert report.rescued is False
    assert "budget" in report.round_note
    # 截断报告也落 Redis
    assert "recD1" in redis.store["safety:hazard:ai:exception_reviews"]


async def test_run_exception_review_tool_budget_truncates(
) -> None:
    """第 9 次工具调用被截断（tool_calls_limit=8）。"""
    redis = FakeRedis()

    async def _tool_loop(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(tool_name="get_record_context", args={})]
        )

    deps = _deps(redis, model=FunctionModel(_tool_loop))
    result = await run_exception_review([_item()], deps=deps)

    assert result.reports[0].proposed_action.value == "insufficient"


async def test_run_exception_review_record_missing(
) -> None:
    """记录读取不到（Bitable 无此 record）→ insufficient 报告而非异常。"""
    redis = FakeRedis()
    deps = _deps(redis, reader=FakeRecordReader(fields={}))
    result = await run_exception_review([_item("recGone")], deps=deps)

    assert result.reviewed == 1
    assert result.reports[0].proposed_action.value == "insufficient"
    assert "not_found" in result.reports[0].round_note


# ── observe 零写断言 ────────────────────────────────────────────────────────


async def test_observe_no_bitable_write_calls() -> None:
    """全链路跑完后：reader 上的写 canary 零命中。"""
    redis = FakeRedis()
    reader = FakeRecordReader(
        fields={"recD1": {"隐患级别": "general", "隐患描述": "平台无防护栏杆"}}
    )
    await run_exception_review([_item()], deps=_deps(redis, reader=reader))

    assert reader.write_calls == []


def test_reviewer_modules_have_no_bitable_write_import() -> None:
    """静态断言：复核链路源码不含 Bitable 写调用 import。"""
    from app.modules.safety.service.hazard_direct import exception_reviewer as mod

    source = inspect.getsource(mod)
    forbidden = [
        "update_record",
        "create_record",
        "delete_record",
        "upload_drive_file",
        "RecordUpdate",
        "assert_write_allowed",
    ]
    for pattern in forbidden:
        assert pattern not in source, f"复核模块不得出现写路径符号: {pattern}"


def test_reviewer_prompt_declares_observe_mode() -> None:
    """复核员 prompt 必须写明 observe 语义（不写回/人工为准）。"""
    assert "observe" in REVIEWER_PROMPT or "不写回" in REVIEWER_PROMPT
    assert "人工" in REVIEWER_PROMPT


def test_reviewer_final_output_is_hard_schema() -> None:
    """最终输出硬 schema：枚举与必填在代码校验（硬护栏留代码）。"""
    out = ReviewerFinalOutput.model_validate(
        json.loads(_final_output_json())
    )
    assert out.major_hazard_basis.startswith("《消防法》")
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReviewerFinalOutput.model_validate({"proposed_action": "直接写回"})


# ── 五工具 impl 直测 ────────────────────────────────────────────────────────


async def test_fetch_record_context() -> None:
    redis = FakeRedis()
    _seed = {
        "record_id": "recD1",
        "attempts": 5,
        "last_round": 9,
        "next_round": None,
        "category": "json_invalid",
        "last_reason": "持续非法",
        "dead": True,
        "dead_at": 100.0,
    }
    redis.store[failure_ledger.DEAD_LETTERS_KEY] = {
        "recD1": json.dumps(_seed, ensure_ascii=False)
    }
    reader = FakeRecordReader(fields={"recD1": {"隐患级别": "general"}})

    ctx = await fetch_record_context(
        reader=reader, redis=redis, record_id="recD1"
    )

    assert ctx["record_id"] == "recD1"
    assert ctx["manual_conclusion"]["hazard_level"] == "general"
    assert ctx["failure"]["category"] == "json_invalid"
    assert ctx["ai_conclusion"] is not None or ctx["ai_conclusion"] == {}


async def test_search_regulation_chunks() -> None:
    chunks = await search_regulation_chunks(FakeSearcher(), "防护栏杆")
    assert chunks[0]["source_doc"] == "消防法"


def test_cross_check_conclusion_diff_and_agreement() -> None:
    result = cross_check_conclusion(
        ai_conclusion={"hazard_level": "major", "hazard_type": "物的因素"},
        manual_conclusion={"hazard_level": "general", "hazard_type": "物的因素"},
        evidence_entries=[
            {"source_doc": "消防法", "source_article": "第10条",
             "chunk_text": "应设置防护栏杆。", "chunk_id": "c1"}
        ],
        ai_basis="《消防法》第10条：'应设置防护栏杆'",
    )
    by_field = {d["field"]: d for d in result["diff"]}
    assert by_field["hazard_level"]["agree"] is False
    assert by_field["hazard_type"]["agree"] is True
    assert result["citation_verified"] is True


def test_build_proposal_marks_observe_only() -> None:
    proposal = build_proposal(
        "recD1", {"hazard_level": "major", "major_hazard_basis": "《消防法》第10条"}
    )
    assert proposal["observe_only"] is True
    assert proposal["writeback"] == "disabled"
    assert proposal["record_id"] == "recD1"
