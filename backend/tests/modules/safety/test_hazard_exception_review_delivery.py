"""P1-3 T3 —— observe 落点：确认卡 + 看板例外复核端点 + 定时默认关。

覆盖 ticket 03 验收：
- 卡片 payload：observe·不写回标注、按钮值结构（收到/忽略，无执行语义）；
- 卡片回调：仅改卡片状态（update_card），零写路径；
- 新端点 service+API：例外率/rescued 率/复核清单；days 校验；
  P1-4 既有 dashboard 端点行为回归不变；
- 定时任务默认关 + 任务体链路（捞死信→runner→发卡，全 fake）；
- 成本护栏上限 app_config 化（3/8/20 默认）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.safety.service.hazard_direct.exception_reviewer import (
    REVIEWS_KEY,
    ExceptionReviewReport,
    ReviewConclusion,
)


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


# ── 报告构造助手 ────────────────────────────────────────────────────────────


def _report(
    record_id: str = "recD1",
    *,
    rescued: bool = True,
    observed_at: datetime | None = None,
) -> ExceptionReviewReport:
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        ExceptionReviewReport,
    )
    return ExceptionReviewReport(
        record_id=record_id,
        exception_label="json_invalid",
        failure_category="json_invalid",
        failure_reason="视觉输出持续非法",
        review_source="dead_letter",
        evidence=[],
        ai_conclusion=ReviewConclusion(
            classification="unsafe_condition",
            hazard_level="general",
            major_hazard_basis="《消防法》第10条：'应设置防护栏杆'",
        ),
        manual_conclusion={"hazard_level": "general"},
        diff=[],
        proposed_action="adopt_ai",
        rescued=rescued,
        observed_at=observed_at or datetime.now(UTC),
    )


# ── 卡片 payload ────────────────────────────────────────────────────────────


def test_card_payload_observe_annotations() -> None:
    from app.modules.safety.feishu.exception_review_card import (
        build_exception_review_card,
    )

    card = build_exception_review_card(_report())
    text = json.dumps(card, ensure_ascii=False)
    # observe·不写回标注（标题或正文显式出现）
    assert "observe" in text and "不写回" in text
    # 按钮：收到 / 忽略（无确认执行语义）
    buttons_text = json.dumps(
        card.get("body", {}).get("elements", []), ensure_ascii=False
    )
    assert "收到" in buttons_text and "忽略" in buttons_text
    assert "确认执行" not in buttons_text


def test_card_payload_button_values_carry_scope_and_record() -> None:
    from app.modules.safety.feishu.exception_review_card import (
        build_exception_review_card,
        extract_button_values,
    )

    card = build_exception_review_card(_report("recX"))
    values = extract_button_values(card)
    assert len(values) == 2
    actions = {v.get("action") for v in values}
    assert actions == {"ack", "dismiss"}
    for value in values:
        assert value.get("scope") == "hazard_exception_review"
        assert value.get("record_id") == "recX"


async def test_card_callback_only_updates_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """回调：收到/忽略仅 PATCH 卡片终态，无任何其他副作用。"""
    from app.modules.safety.feishu import exception_review_card as erc

    calls: list[str] = []
    sent_cards: list[dict] = []

    async def fake_update(message_id: str, card: dict) -> bool:
        calls.append(message_id)
        sent_cards.append(card)
        return True

    monkeypatch.setattr(erc, "update_card", fake_update)

    handled = await erc.handle_review_card_action(
        {"action": "ack", "record_id": "recX", "scope": "hazard_exception_review"},
        {"open_message_id": "om_1"},
    )
    assert handled is True
    assert calls == ["om_1"]
    assert "已收到" in json.dumps(sent_cards[0], ensure_ascii=False)

    handled = await erc.handle_review_card_action(
        {"action": "dismiss", "record_id": "recX", "scope": "hazard_exception_review"},
        {"open_message_id": "om_2"},
    )
    assert handled is True
    assert calls == ["om_1", "om_2"]


async def test_card_callback_ignores_unknown_action() -> None:
    from app.modules.safety.feishu.exception_review_card import (
        handle_review_card_action,
    )

    handled = await handle_review_card_action(
        {"action": "write", "record_id": "recX", "scope": "hazard_exception_review"},
        {"open_message_id": "om_3"},
    )
    assert handled is False  # 未知动作（尤其任何写语义）一律不处理


# ── 看板 service：build_exception_review_dashboard ──────────────────────────


class _CountResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one_or_none(self) -> int:
        return self._value


class FakeCountDB:
    """只回答 count 查询的假 db。"""

    def __init__(self, analyzed: int) -> None:
        self.analyzed = analyzed
        self.stmts: list[Any] = []

    async def execute(self, stmt: Any) -> _CountResult:
        self.stmts.append(stmt)
        return _CountResult(self.analyzed)


class FakeReviewsRedis:
    """REVIEWS_KEY hash 假件。"""

    def __init__(self, reports: list[ExceptionReviewReport]) -> None:
        self._hash = {r.record_id: r.model_dump_json() for r in reports}

    async def hgetall(self, key: str) -> dict[str, str]:
        if key == REVIEWS_KEY:
            return dict(self._hash)
        return {}


async def test_exception_dashboard_metrics_and_items() -> None:
    from app.modules.safety.service.hazard_direct.quality_dashboard import (
        build_exception_review_dashboard,
    )

    base = datetime.now(UTC)
    reports = [
        _report("recA", rescued=True, observed_at=base),
        _report("recB", rescued=False, observed_at=base + timedelta(seconds=5)),
        # 窗口外的旧报告不计入
        ExceptionReviewReport(
            **{
                **_report("recOld").model_dump(),
                "observed_at": datetime.now(UTC) - timedelta(days=40),
            }
        ),
    ]
    data = await build_exception_review_dashboard(
        FakeCountDB(analyzed=100), days=30, redis=FakeReviewsRedis(reports)
    )
    assert data["window"]["days"] == 30
    assert data["metrics"]["reviewed"] == 2
    assert data["metrics"]["rescued"] == 1
    assert data["metrics"]["rescued_rate"] == 0.5
    assert data["metrics"]["exception_rate"] == 0.02
    # 清单按 observed_at 倒序（最新在前）
    assert [i["record_id"] for i in data["items"]] == ["recB", "recA"]


async def test_exception_dashboard_redis_failure_degrades() -> None:
    from app.modules.safety.service.hazard_direct.quality_dashboard import (
        build_exception_review_dashboard,
    )

    class BoomRedis:
        async def hgetall(self, key: str) -> dict[str, str]:
            raise ConnectionError("down")

    data = await build_exception_review_dashboard(
        FakeCountDB(analyzed=10), days=30, redis=BoomRedis()
    )
    assert data["metrics"]["reviewed"] == 0
    assert data["reviews_available"] is False


async def test_exception_reviews_endpoint_days_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.api import hazard_quality as hq_api

    async def fake_dashboard(db: Any, *, days: int = 30, redis: Any = None) -> dict:
        return {"window": {"days": days}, "metrics": {}, "items": []}

    monkeypatch.setattr(hq_api, "build_exception_review_dashboard", fake_dashboard)
    ok = await hq_api.get_exception_review_dashboard(days=30)
    assert ok.data["window"]["days"] == 30
    with pytest.raises(Exception):
        await hq_api.get_exception_review_dashboard(days=14)


async def test_p1_4_dashboard_endpoint_unchanged() -> None:
    """P1-4 既有 dashboard 端点行为回归：函数签名/返回结构不变。"""
    import inspect

    from app.modules.safety.api import hazard_quality as hq_api

    sig = inspect.signature(hq_api.get_hazard_quality_dashboard)
    assert "days" in sig.parameters
    # build_quality_dashboard 未被改名/移除
    assert hasattr(hq_api, "build_quality_dashboard")


# ── 定时任务默认关 + 任务体 ─────────────────────────────────────────────────


def test_scheduled_job_registered_default_off() -> None:
    from app.modules.safety.scheduler import SCHEDULED_JOBS

    jobs = {j["name"]: j for j in SCHEDULED_JOBS}
    job = jobs.get("隐患例外复核")
    assert job is not None, "SCHEDULED_JOBS 缺少「隐患例外复核」"
    assert job.get("enabled") is False, "默认必须关（灰度后 DB 覆写开启）"
    assert job.get("hour") == 9 and job.get("minute") == 0


async def test_scheduled_review_runs_with_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务体链路：捞死信 → runner（fake）→ 发卡（fake）。"""
    from app.modules.safety.feishu import exception_review_card as erc
    from app.modules.safety.service.hazard_direct import exception_reviewer as er

    sent: list[tuple[str, str]] = []

    async def fake_send_summary(chat_id: str, result: Any) -> str | None:
        sent.append((chat_id, f"reviewed={result.reviewed}"))
        return "om_x"

    monkeypatch.setattr(erc, "send_review_summary_card", fake_send_summary)

    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis

    redis = FakeRedis()
    redis.store["safety:hazard:ai:dead_letters"] = {
        "recDead9": '{"record_id": "recDead9", "attempts": 5, "last_round": 1, '
        '"next_round": null, "category": "json_invalid", "last_reason": "x", '
        '"dead": true, "dead_at": 100.0}'
    }

    async def _model(messages: list[Any], info: Any) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(content='{"proposed_action": "insufficient"}')]
        )

    class _Reader:
        async def get_fields(self, record_id: str) -> dict[str, Any] | None:
            return {"隐患描述": "y"}

        async def defect_images(self, record_id: str) -> list[str]:
            return []

    class _Searcher:
        async def search(self, query: str) -> list[dict[str, Any]]:
            return []

    def _fake_deps(db: Any = None) -> er.ReviewDeps:
        return er.ReviewDeps(
            reader=_Reader(),
            searcher=_Searcher(),
            model_factory=lambda: FunctionModel(_model),
            redis=redis,
        )

    monkeypatch.setattr(er, "build_default_review_deps", _fake_deps)
    monkeypatch.setattr(er, "review_redis_client", lambda: redis)

    summary = await er.run_scheduled_review(chat_id="oc_target")
    assert summary["reviewed"] == 1
    assert sent == [("oc_target", "reviewed=1")]


def test_review_budget_defaults() -> None:
    """护栏上限 app_config 化：默认 3/8/20。"""
    from app.modules.safety.service.hazard_direct import config

    budget = config.review_budget()
    assert budget.llm_call_limit == 3
    assert budget.tool_call_limit == 8
    assert budget.daily_limit == 20
