"""节点引擎与考核类型辨别 —— 纯函数单测（T01）。

周期口径（拍板①）：第一次复审=取证+1年 / 第二次=+2年 / 应换证=+3年。
顺序消费（拍板③根基）：当前节点=第一个未被合格事件覆盖的节点，过期不跳过；
第 N 次复审合格只消费第 N 个复审节点（exam_history 计数）。
辨别（拍板③）：不在名单→取证；在名单→按考核日期当天当前节点→复审/换证。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.modules.safety.service.guardian_r2.node_engine import (
    PERIOD_YEARS,
    NodeState,
    add_years,
    current_node,
    derive_nodes,
    discriminate,
)
from app.modules.safety.service.guardian_r2.score_parse import ScoreFacts


def _pass_event(exam_type: str, d: date) -> dict[str, Any]:
    return {"exam_type": exam_type, "passed": "合格", "exam_date": d}


@dataclass
class CertRecord:
    """持证记录 duck-typing 替身（字段名与 ORM/直读视图同名）。"""

    person_name: str = "张三"
    department: str | None = "提炼工程一部"
    cert_category: str = "guardian_a"
    issue_date: date | None = date(2026, 1, 10)
    first_review_deadline: date | None = None
    second_review_deadline: date | None = None
    should_renew_date: date | None = None
    renewed_date: date | None = None
    exam_score: str | None = None      # 考核成绩（合格/不合格，回写列）
    exam_date: date | None = None      # 考核日期（回写列）
    exam_type: str | None = None       # 考核类型（取证/复审/换证，回写列）
    guardian_open_id: str | None = "ou_demo"
    exam_history: list[dict[str, Any]] = field(default_factory=list)


def _full_cycle(issue: date, **kw: Any) -> CertRecord:
    return CertRecord(
        issue_date=issue,
        first_review_deadline=add_years(issue, 1),
        second_review_deadline=add_years(issue, 2),
        should_renew_date=add_years(issue, 3),
        **kw,
    )


# ═══════════════════════════════════════════════════════════
# 周期推导（拍板①：1/2/3 年）
# ═══════════════════════════════════════════════════════════


def test_period_years_calibrated() -> None:
    assert PERIOD_YEARS == {"first_review": 1, "second_review": 2, "renew": 3}


def test_derive_nodes_from_issue_date() -> None:
    nodes = derive_nodes(date(2026, 1, 10))
    assert nodes["first_review"] == date(2027, 1, 10)
    assert nodes["second_review"] == date(2028, 1, 10)
    assert nodes["renew"] == date(2029, 1, 10)


def test_add_years_handles_leap_day() -> None:
    """2月29日取证 → 周年无2月29 → 落在2月28日（不抛错）。"""
    assert add_years(date(2024, 2, 29), 1) == date(2025, 2, 28)


# ═══════════════════════════════════════════════════════════
# 当前节点判定（顺序义务）
# ═══════════════════════════════════════════════════════════


def test_current_node_first_review_within_year() -> None:
    rec = _full_cycle(date(2026, 1, 10))
    st = current_node(rec, ref_date=date(2026, 6, 1))
    assert st == NodeState(
        node_key="first_review", label="第一次复审", exam_kind="复审",
        deadline=date(2027, 1, 10), remaining_days=223,
    )


def test_current_node_obligation_is_sequential_not_date_skipped() -> None:
    """无合格事件时义务不随日期跳过：第一次复审过期未过 → 仍是第一次复审（逾期）。"""
    rec = _full_cycle(date(2026, 1, 10))
    st = current_node(rec, ref_date=date(2028, 6, 1))
    assert st.node_key == "first_review"
    assert st.remaining_days is not None and st.remaining_days < 0


def test_current_node_passed_by_score_advances() -> None:
    """第一次复审合格（回写三列）→ 消费第一个节点，推进到第二次复审。"""
    rec = _full_cycle(date(2026, 1, 10))
    rec.exam_score, rec.exam_date, rec.exam_type = "合格", date(2026, 12, 1), "复审"
    st = current_node(rec, ref_date=date(2026, 12, 15))
    assert st.node_key == "second_review"
    assert st.deadline == date(2028, 1, 10)


def test_current_node_single_review_pass_consumed_once() -> None:
    """一次复审合格（history 单事件）只消费第一个复审节点——第二次仍待办。"""
    rec = _full_cycle(date(2024, 6, 1), exam_history=[
        _pass_event("复审", date(2025, 6, 1)),  # 周期内（> issue 2024-06-01）
    ])
    st = current_node(rec, ref_date=date(2026, 6, 1))
    assert st.node_key == "second_review"


def test_current_node_pre_cycle_event_not_consumed() -> None:
    """周期起点前的旧事件（脏数据/换证残留）不消费新周期节点。"""
    rec = _full_cycle(date(2026, 1, 10), exam_history=[
        _pass_event("复审", date(2025, 6, 1)),  # < issue → 不算
    ])
    st = current_node(rec, ref_date=date(2026, 6, 1))
    assert st.node_key == "first_review"  # 未被消费


def test_current_node_cross_cycle_leak_prevented() -> None:
    """换证重开周期：旧周期 2 复审+1 换证事件不消费新周期节点（Spec 审查①）。"""
    rec = _full_cycle(date(2023, 1, 10), exam_history=[
        _pass_event("复审", date(2024, 1, 10)),
        _pass_event("复审", date(2025, 1, 10)),
        _pass_event("换证", date(2026, 2, 1)),
    ])
    rec.renewed_date = date(2026, 2, 1)  # 新周期起点
    st = current_node(rec, ref_date=date(2026, 6, 1))
    assert st.node_key == "first_review"  # 新周期第一次复审仍待办
    assert st.deadline == date(2027, 2, 1)


def test_current_node_two_review_passes_reach_renew() -> None:
    """两次复审合格 → 到达换证节点。"""
    rec = _full_cycle(date(2024, 1, 10), exam_history=[
        _pass_event("复审", date(2024, 12, 1)),
        _pass_event("复审", date(2025, 12, 1)),
    ])
    st = current_node(rec, ref_date=date(2026, 6, 1))
    assert st.node_key == "renew"
    assert st.exam_kind == "换证"
    assert st.deadline == date(2027, 1, 10)


def test_current_node_score_type_mismatch_not_passed() -> None:
    """考核类型=取证 不消费复审节点（类型必须匹配节点语义）。"""
    rec = _full_cycle(date(2026, 1, 10))
    rec.exam_score, rec.exam_date, rec.exam_type = "合格", date(2026, 12, 1), "取证"
    st = current_node(rec, ref_date=date(2026, 12, 15))
    assert st.node_key == "first_review"


def test_current_node_failed_score_not_passed() -> None:
    """考核不合格不消费节点（不合格走取消资格链路，节点仍待办）。"""
    rec = _full_cycle(date(2026, 1, 10))
    rec.exam_score, rec.exam_date, rec.exam_type = "不合格", date(2026, 12, 1), "复审"
    st = current_node(rec, ref_date=date(2026, 12, 15))
    assert st.node_key == "first_review"


def test_current_node_future_exam_date_not_counted() -> None:
    """考核日期晚于基准日（误填未来）→ 不消费。"""
    rec = _full_cycle(date(2026, 1, 10))
    rec.exam_score, rec.exam_date, rec.exam_type = "合格", date(2027, 6, 1), "复审"
    st = current_node(rec, ref_date=date(2026, 12, 15))
    assert st.node_key == "first_review"


def test_current_node_renewed_date_recalc_cycle() -> None:
    """已换证日期回填 → 新周期从 renewed+1 年第一次复审起算（成功延期换证）。"""
    rec = _full_cycle(date(2023, 1, 10))
    rec.renewed_date = date(2026, 2, 1)
    st = current_node(rec, ref_date=date(2026, 6, 1))
    assert st.node_key == "first_review"
    assert st.deadline == date(2027, 2, 1)
    assert st.remaining_days == 245


def test_current_node_all_dates_missing() -> None:
    st = current_node(CertRecord(issue_date=None), ref_date=date(2026, 6, 1))
    assert st.node_key is None and st.deadline is None and st.remaining_days is None


def test_current_node_all_passed_no_pending() -> None:
    """三节点全被合格事件消费 → 无待办（NodeState None）。"""
    rec = _full_cycle(date(2023, 1, 10), exam_history=[
        _pass_event("复审", date(2023, 12, 1)),
        _pass_event("复审", date(2024, 12, 1)),
        _pass_event("换证", date(2025, 12, 1)),
    ])
    st = current_node(rec, ref_date=date(2026, 6, 1))
    assert st.node_key is None


# ═══════════════════════════════════════════════════════════
# 考核类型辨别（拍板③）
# ═══════════════════════════════════════════════════════════


def _facts(**kw: Any) -> ScoreFacts:
    base = dict(
        person_name="张三", open_id="ou_demo", department="提炼工程一部",
        cert_category="guardian_a", passed="合格", exam_date=date(2026, 12, 1),
        score_value=88.0,
    )
    base.update(kw)
    return ScoreFacts(**base)


def test_discriminate_new_person_is_enroll() -> None:
    """合格 + 不在名单 → 取证（自动进 A 证名单）。"""
    result, detail, _matched = discriminate(_facts(), [])
    assert result == "取证"


def test_discriminate_new_person_failed_is_noop() -> None:
    """不合格 + 不在名单 → 无需处理（无资格可取消）。"""
    result, detail, _matched = discriminate(_facts(passed="不合格"), [])
    assert result == "无需处理"


def test_discriminate_review_node() -> None:
    """在名单 + 考核日期当天首个待办节点=第一次复审 → 复审。"""
    rec = _full_cycle(date(2026, 1, 10))
    result, detail, _matched = discriminate(_facts(exam_date=date(2026, 12, 1)), [rec])
    assert result == "复审"


def test_discriminate_overdue_review_still_review() -> None:
    """第一次复审已逾期未过 → 补考辨别为复审（义务顺序，不是换证）。"""
    rec = _full_cycle(date(2023, 6, 1))  # first=2024-06-01 早已过期
    result, detail, _matched = discriminate(_facts(exam_date=date(2026, 12, 1)), [rec])
    assert result == "复审"


def test_discriminate_renew_node() -> None:
    """在名单 + 两次复审已过 → 当前节点=换证 → 换证（成功延期换证）。"""
    rec = _full_cycle(date(2024, 1, 10), exam_history=[
        _pass_event("复审", date(2024, 12, 1)),
        _pass_event("复审", date(2025, 12, 1)),
    ])
    result, detail, _matched = discriminate(_facts(exam_date=date(2026, 12, 1)), [rec])
    assert result == "换证"


def test_discriminate_routes_by_cert_category() -> None:
    """A 证成绩只匹配 A 证记录；名单里只有 B 证 → 视为取证。"""
    rec = CertRecord(person_name="张三", cert_category="guardian_b",
                     issue_date=date(2024, 1, 10))
    result, detail, _matched = discriminate(_facts(cert_category="guardian_a"), [rec])
    assert result == "取证"


def test_discriminate_same_name_department_disambiguation() -> None:
    """同名多命中 → 成绩表部门消歧命中唯一记录 → 正常辨别。"""
    a = CertRecord(person_name="张三", department="提炼工程一部",
                   issue_date=date(2026, 1, 10))
    b = CertRecord(person_name="张三", department="发酵工程部",
                   issue_date=date(2024, 1, 10))
    result, detail, _matched = discriminate(
        _facts(exam_date=date(2026, 12, 1)), [a, b]
    )
    assert result == "复审"


def test_discriminate_same_name_ambiguous_is_error() -> None:
    """同名且部门无法消歧 → 异常（不猜测）。"""
    a = CertRecord(person_name="张三", issue_date=date(2026, 1, 10))
    b = CertRecord(person_name="张三", issue_date=date(2024, 1, 10))
    result, detail, _matched = discriminate(_facts(), [a, b])
    assert result == "异常"


def test_discriminate_no_person_name_is_error() -> None:
    result, detail, _matched = discriminate(_facts(person_name=None), [])
    assert result == "异常"


def test_discriminate_no_node_dates_is_error() -> None:
    """在名单但记录无任何日期 → 无法辨别 → 异常。"""
    rec = CertRecord(issue_date=None)
    result, detail, _matched = discriminate(_facts(), [rec])
    assert result == "异常"
