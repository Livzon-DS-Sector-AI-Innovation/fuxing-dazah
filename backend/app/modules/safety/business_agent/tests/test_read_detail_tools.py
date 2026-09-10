"""已同步本地库明细查询工具单测（special_op / key_risk_op / ehs_change /
work_ticket / hazard_id 五个只读工具）。

测试接缝（与 test_subsidy_tools 一致）：
- mock ``ctx.deps.db``：FakeSession 按调用序返回预设结果，并记录收到的
  statement（断言 where 骨架）；
- 直接调用工具函数（不走 core.pipeline，避免真实审计写库）；
- 行对象用真实模型实例构造（不落库）。

覆盖：
- registry TOOL_KIND / _all_read_funcs 接线；
- permissions：五个工具进入 _READ_TOOLS（viewer 也可查）；
- tool_selector 关键词激活（用户原话"提炼工程五部作业判定记录"命中）；
- 参数规范化 _norm_choice（中文→code / code 兼容 / 未知原样）；
- 各工具返回结构与 where 骨架（部门模糊、风险等级、not_applicable 默认排除）。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import allowed_tools, ROLE_VIEWER
from app.modules.safety.business_agent.tools import registry
from app.modules.safety.business_agent.tools.read_tools import (
    _norm_choice,
    query_ehs_changes,
    query_hazard_identifications,
    query_key_risk_ops,
    query_special_op_records,
    query_work_ticket_reviews,
    _SPECIAL_OP_RISK_MAP,
)
from app.modules.safety.models import (
    EhsChange,
    HazardIdentification,
    KeyRiskOperationReport,
    SpecialOperationReport,
    WorkTicketReview,
    WorkTicketReviewViolation,
)

NEW_TOOLS = [
    "query_special_op_records",
    "query_key_risk_ops",
    "query_ehs_changes",
    "query_work_ticket_reviews",
    "query_hazard_identifications",
]

QUERY_FUNCS = {
    "query_special_op_records": query_special_op_records,
    "query_key_risk_ops": query_key_risk_ops,
    "query_ehs_changes": query_ehs_changes,
    "query_work_ticket_reviews": query_work_ticket_reviews,
    "query_hazard_identifications": query_hazard_identifications,
}


# ── Fake DB（按调用序返回；记录 statement）────────────────────────


class _FakeResult:
    def __init__(self, *, scalar: Any = None, rows: list[Any] | None = None,
                 pairs: list[tuple[Any, ...]] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []
        self._pairs = pairs or []

    def scalar(self) -> Any:
        return self._scalar

    def scalars(self) -> Any:
        return SimpleNamespace(all=lambda: self._rows)

    def all(self) -> list[Any]:
        return self._pairs


class FakeSession:
    """依次返回预设结果；收集 execute 收到的 statement 供断言。"""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.statements.append(stmt)
        return self._results.pop(0)


def _ctx(db: FakeSession) -> SimpleNamespace:
    return SimpleNamespace(deps=SimpleNamespace(db=db))


# ── 接线：registry / permissions / tool_selector ─────────────────


def test_registry_wiring() -> None:
    for name in NEW_TOOLS:
        assert registry.TOOL_KIND.get(name) is False, name
    read_names = {f.__name__ for f in registry._all_read_funcs()}
    assert set(NEW_TOOLS) <= read_names


def test_permissions_viewer_can_query() -> None:
    allowed = allowed_tools(ROLE_VIEWER)
    assert set(NEW_TOOLS) <= allowed


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("提炼工程五部作业判定记录发给我看下", "query_special_op_records"),
        ("8月31日的作业票审核结果", "query_work_ticket_reviews"),
        ("最近有哪些EHS变更", "query_ehs_changes"),
        ("本周关键风险作业有哪些", "query_key_risk_ops"),
        ("提炼五部的危险源辨识LEC评级", "query_hazard_identifications"),
    ],
)
def test_tool_selector_activates(message: str, expected: str) -> None:
    names = tool_selector.select_tool_names(message)
    assert expected in names


# ── 参数规范化 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "mapping", "expected"),
    [
        ("高风险", _SPECIAL_OP_RISK_MAP, "high"),
        ("高", _SPECIAL_OP_RISK_MAP, "high"),
        ("MEDIUM", _SPECIAL_OP_RISK_MAP, "medium"),
        ("low", _SPECIAL_OP_RISK_MAP, "low"),
        ("动火作业", {"动火作业": "hot_work"}, "hot_work"),
        ("hot_work", {"动火作业": "hot_work"}, "hot_work"),
        ("未知值", {"动火作业": "hot_work"}, "未知值"),
        (None, _SPECIAL_OP_RISK_MAP, None),
    ],
)
def test_norm_choice(raw: str | None, mapping: dict[str, str], expected: str | None) -> None:
    assert _norm_choice(raw, mapping) == expected


# ── 特殊作业明细 ──────────────────────────────────────────────────


def _sp_row(**overrides: Any) -> SpecialOperationReport:
    base = dict(
        report_no="BT-0001", department="提炼工程五部", operation_type="hot_work",
        operation_level="grade1", daily_risk_level="medium",
        daily_risk_reason="动火作业+其他特殊作业", planned_start_time=None,
    )
    base.update(overrides)
    return SpecialOperationReport(**base)


@pytest.mark.asyncio
async def test_special_op_records_query() -> None:
    db = FakeSession([
        _FakeResult(scalar=2),
        _FakeResult(rows=[_sp_row(), _sp_row(report_no="BT-0002")]),
    ])
    r = await query_special_op_records(
        _ctx(db), department="提炼工程五部", date_from="2026-09-02",
        date_to="2026-09-03", daily_risk_level="高风险",
    )
    assert r["success"] is True
    assert r["total"] == 2
    assert len(r["items"]) == 2
    assert r["items"][0]["department"] == "提炼工程五部"
    assert r["items"][0]["daily_risk_level"] == "medium"
    # where 骨架：部门模糊 + 日期区间 + 风险等级（"高风险"已规范化）
    sql = str(db.statements[0])
    assert "department" in sql
    assert "LIKE" in sql  # ilike → lower(x) LIKE lower(:y)（default 方言）
    assert "planned_start_time >=" in sql
    assert "daily_risk_level =" in sql
    compiled = db.statements[0].compile()
    assert "high" in str(compiled.params)


@pytest.mark.asyncio
async def test_special_op_records_error_path() -> None:
    class Boom(FakeSession):
        async def execute(self, stmt: Any) -> Any:
            raise RuntimeError("db down")

    r = await query_special_op_records(_ctx(Boom([])), department="x")
    assert r["success"] is False
    assert "查询失败" in r["error"]


# ── 关键风险作业 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_key_risk_ops_query() -> None:
    row = KeyRiskOperationReport(
        report_no="KR-001", department="提炼工程五部", area="一车间",
        operation_content="更换反应釜密封圈",
    )
    db = FakeSession([_FakeResult(scalar=1), _FakeResult(rows=[row])])
    r = await query_key_risk_ops(_ctx(db), department="五部", apply_status="已通过")
    assert r["success"] is True
    assert r["total"] == 1
    assert r["items"][0]["operation_content"] == "更换反应釜密封圈"
    sql = str(db.statements[0])
    assert "department" in sql
    assert "apply_status =" in sql


# ── EHS 变更 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ehs_changes_query() -> None:
    row = EhsChange(change_no="EHS-001", title="DCS 系统升级",
                    change_grade="major", department="生产部")
    db = FakeSession([_FakeResult(scalar=1), _FakeResult(rows=[row])])
    r = await query_ehs_changes(_ctx(db), change_grade="重大", keyword="DCS")
    assert r["success"] is True
    assert r["items"][0]["title"] == "DCS 系统升级"
    sql = str(db.statements[0])
    assert "change_grade =" in sql
    assert "title" in sql
    # "重大" → major
    assert "major" in str(db.statements[0].compile().params)


# ── 作业票审核 ────────────────────────────────────────────────────


def _wt_review(rid: str, d: str) -> WorkTicketReview:
    return WorkTicketReview(
        id=rid, date=date.fromisoformat(d), total=32, reviewed=32,
        violation_count=3, compliant_count=29, data_insufficient=0,
    )


def _wt_violation(rid: str, **overrides: Any) -> WorkTicketReviewViolation:
    base = dict(
        review_id=rid, ticket_no="DH-2026-001", ticket_type="hot_work",
        rule_no="7.1.3", rule_name="气体检测间隔", detail="缺少 finish_time",
        not_applicable=False,
    )
    base.update(overrides)
    return WorkTicketReviewViolation(**base)


@pytest.mark.asyncio
async def test_work_ticket_reviews_excludes_not_applicable_by_default() -> None:
    rid = "00000000-0000-0000-0000-000000000001"
    db = FakeSession([
        _FakeResult(scalar=1),                       # 批次 count
        _FakeResult(rows=[_wt_review(rid, "2026-08-31")]),  # 批次行
        _FakeResult(pairs=[(_wt_violation(rid), date(2026, 8, 31))]),  # 违规 join
        _FakeResult(scalar=1),                       # 违规 count
    ])
    r = await query_work_ticket_reviews(_ctx(db), date_from="2026-08-31", date_to="2026-08-31")
    assert r["success"] is True
    assert r["reviews"][0]["violation_count"] == 3
    assert r["violation_total"] == 1
    assert r["violations"][0]["review_date"] == "2026-08-31"
    # 默认排除 not_applicable（"规则不适用"记录不算违规）
    assert "not_applicable IS false" in str(db.statements[2])


@pytest.mark.asyncio
async def test_work_ticket_reviews_include_not_applicable() -> None:
    rid = "00000000-0000-0000-0000-000000000002"
    db = FakeSession([
        _FakeResult(scalar=1),
        _FakeResult(rows=[_wt_review(rid, "2026-08-31")]),
        _FakeResult(pairs=[(_wt_violation(rid, not_applicable=True), date(2026, 8, 31))]),
        _FakeResult(scalar=1),
    ])
    r = await query_work_ticket_reviews(
        _ctx(db), date_from="2026-08-31", include_not_applicable=True,
    )
    assert r["success"] is True
    assert "not_applicable IS false" not in str(db.statements[2])


# ── 危险源辨识 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hazard_identifications_query() -> None:
    row = HazardIdentification(
        hazard_id_no="HI-001", department="提炼工程五部", position="反应岗",
        inherent_risk_label="一级/重大风险",
    )
    db = FakeSession([_FakeResult(scalar=1), _FakeResult(rows=[row])])
    r = await query_hazard_identifications(
        _ctx(db), department="提炼", risk_stage="inherent", risk_level="1",
    )
    assert r["success"] is True
    assert r["items"][0]["inherent_risk_label"] == "一级/重大风险"
    sql = str(db.statements[0])
    assert "inherent_risk_label" in sql
    # 等级 "1" → 匹配词 ["一级", "重大"]
    params = str(db.statements[0].compile().params)
    assert "一级" in params and "重大" in params
