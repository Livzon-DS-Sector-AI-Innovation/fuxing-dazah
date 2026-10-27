"""整改复查（rectify）单测：比对纯函数 + RectifyChecker 全流程（Fake 注入，无 DB/网络）。

覆盖：
  - _compare_rules：昨日违规今日消除→resolved / 仍存在→未整改 / 今日新增
  - _pid_map_from_raw：正常映射 / raw_json 缺失 / 条目缺 pid
  - RectifyChecker.run：无审核记录→None / 无问题票→None / 已整改 / 未整改+新增 /
    缺 pid→uncheckable / detail 拉取失败→uncheckable
  - 落库行结构与汇总计数

时间点构造依赖 parser FIELD_MAP 的动火 fieldId，通过时间顺序/时长构造确定性违规。
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

from app.modules.safety.models import WorkTicketRectifyCheck
from app.modules.safety.workticket_review.rectify import (
    RectifyChecker,
    RuleResult,
    STATUS_RECTIFIED,
    STATUS_UNCHECKABLE,
    STATUS_UNRECTIFIED,
    _compare_rules,
    _pid_map_from_raw,
)
from app.modules.safety.workticket_review.rule_engine import RuleNo


# ── 比对纯函数 ──


def test_compare_rules_resolved() -> None:
    results = _compare_rules(
        {RuleNo.TIME_ORDER: ["申请晚于气体分析"]},
        {},
    )
    assert results == [
        RuleResult(
            rule_no=RuleNo.TIME_ORDER,
            rule_name="时间顺序链",
            yesterday_detail="申请晚于气体分析",
            resolved=True,
            today_detail=None,
        ),
    ]


def test_compare_rules_unresolved() -> None:
    results = _compare_rules(
        {RuleNo.GAS_VALIDITY: ["超 30 分钟"]},
        {RuleNo.GAS_VALIDITY: ["超 60 分钟"]},
    )
    assert len(results) == 1
    assert not results[0].resolved
    assert results[0].yesterday_detail == "超 30 分钟"
    assert results[0].today_detail == "超 60 分钟"


def test_compare_rules_new_problem() -> None:
    results = _compare_rules(
        {RuleNo.TIME_ORDER: ["倒签"]},
        {RuleNo.DURATION: ["超时"]},
    )
    assert len(results) == 2
    new = next(r for r in results if r.rule_no == RuleNo.DURATION)
    assert new.yesterday_detail is None
    assert not new.resolved
    assert new.today_detail == "超时"


def test_pid_map_from_raw_variants() -> None:
    raw = {
        "tickets": [
            {"type": "hot_work", "processInstanceId": "pi-1", "serialNumber": "DH-1"},
            {"type": "hot_work", "serialNumber": "DH-2"},  # 缺 pid
            {"type": "height_work", "processInstanceId": "pi-3",
             "variables": {"serialNumber": "GC-3"}},  # 票号在 variables
        ],
    }
    mapping = _pid_map_from_raw(raw)
    assert mapping == {"DH-1": ("hot_work", "pi-1"), "GC-3": ("height_work", "pi-3")}
    assert _pid_map_from_raw(None) == {}
    assert _pid_map_from_raw({"tickets": []}) == {}


# ── 全流程（Fake 注入）──

# 动火票 fieldId（与 parser FIELD_MAP 对齐）
_F = {
    "apply": "a165650258429577527",
    "approve": "a166419575104497385",
    "start": "a166452480843974469",
    "end": "a170041634227259322",
    "finish": "a165630881894418049",
    "level": "a165650253075756898",
    "mode": "a165630136371848108",
    "gas_array": "a172363237973025304",
    "gas_time": "a172363239131846707",
}


def _hot_variables(
    apply: str,
    gas: str,
    approve: str,
    start: str,
    end: str,
    finish: str,
    extra_gas: list[str] | None = None,
) -> dict[str, Any]:
    """动火票 variables：二级动火（72h 上限）、塑料焊接（不触发证件规则），
    时间点顺序由调用方控制以构造 TIME_ORDER / DURATION 违规。"""
    gas_rows = [{_F["gas_time"]: gas}]
    gas_rows.extend({_F["gas_time"]: t} for t in extra_gas or [])
    return {
        _F["apply"]: apply,
        _F["approve"]: approve,
        _F["start"]: start,
        _F["end"]: end,
        _F["finish"]: finish,
        _F["level"]: "2",
        f"${_F['mode']}": "塑料焊接",
        _F["gas_array"]: gas_rows,
    }


def _bad_variables() -> dict[str, Any]:
    """申请晚于气体分析（TIME_ORDER 违规），其余规则全部通过/不适用。"""
    return _hot_variables(
        apply="2026-10-20 08:30:00",
        gas="2026-10-20 08:00:00",
        approve="2026-10-20 08:10:00",
        start="2026-10-20 08:20:00",
        end="2026-10-20 10:00:00",
        finish="2026-10-20 10:30:00",
    )


def _fixed_variables() -> dict[str, Any]:
    """时间链已修正：无任何违规。"""
    return _hot_variables(
        apply="2026-10-20 08:00:00",
        gas="2026-10-20 08:20:00",
        approve="2026-10-20 08:30:00",
        start="2026-10-20 08:40:00",
        end="2026-10-20 10:00:00",
        finish="2026-10-20 10:30:00",
    )


def _overtime_variables() -> dict[str, Any]:
    """TIME_ORDER 仍在 + 新增 DURATION 超时（二级 72h 上限，实际 ~80h）；
    补午后气体记录避免 GAS_INTERVAL 混入。"""
    return _hot_variables(
        apply="2026-10-20 08:30:00",
        gas="2026-10-20 08:00:00",
        approve="2026-10-20 08:10:00",
        start="2026-10-20 08:20:00",
        end="2026-10-23 16:00:00",
        finish="2026-10-23 17:00:00",
        extra_gas=["2026-10-20 13:00:00", "2026-10-21 08:00:00",
                   "2026-10-21 13:00:00", "2026-10-22 08:00:00",
                   "2026-10-22 13:00:00", "2026-10-23 08:00:00",
                   "2026-10-23 13:00:00"],
    )


class FakeDetailClient:
    """按 pid 返回预置 detail 响应；未预置的 pid 抛异常。"""

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses

    async def detail(self, pid: str) -> Any:
        if pid not in self._responses:
            raise RuntimeError(f"detail 失败 {pid}")
        return self._responses[pid]


class FakeSession:
    """RectifyChecker._save 所需最小会话实现。"""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, stmt: Any) -> Any:
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


class FakeRepo:
    def __init__(
        self,
        review: SimpleNamespace | None,
        violations: list[SimpleNamespace],
    ) -> None:
        self._review = review
        self._violations = violations

    async def get_by_date(self, review_date: Any) -> Any:
        return self._review

    async def list_violations(self, review_id: Any) -> list[Any]:
        return self._violations


def _fake_review(ticket_no: str = "DH-1", include_raw: bool = True) -> SimpleNamespace:
    raw_json = {
        "tickets": [
            {"type": "hot_work", "processInstanceId": "pi-1", "serialNumber": ticket_no},
        ],
    } if include_raw else None
    return SimpleNamespace(id=uuid.uuid4(), raw_json=raw_json)


def _violation_row(
    ticket_no: str,
    rule_no: str = RuleNo.TIME_ORDER,
    detail: str = "申请晚于气体分析",
    not_applicable: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        ticket_no=ticket_no,
        ticket_type="hot_work",
        rule_no=rule_no,
        detail=detail,
        not_applicable=not_applicable,
    )


def _checker(
    review: SimpleNamespace | None,
    violations: list[SimpleNamespace],
    client: FakeDetailClient,
) -> tuple[RectifyChecker, FakeSession]:
    session = FakeSession()
    checker = RectifyChecker(
        session,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        repo=FakeRepo(review, violations),  # type: ignore[arg-type]
    )
    return checker, session


async def test_run_no_review_returns_none() -> None:
    checker, session = _checker(None, [], FakeDetailClient({}))
    result = await checker.run(date(2026, 10, 20), date(2026, 10, 21))
    assert result is None
    assert session.added == []


async def test_run_no_flagged_violations_returns_zero_summary() -> None:
    """零问题票返回 problem_total=0 的空汇总（渲染层显式展示「无问题票」）。"""
    review = _fake_review()
    rows = [_violation_row("DH-1", not_applicable=True)]
    checker, session = _checker(review, rows, FakeDetailClient({}))
    result = await checker.run(date(2026, 10, 20), date(2026, 10, 21))
    assert result is not None
    assert result["problem_total"] == 0
    assert result["tickets"] == []
    assert session.added == []


async def test_run_rectified() -> None:
    review = _fake_review()
    client = FakeDetailClient({
        "pi-1": {"process": {"variables": _fixed_variables()}},
    })
    checker, session = _checker(review, [_violation_row("DH-1")], client)

    summary = await checker.run(date(2026, 10, 20), date(2026, 10, 21))

    assert summary is not None
    assert summary["problem_total"] == 1
    assert summary["rectified"] == 1
    assert summary["unrectified"] == 0
    ticket = summary["tickets"][0]
    assert ticket["status"] == STATUS_RECTIFIED
    assert ticket["ticket_type_name"] == "动火作业"
    assert ticket["rule_results"][0]["resolved"] is True

    # 落库行
    row = session.added[0]
    assert isinstance(row, WorkTicketRectifyCheck)
    assert row.source_review_date == date(2026, 10, 20)
    assert row.checked_date == date(2026, 10, 21)
    assert row.ticket_no == "DH-1"
    assert row.status == STATUS_RECTIFIED


async def test_run_unrectified_with_new_problem() -> None:
    review = _fake_review()
    client = FakeDetailClient({
        "pi-1": {"process": {"variables": _overtime_variables()}},
    })
    checker, session = _checker(review, [_violation_row("DH-1")], client)

    summary = await checker.run(date(2026, 10, 20), date(2026, 10, 21))

    ticket = summary["tickets"][0]
    assert ticket["status"] == STATUS_UNRECTIFIED
    rules = {r["rule_no"]: r for r in ticket["rule_results"]}
    assert rules[RuleNo.TIME_ORDER]["resolved"] is False  # 昨日问题仍在
    assert rules[RuleNo.DURATION]["yesterday_detail"] is None  # 今日新增
    assert rules[RuleNo.DURATION]["resolved"] is False
    assert summary["unrectified"] == 1


async def test_run_missing_pid_uncheckable() -> None:
    review = _fake_review(include_raw=False)  # raw_json=None → 定位不到 pid
    checker, session = _checker(review, [_violation_row("DH-1")], FakeDetailClient({}))

    summary = await checker.run(date(2026, 10, 20), date(2026, 10, 21))

    ticket = summary["tickets"][0]
    assert ticket["status"] == STATUS_UNCHECKABLE
    assert "无法定位" in (ticket["note"] or "")
    assert summary["uncheckable"] == 1


async def test_run_detail_failure_uncheckable() -> None:
    review = _fake_review()  # raw 里 pid=pi-1，但 client 未预置 → 抛异常
    checker, session = _checker(review, [_violation_row("DH-1")], FakeDetailClient({}))

    summary = await checker.run(date(2026, 10, 20), date(2026, 10, 21))

    ticket = summary["tickets"][0]
    assert ticket["status"] == STATUS_UNCHECKABLE
    assert "拉取" in (ticket["note"] or "")
