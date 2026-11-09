"""P1-3 T2 —— 例外复核五工具 + 入口工具的 business_agent 接线。

三件套断言（对齐 test_agent_action_p3_ops 模式）：
- registry.TOOL_KIND 注册（全部只读 False，observe 期无写工具）；
- tool_selector.TOOL_GROUPS hazard_review 组 + 意图关键词命中；
- permissions.check 角色矩阵（viewer 拒绝全组、manager 五工具、creator 含入口）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core import permissions
from app.modules.safety.business_agent.tools import hazard_review_tools, registry

GROUP_TOOLS = [
    "hazard_view_images",
    "hazard_search_regulations",
    "hazard_get_record_context",
    "hazard_cross_check",
    "hazard_propose_writeback",
]
ENTRY_TOOL = "review_hazard_exceptions"
ALL_TOOLS = GROUP_TOOLS + [ENTRY_TOOL]


# ── 接线三件套 ──────────────────────────────────────────────────────────────


def test_tool_kind_registered_readonly() -> None:
    for name in ALL_TOOLS:
        assert name in registry.TOOL_KIND, f"{name} 未注册 TOOL_KIND"
        assert registry.TOOL_KIND[name] is False, f"{name} 必须只读（observe）"


def test_tool_group_and_intent_keywords() -> None:
    group = tool_selector.TOOL_GROUPS.get("hazard_review")
    assert group is not None, "缺少 hazard_review 工具组"
    for name in GROUP_TOOLS + [ENTRY_TOOL]:
        assert name in group
    # 意图关键词：管理员说「复核死信/例外复核」能挂上组
    hit = any(
        "复核" in kw or "死信" in kw
        for kws in tool_selector.INTENT_KEYWORDS.values()
        for kw in kws
    )
    assert hit, "INTENT_KEYWORDS 缺少复核/死信触发词"


def test_registry_func_by_name() -> None:
    for name in ALL_TOOLS:
        assert name in registry._FUNC_BY_NAME, f"{name} 未挂载到 registry 函数表"


# ── 权限矩阵 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["creator"])
@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_creator_allowed_all(role: str, tool: str) -> None:
    assert permissions.check(role, tool) is True


@pytest.mark.parametrize("tool", GROUP_TOOLS)
def test_manager_allowed_five_tools(tool: str) -> None:
    assert permissions.check("manager", tool) is True


def test_manager_denied_entry_tool() -> None:
    """入口工具（触发 AI 复核成本）仅 creator。"""
    assert permissions.check("manager", ENTRY_TOOL) is False


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_viewer_denied_all(tool: str) -> None:
    assert permissions.check("viewer", tool) is False


# ── 工具体（fake 依赖直测）─────────────────────────────────────────────────


class _FakeCtx:
    """BA 工具层 fake ctx（SimpleNamespace 模式）。"""

    def __init__(self, role: str = "creator") -> None:
        self.deps = type("Deps", (), {"role": role, "db": None})()


async def test_propose_writeback_marks_observe_only() -> None:
    result = await hazard_review_tools.hazard_propose_writeback(
        _FakeCtx(),  # type: ignore[arg-type]
        record_id="recD1",
        proposal={"hazard_level": "major"},
    )
    assert result["observe_only"] is True
    assert result["writeback"] == "disabled"
    assert result["record_id"] == "recD1"


async def test_entry_tool_runs_review_with_fake_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """入口工具：捞取→复核→摘要（monkeypatch 依赖构建器，全 fake）。"""
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    from app.modules.safety.service.hazard_direct.exception_reviewer import ReviewDeps
    from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis
    from tests.modules.safety.test_hazard_exception_reviewer_runner import (
        FakeRecordReader,
        FakeSearcher,
    )

    async def _model(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(
            parts=[
                TextPart(
                    content=(
                        '{"classification": "unsafe_condition", "hazard_level": "general",'
                        ' "major_hazard_basis": "", "rectification_suggestion": null,'
                        ' "proposed_action": "insufficient", "note": ""}'
                    )
                )
            ]
        )

    redis = FakeRedis()
    redis.store["safety:hazard:ai:dead_letters"] = {
        "recDead1": '{"record_id": "recDead1", "attempts": 5, "last_round": 1, '
        '"next_round": null, "category": "json_invalid", "last_reason": "持续非法",'
        ' "dead": true, "dead_at": 100.0}'
    }

    def _fake_builder(db: Any = None) -> ReviewDeps:
        return ReviewDeps(
            reader=FakeRecordReader(
                fields={"recDead1": {"隐患级别": "general", "隐患描述": "x"}}
            ),
            searcher=FakeSearcher(),
            model_factory=lambda: FunctionModel(_model),
            redis=redis,
        )

    monkeypatch.setattr(hazard_review_tools, "_build_default_review_deps", _fake_builder)

    summary = await hazard_review_tools.review_hazard_exceptions(
        _FakeCtx(),  # type: ignore[arg-type]
        limit=5,
        record_ids=None,
    )
    assert summary["reviewed"] == 1
    assert summary["skipped"] == 0
    assert summary["items"][0]["record_id"] == "recDead1"
    assert summary["observe"] == "no_writeback"


async def test_entry_tool_manual_ids_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """点名 record_id → manual 捞取（无死信也能复核）。"""
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    from app.modules.safety.service.hazard_direct.exception_reviewer import ReviewDeps
    from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis
    from tests.modules.safety.test_hazard_exception_reviewer_runner import (
        FakeRecordReader,
        FakeSearcher,
    )

    async def _model(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(content='{"proposed_action": "insufficient"}')]
        )

    redis = FakeRedis()

    def _fake_builder(db: Any = None) -> ReviewDeps:
        return ReviewDeps(
            reader=FakeRecordReader(fields={"recM1": {"隐患描述": "y"}}),
            searcher=FakeSearcher(),
            model_factory=lambda: FunctionModel(_model),
            redis=redis,
        )

    monkeypatch.setattr(hazard_review_tools, "_build_default_review_deps", _fake_builder)

    summary = await hazard_review_tools.review_hazard_exceptions(
        _FakeCtx(),  # type: ignore[arg-type]
        limit=5,
        record_ids=["recM1"],
    )
    assert summary["reviewed"] == 1
    assert summary["items"][0]["record_id"] == "recM1"
    assert summary["items"][0]["source"] == "manual"


# ── 场景注册 ────────────────────────────────────────────────────────────────


def test_scenario_registered() -> None:
    from app.modules.safety.ai_config import scenario_registry

    assert "hazard_exception_review" in scenario_registry._AI_SCENARIO_FUNCTIONS


# ── 四只读工具的 BA 适配层（fake 依赖直测 + 不存在记录兜底）──────────────


class _FakeReader:
    def __init__(self, fields: dict[str, Any] | None = None) -> None:
        self.fields = fields or {"rec1": {"隐患级别": "general", "隐患描述": "x"}}

    async def get_fields(self, record_id: str) -> dict[str, Any] | None:
        return self.fields.get(record_id)

    async def defect_images(self, record_id: str) -> list[str]:
        return ["data:image/jpeg;base64,ZmFrZQ=="] if record_id in self.fields else []


class _FakeSearcher:
    async def search(self, query: str) -> list[dict[str, Any]]:
        return [
            {
                "source_doc": "消防法",
                "source_article": "第10条",
                "chunk_text": "应设置防护栏杆。",
                "chunk_id": "c1",
            }
        ]


async def test_ba_view_images_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hazard_review_tools, "_BitableRecordReader", lambda: _FakeReader()
    )
    images = await hazard_review_tools.hazard_view_images(
        _FakeCtx(), record_id="rec1"  # type: ignore[arg-type]
    )
    assert images and images[0].media_type == "image/jpeg"


async def test_ba_view_images_record_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不存在的记录：返回空列表（不炸、不触网）。"""
    monkeypatch.setattr(
        hazard_review_tools, "_BitableRecordReader", lambda: _FakeReader(fields={})
    )
    images = await hazard_review_tools.hazard_view_images(
        _FakeCtx(), record_id="recGone"  # type: ignore[arg-type]
    )
    assert images == []


async def test_ba_get_record_context_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hazard_review_tools, "_BitableRecordReader", lambda: _FakeReader()
    )
    ctx = await hazard_review_tools.hazard_get_record_context(
        _FakeCtx(), record_id="rec1"  # type: ignore[arg-type]
    )
    assert ctx["manual_conclusion"]["hazard_level"] == "general"
    # 不存在记录 → error 字段兜底（不炸）
    missing = await hazard_review_tools.hazard_get_record_context(
        _FakeCtx(), record_id="recGone"  # type: ignore[arg-type]
    )
    assert "error" in missing


async def test_ba_search_regulations_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hazard_review_tools, "_RetrieverSearcher", lambda db: _FakeSearcher()
    )
    chunks = await hazard_review_tools.hazard_search_regulations(
        _FakeCtx(), query="防护栏杆"  # type: ignore[arg-type]
    )
    assert chunks[0]["source_doc"] == "消防法"


async def test_ba_cross_check_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hazard_review_tools, "_BitableRecordReader", lambda: _FakeReader()
    )
    result = await hazard_review_tools.hazard_cross_check(
        _FakeCtx(),  # type: ignore[arg-type]
        record_id="rec1",
        ai_conclusion={"hazard_level": "major", "major_hazard_basis": "《消防法》第10条：'应设置防护栏杆'"},
        evidence=[
            {
                "source_doc": "消防法",
                "source_article": "第10条",
                "chunk_text": "应设置防护栏杆。",
                "chunk_id": "c1",
            }
        ],
    )
    by_field = {d["field"]: d for d in result["diff"]}
    assert by_field["hazard_level"]["agree"] is False
    assert result["citation_verified"] is True


# ═══════════════════════════════════════════════════════════════════════════
# P2-1 T3 —— hazard_execute_review_writeback 写工具（requires_approval 确认流）
# ═══════════════════════════════════════════════════════════════════════════

EXEC_TOOL = "hazard_execute_review_writeback"


def test_execute_writeback_tool_registered_as_write() -> None:
    assert registry.TOOL_KIND.get(EXEC_TOOL) is True, "必须是写工具（确认流）"


def test_execute_writeback_creator_only() -> None:
    assert permissions.check("creator", EXEC_TOOL) is True
    assert permissions.check("manager", EXEC_TOOL) is False, "确认人=creator（P2-1 F3）"
    assert permissions.check("viewer", EXEC_TOOL) is False


def test_execute_writeback_in_hazard_review_group() -> None:
    group = tool_selector.TOOL_GROUPS.get("hazard_review")
    assert group is not None and EXEC_TOOL in group


async def test_execute_writeback_tool_runs_with_fake_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.service.hazard_direct import exception_writeback as wb

    calls: list[str] = []

    async def fake_for_record(record_id: str, *, redis: Any = None) -> dict[str, Any]:
        calls.append(record_id)
        return {
            "record_id": record_id,
            "status": "success",
            "written_fields": ["隐患级别（AI）"],
            "note": "已写回 AI 列并清除死信",
        }

    monkeypatch.setattr(wb, "execute_writeback_for_record", fake_for_record)
    result = await hazard_review_tools.hazard_execute_review_writeback(
        _FakeCtx(),  # type: ignore[arg-type]
        record_id="recM1",
    )
    assert calls == ["recM1"]
    assert result["status"] == "success"


async def test_execute_writeback_tool_report_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.service.hazard_direct import exception_writeback as wb

    async def fake_for_record(record_id: str, *, redis: Any = None) -> dict[str, Any]:
        return {"error": f"未找到复核报告: {record_id}", "record_id": record_id}

    monkeypatch.setattr(wb, "execute_writeback_for_record", fake_for_record)
    result = await hazard_review_tools.hazard_execute_review_writeback(
        _FakeCtx(),  # type: ignore[arg-type]
        record_id="recNone",
    )
    assert "error" in result


async def test_execute_writeback_for_record_service_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务层 helper：装 Redis 报告 → execute_writeback（全 fake）。"""
    from app.modules.safety.service.hazard_direct import exception_writeback as wb
    from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis
    from tests.modules.safety.test_hazard_exception_writeback import (
        FakeReader,
        FakeWriter,
    )
    from tests.modules.safety.test_hazard_exception_writeback import (
        _report as _wb_report,
    )

    report = _wb_report(record_id="recS1")
    report.writeback = "pending_confirm"
    redis = FakeRedis()
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        REVIEWS_KEY,
    )

    redis.store[REVIEWS_KEY] = {
        "recS1": report.model_dump_json()
    }

    monkeypatch.setattr(
        "app.modules.safety.service.hazard_direct.exception_reviewer.review_redis_client",
        lambda: redis,
    )
    monkeypatch.setattr(
        wb,
        "build_default_writeback_deps",
        lambda: wb.WritebackDeps(reader=FakeReader(), writer=FakeWriter(), redis=redis),
    )
    out = await wb.execute_writeback_for_record("recS1")
    assert out["status"] == "success"
    assert "隐患判定依据（AI）" in out["written_fields"]


async def test_execute_writeback_for_record_missing_report() -> None:
    from app.modules.safety.service.hazard_direct import exception_writeback as wb
    from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis

    out = await wb.execute_writeback_for_record("rec404", redis=FakeRedis())
    assert "error" in out
    assert out["record_id"] == "rec404"


async def test_entry_tool_auto_payload_marks_auto_not_observe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto 批入口返回体：mode=auto 且不再误标 observe=no_writeback。"""
    import json as _json

    from app.modules.safety.service.hazard_direct import exception_reviewer
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        ReviewDeps,
    )
    from tests.modules.safety.test_hazard_exception_auto import _auto_model
    from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis
    from tests.modules.safety.test_hazard_exception_reviewer_runner import (
        FakeRecordReader,
        FakeSearcher,
    )
    from tests.modules.safety.test_hazard_exception_writeback import FakeWriter

    redis = FakeRedis()
    redis.store[exception_reviewer.REVIEWS_KEY] = {}
    redis.store["safety:hazard:ai:dead_letters"] = {
        "recDeadA": _json.dumps({"record_id": "recDeadA", "dead": True})
    }
    fields = {
        "隐患描述": "栏杆缺失",
        "隐患级别（AI）": None,
        "隐患分类（AI）": None,
        "隐患类别（AI）": None,
        "隐患描述（AI）": None,
        "隐患判定依据（AI）": None,
        "整改建议（AI）": None,
    }

    def _fake_builder(db: Any = None) -> ReviewDeps:
        return ReviewDeps(
            reader=FakeRecordReader(fields={"recDeadA": fields}),
            searcher=FakeSearcher(),
            model_factory=_auto_model,
            redis=redis,
            mode="auto",
            writer=FakeWriter(),
        )

    monkeypatch.setattr(hazard_review_tools, "_build_default_review_deps", _fake_builder)
    summary = await hazard_review_tools.review_hazard_exceptions(
        _FakeCtx(),  # type: ignore[arg-type]
        limit=5,
        record_ids=None,
    )
    assert summary["mode"] == "auto"
    assert "observe" not in summary
    assert summary["writeback"] == "enabled"
    assert summary["writeback_success"] == 1


def test_confirm_card_summary_restates_writeback_plan() -> None:
    """确认卡复述方案（D5/US3）：字段面+效果，不含「不写回」误标。"""
    from app.modules.safety.business_agent.executor import _format_tool_summary

    text = _format_tool_summary(
        "hazard_execute_review_writeback", {"record_id": "recM1"}
    )
    assert "recM1" in text
    assert "AI 六列" in text
    assert "人工列绝写" in text
    assert "死信" in text
    assert "新值详情见本会话复核报告卡" in text
