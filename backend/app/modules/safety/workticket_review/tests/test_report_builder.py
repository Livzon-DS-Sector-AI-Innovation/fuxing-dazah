"""WorkTicketReviewReportBuilder 固定模板单测（feature ticket 05）。

覆盖：
  - 四板块结构（审核概要 / 违规明细 / 合格摘要 / 措施建议）
  - 违规明细按票逐条：票号/类型/规则名/detail/key_times
  - “数据不足”（not_applicable=False 且 detail 以“数据不足：”开头）归入
    「数据不足/待跟进」，不混入「真实违规」
  - not_applicable=True 的规则不列为违规，且该票归入合格摘要
  - 措施建议含按规则固化的中文文案及“补齐对应时间记录”
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.workticket_review.parser import WorkTicket
from app.modules.safety.workticket_review.report_builder import (
    MEASURE_ADVICE,
    WorkTicketReviewReportBuilder,
)
from app.modules.safety.workticket_review.rule_engine import RuleNo, Violation

TZ = ZoneInfo("Asia/Shanghai")
BUILDER = WorkTicketReviewReportBuilder()


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=TZ)


def _ticket(ticket_no: str, ticket_type: str, **kwargs: Any) -> WorkTicket:
    return WorkTicket(ticket_no=ticket_no, ticket_type=ticket_type, **kwargs)


def _report(
    tickets: list[WorkTicket],
    violations_by_ticket: dict[str, list[Violation]],
    stats: dict[str, Any],
) -> str:
    return BUILDER.build(date(2026, 8, 26), tickets, violations_by_ticket, stats)


def _violation(detail: str, *, rule_no: str = RuleNo.TIME_ORDER, not_applicable: bool = False) -> Violation:
    return Violation(
        rule_no=rule_no,
        rule_name="规则",
        detail=detail,
        key_times=["开始=2026-08-26 08:00:00"],
        not_applicable=not_applicable,
    )


def _make_fixture() -> tuple[list[WorkTicket], dict[str, list[Violation]], dict[str, Any]]:
    # 票 1：动火，含 1 条真实违规 + 1 条数据不足 + 1 条不适用
    t1 = _ticket(
        "DH-001",
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 20),
        start_time=_dt(2026, 8, 26, 8, 30),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 10, 30),
        level="1",
        work_site="精制二楼外包间",
        work_content="传递窗焊接",
        apply_unit="精制工程一部",
    )
    # 票 2：高处，仅 not_applicable（gas 规则不适用、时长在限内）→ 合格
    t2 = _ticket(
        "GC-001",
        "height_work",
        apply_time=_dt(2026, 8, 26, 9, 0),
        approve_time=_dt(2026, 8, 26, 9, 20),
        start_time=_dt(2026, 8, 26, 9, 20),
        end_time=_dt(2026, 8, 26, 11, 0),
        finish_time=_dt(2026, 8, 26, 11, 30),
        work_site="小喷一楼外围",
        work_content="关闭冷却水管道阀门",
    )
    # 票 3：受限空间，仅数据不足（缺 end_time）→ 数据不足/待跟进
    t3 = _ticket(
        "SX-001",
        "confined_space",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 20),
        start_time=_dt(2026, 8, 26, 8, 30),
        work_site="316罐",
        work_content="下罐清洗",
        apply_unit="发酵工程部",
    )

    violations = {
        "DH-001": [
            _violation(
                "作业开始前无有效气体分析记录",
                rule_no=RuleNo.GAS_VALIDITY,
            ),
            _violation(
                "数据不足：缺少 结束时间",
                rule_no=RuleNo.DURATION,
            ),
            _violation(
                "该类作业无时长上限，规则不适用",
                rule_no=RuleNo.DURATION,
                not_applicable=True,
            ),
        ],
        "SX-001": [
            _violation(
                "数据不足：缺少 开始时间、结束时间",
                rule_no=RuleNo.GAS_INTERVAL,
            ),
        ],
    }
    # 票 2 不放入 violations_by_ticket，构建器应视作无违规 → 合格
    stats = {
        "total": 3,
        "reviewed": 2,
        "violation_count": 1,
        "compliant_count": 1,
        "data_insufficient": 1,
        "pushed": False,
    }
    return [t1, t2, t3], violations, stats


def test_report_contains_four_sections() -> None:
    tickets, violations, stats = _make_fixture()
    report = _report(tickets, violations, stats)

    assert "📋 【作业票审核日报】 2026-08-26" in report
    for heading in (
        "📊 审核概要",
        "🔴 真实违规",
        "🟢 合格摘要",
    ):
        assert heading in report
    assert "📌 措施建议" not in report


def test_overview_shows_summary_stats() -> None:
    tickets, violations, stats = _make_fixture()
    report = _report(tickets, violations, stats)

    assert "今日标准 8 类作业票数: 3 项" in report
    assert "已审数（已具备开始时间）: 2 项" in report
    assert "违规票数: 1 项" in report
    assert "合格票数: 1 项" in report
    assert "数据不足票数: 1 项" in report
    assert "推送状态" not in report
    # 类型按票分布
    assert "动火作业: 1 项" in report
    assert "高处作业: 1 项" in report
    assert "受限空间作业: 1 项" in report


def test_real_violation_lists_rule_and_key_times() -> None:
    tickets, violations, stats = _make_fixture()
    report = _report(tickets, violations, stats)

    assert "【动火作业】DH-001" in report
    assert "作业开始前无有效气体分析记录" in report
    assert "开始=2026-08-26 08:00:00" in report
    # 真实违规段应展示部门/作业地点/内容
    assert "📍 部门：精制工程一部 ｜ 地点：精制二楼外包间 ｜ 内容：传递窗焊接" in report
    real_section = report.split("🟡 数据不足 / 待跟进")[0]
    # 真实违规段不应出现数据不足条目，也不应出现“数据不足：”文本
    assert "数据不足：" not in real_section
    assert "数据不足：缺少 结束时间" not in real_section


def test_data_insufficient_not_in_real_violation_list() -> None:
    tickets, violations, stats = _make_fixture()
    report = _report(tickets, violations, stats)

    insufficient_section = report.split("🟡 数据不足 / 待跟进")[1]
    assert "数据不足：缺少 结束时间" in insufficient_section
    assert "数据不足：缺少 开始时间、结束时间" in insufficient_section
    # 数据不足段应展示部门/作业地点/内容
    assert "📍 部门：发酵工程部 ｜ 地点：316罐 ｜ 内容：下罐清洗" in insufficient_section
    # 真实违规段中没有数据不足条目
    real_section = report.split("🟡 数据不足 / 待跟进")[0]
    assert "数据不足：" not in real_section


def test_not_applicable_rule_not_listed_as_violation() -> None:
    tickets, violations, stats = _make_fixture()
    report = _report(tickets, violations, stats)

    # “该类作业无时长上限，规则不适用”是 not_applicable，不应出现在违规明细
    assert "该类作业无时长上限，规则不适用" not in report.split("🟢 合格摘要")[0]


def test_compliant_ticket_listed_with_phrase() -> None:
    tickets, violations, stats = _make_fixture()
    report = _report(tickets, violations, stats)

    assert "【高处作业】GC-001" not in report  # 合格票不进违规明细
    assert "GC-001（高处作业）未发现违规" in report
    # 合格段不展示部门/作业地点/内容
    assert "地点：小喷一楼外围" not in report.split("🟢 合格摘要")[1]
    assert "内容：关闭冷却水管道阀门" not in report.split("🟢 合格摘要")[1]
    assert "部门：" not in report.split("🟢 合格摘要")[1]


def test_missing_apply_unit_renders_without_department_part() -> None:
    """申请单位缺失时，📍 行只渲染地点/内容，不残留空部门段或多余分隔符。"""
    tickets, violations, stats = _make_fixture()
    tickets[0].apply_unit = ""
    report = _report(tickets, violations, stats)

    assert "📍 地点：精制二楼外包间 ｜ 内容：传递窗焊接" in report
    assert "部门：" not in report.split("🟡 数据不足 / 待跟进")[0]


def test_measures_contain_fixed_rule_copy() -> None:
    tickets, violations, stats = _make_fixture()
    report = _report(tickets, violations, stats)

    assert "规范票面各时间节点顺序，避免倒签/补签" in MEASURE_ADVICE[RuleNo.TIME_ORDER]
    assert "作业开始前 30 分钟内完成气体复测" in MEASURE_ADVICE[RuleNo.GAS_VALIDITY]
    assert "作业时长超限，严格按 GB30871 时限安排/办延期" in MEASURE_ADVICE[RuleNo.DURATION]
    assert "受限空间每 2h 记录气体" in MEASURE_ADVICE[RuleNo.GAS_INTERVAL]
    assert "特种作业人员" in MEASURE_ADVICE[RuleNo.PERSONNEL_CERT]
    assert "📌 措施建议" not in report


def test_ticket_with_real_violation_and_data_insufficient_in_both_sections() -> None:
    """同一张票同时存在「真实违规」与「数据不足」时，应同时归入两个板块。"""
    tickets, violations, stats = _make_fixture()
    report = _report(tickets, violations, stats)
    real_section = report.split("🟡 数据不足 / 待跟进")[0]
    insufficient_section = report.split("🟡 数据不足 / 待跟进")[1]

    assert "【动火作业】DH-001" in real_section
    assert "【动火作业】DH-001" in insufficient_section
    assert "作业开始前无有效气体分析记录" in real_section
    assert "数据不足：缺少 结束时间" in insufficient_section

