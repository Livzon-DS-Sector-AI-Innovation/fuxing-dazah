"""津贴联动资格剔除 —— R2 拍板⑥/⑦：revoked 停发 + 无证收紧（纯函数）。

- 平台票路线 SubsidyPlanBuilder.build(revoked=…)：资格取消者跳过并注明原因
- 台账路线 build_ledger_plan(revoked=…)：同口径
- 无证口径：uncertified_level=None（拍板⑥收紧）不再暂计 A 证
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.service.subsidy_dept_ledgers import build_ledger_plan
from app.modules.safety.service.subsidy_plan import SubsidyPlanBuilder
from app.modules.safety.workticket_review.parser import WorkTicket

TZ = ZoneInfo("Asia/Shanghai")

CERT_MAP: dict[str, str] = {"张三": "A证", "李四": "A证"}

REVOKED: dict[str, str] = {"张三": "逾期未复审", "李四": "考核不合格"}


def _ticket(no: str, guardian: str) -> WorkTicket:
    return WorkTicket(
        ticket_type="hot_work",
        ticket_no=no,
        guardian=guardian,
        apply_unit="环保部",
        start_time=datetime(2026, 10, 15, 9, 0, tzinfo=TZ),
        end_time=datetime(2026, 10, 15, 11, 0, tzinfo=TZ),
        level="二级",
    )


def test_build_revoked_guardian_skipped_with_reason() -> None:
    """平台票：revoked 监护人的票跳过，注明资格取消原因；正常人不影响。"""
    plan = SubsidyPlanBuilder.build(
        [_ticket("DH-1", "张三"), _ticket("DH-2", "王正常")],
        dict(CERT_MAP, 王正常="A证"),
        "环保部", 2026, 10,
        revoked=REVOKED,
    )
    assert [r.guardian_name for r in plan.records] == ["王正常"]
    reasons = {s.ticket_no: s.reason for s in plan.skipped}
    assert "监护资格已取消" in reasons["DH-1"]
    assert "逾期未复审" in reasons["DH-1"]


def test_build_revoked_none_keeps_old_behavior() -> None:
    """revoked=None → 不剔除（向后兼容；R2 关闭时不影响津贴）。"""
    plan = SubsidyPlanBuilder.build(
        [_ticket("DH-1", "张三")], CERT_MAP, "环保部", 2026, 10,
    )
    assert [r.guardian_name for r in plan.records] == ["张三"]


def test_build_uncertified_none_not_paid() -> None:
    """无证收紧（拍板⑥）：uncertified_level=None → 无证不暂计，只进待核对。"""
    plan = SubsidyPlanBuilder.build(
        [_ticket("DH-9", "无证人")], CERT_MAP, "环保部", 2026, 10,
        uncertified_level=None,
    )
    assert plan.records == []
    assert [u.name for u in plan.unmatched] == ["无证人"]


# ── 台账路线 ──


def _ledger_source() -> Any:
    from app.modules.safety.service.subsidy_dept_ledgers import LEDGER_SOURCES

    return next(s for s in LEDGER_SOURCES if s.department == "提炼工程五部")


def _ledger_rows() -> list[dict]:
    """五部台账两行：张三（revoked）/ 李小正常。"""
    ms = int(datetime(2026, 10, 15, 8, 30, tzinfo=TZ).timestamp() * 1000)
    return [
        {"record_id": "r1", "fields": {
            "监护人": [{"name": "张三", "id": "ou_z"}],
            "监护人级别": "A证",
            "特殊作业类型": "动火作业",
            "作业级别": "二级",
            "开始时间": ms, "结束时间": ms + 2 * 3600 * 1000,
            "作业地点及内容": "罐区",
        }},
        {"record_id": "r2", "fields": {
            "监护人": [{"name": "李小正常", "id": "ou_l"}],
            "监护人级别": "A证",
            "特殊作业类型": "动火作业",
            "作业级别": "二级",
            "开始时间": ms, "结束时间": ms + 2 * 3600 * 1000,
            "作业地点及内容": "罐区",
        }},
    ]


def test_ledger_plan_revoked_skipped() -> None:
    """台账：revoked 行跳过注明原因；正常人正常计。"""
    plan = build_ledger_plan(
        _ledger_source(), _ledger_rows(), 2026, 10,
        uncertified_level=None, revoked={"张三": "考核不合格"},
    )
    assert [r.guardian_name for r in plan.records] == ["李小正常"]
    assert any(
        "监护资格已取消" in s.reason and "考核不合格" in s.reason
        for s in plan.skipped
    )


def test_ledger_plan_revoked_none_unchanged() -> None:
    plan = build_ledger_plan(
        _ledger_source(), _ledger_rows(), 2026, 10, uncertified_level=None,
    )
    assert sorted(r.guardian_name for r in plan.records) == ["张三", "李小正常"]
