"""SubsidyPlanBuilder 纯函数单测（主接缝，用例清单见 backend-design 6.1）。

夹具直接构造 WorkTicket（含 02 新字段 guardian/apply_unit）+ 证书映射，
不依赖 DB / 网络；build_certificate_map 用最小 mock session 校验 A 优先/去空格。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.safety.service.subsidy import SUBSIDY_RATES, SubsidyService
from app.modules.safety.service.subsidy_plan import (
    _OP_TYPE_LABEL,
    SubsidyPlanBuilder,
    UnmatchedGuardian,
    build_certificate_map,
)
from app.modules.safety.workticket_review.parser import WorkTicket

TZ = ZoneInfo("Asia/Shanghai")

# 证书映射（键已去空格）：张三 A证 / 李四 B证 / 王五 B证
CERT_MAP: dict[str, str] = {"张三": "A证", "李四": "B证", "王五": "B证"}


class _Unset:
    """哨兵：区分「未传时间参数（用默认值）」与「显式 None（缺失时间）」。"""


_UNSET = _Unset()


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def _ticket(
    ticket_type: str = "hot_work",
    *,
    ticket_no: str = "DH-001",
    guardian: str = "张三",
    apply_unit: str = "环保部",
    start_time: datetime | None | _Unset = _UNSET,
    end_time: datetime | None | _Unset = _UNSET,
    level: str | None = "二级",
    work_site: str | None = "车间一楼",
    work_content: str | None = "动火焊接",
    **kwargs: Any,
) -> WorkTicket:
    start = _dt(2026, 8, 1, 8) if start_time is _UNSET else start_time
    end = _dt(2026, 8, 1, 11) if end_time is _UNSET else end_time
    return WorkTicket(
        ticket_type=ticket_type,
        ticket_no=ticket_no,
        start_time=start,
        end_time=end,
        level=level,
        work_site=work_site,
        work_content=work_content,
        guardian=guardian,
        apply_unit=apply_unit,
        **kwargs,
    )


# ── 6.1 用例 1: 部门包含匹配 ──

def test_dept_keyword_contains_match() -> None:
    tickets = [
        _ticket(ticket_no="A-001", apply_unit="环保部", guardian="张三"),
        _ticket(ticket_no="A-002", apply_unit="发酵工程部", guardian="李四"),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert len(plan.records) == 1
    assert plan.records[0].guardian_name == "张三"
    assert plan.matched_tickets == 1
    # 不命中的部门票不计入 records/unmatched/skipped，但出现在候选部门清单
    assert plan.departments == {"环保部", "发酵工程部"}
    assert plan.unmatched == []
    assert plan.skipped == []


# ── 6.1 用例 2: 月份按开始时间过滤（跨月申请花 8 月） ──

def test_month_filter_by_start_time() -> None:
    tickets = [
        # 申请时间 7 月，开始时间 8 月 → 归 8 月
        _ticket(
            ticket_no="M-001",
            apply_time=_dt(2026, 7, 28),
            start_time=_dt(2026, 8, 2, 9),
            end_time=_dt(2026, 8, 2, 12),
        ),
        # 开始时间 7 月 → 不归 8 月
        _ticket(
            ticket_no="M-002",
            apply_time=_dt(2026, 8, 1),
            start_time=_dt(2026, 7, 31, 9),
            end_time=_dt(2026, 7, 31, 12),
        ),
        # 开始时间 9 月 → 不归 8 月（窗口拉数时会被拉回但过滤掉）
        _ticket(
            ticket_no="M-003",
            start_time=_dt(2026, 9, 1, 9),
            end_time=_dt(2026, 9, 1, 12),
        ),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.total_tickets == 3
    assert plan.matched_tickets == 1
    assert plan.records[0].start_time == "2026-08-02T09:00:00+08:00"
    assert plan.skipped == []


# ── 6.1 用例 3: 8 类票 guardian/apply_unit → 记录（含中文标签映射） ──

def test_guardian_extracted_per_ticket_type() -> None:
    tickets = [
        # 时间错开（同日不重叠），避免触发同日重叠去重
        _ticket(
            ticket_type=type_key, ticket_no=f"T-{type_key}",
            start_time=_dt(2026, 8, 1, 7 + i * 2),
            end_time=_dt(2026, 8, 1, 9 + i * 2),
        )
        for i, type_key in enumerate((
            "hot_work",
            "confined_space",
            "height_work",
            "lifting",
            "temporary_electricity",
            "excavation",
            "road_breaking",
            "blind_plate",
        ))
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 8
    assert all(r.interval_hours == "0" for r in plan.records)
    expected: dict[str, str] = {
        "hot_work": "动火作业",
        "confined_space": "受限空间",
        "height_work": "登高作业",
        "lifting": "吊装作业",
        "temporary_electricity": "临时用电",
        "excavation": "动土",
        "road_breaking": "断路",
        "blind_plate": "抽堵盲板",
    }
    labels = {r.operation_type for r in plan.records}
    assert labels == set(expected.values())
    assert plan.records[0].guardian_name == "张三"


# ── 6.1 用例 4: 无监护人 → 跳过 ──

def test_no_guardian_is_skipped() -> None:
    tickets = [
        _ticket(ticket_no="G-001", guardian=""),
        _ticket(ticket_no="G-002", guardian="   "),
        _ticket(ticket_no="G-003", guardian="张三"),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert len(plan.records) == 1
    assert plan.skipped_tickets == 2
    assert all(s.reason == "无监护人" for s in plan.skipped)
    assert {s.ticket_no for s in plan.skipped} == {"G-001", "G-002"}


# ── 6.1 用例 5: A/B 证匹配，A 优先 ──

def test_guardian_certificate_match_a_preferred() -> None:
    tickets = [
        _ticket(ticket_no="C-001", guardian="张三"),
        _ticket(ticket_no="C-002", guardian="李四"),
    ]
    # 张三同时持有 A/B 证（map 层已 A 优先为 A证），李四只有 B证
    cert_map = {"张三": "A证", "李四": "B证"}

    plan = SubsidyPlanBuilder.build(tickets, cert_map, "环保", 2026, 8)

    assert plan.matched_tickets == 2
    levels = {r.guardian_name: r.guardian_level for r in plan.records}
    assert levels == {"张三": "A证", "李四": "B证"}


# ── 6.1 用例 6: 未匹配证书 → unmatched 且不计金额 ──

def test_guardian_no_cert_goes_unmatched() -> None:
    tickets = [
        _ticket(ticket_no="U-001", guardian="王不存在"),
        _ticket(ticket_no="U-002", guardian="王不存在"),
        _ticket(ticket_no="U-003", guardian="张三"),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 1
    assert plan.unmatched_tickets == 2
    assert plan.unmatched == [
        UnmatchedGuardian(name="王不存在", ticket_count=2, operation_types=["动火作业"])
    ]
    assert all(r.guardian_name == "张三" for r in plan.records)


# ── 6.1 用例 7: interval_hours 恒 0 ──

def test_interval_hours_always_zero() -> None:
    tickets = [
        _ticket(ticket_no="I-001"),
        _ticket(ticket_no="I-002", ticket_type="confined_space"),
        _ticket(ticket_no="I-003", ticket_type="blind_plate"),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.records
    assert all(r.interval_hours == "0" for r in plan.records)


# ── 6.1 用例 8: 作废票跳过（仅目标部门+目标月域内，P-3） ──

def test_void_ticket_skipped() -> None:
    tickets = [
        # 目标部门+目标月：作废 → skipped
        _ticket(ticket_no="V-001", raw={"variables": {"wf_process_terminate": "true"}}),
        _ticket(ticket_no="V-002", guardian="张三"),
        # 非目标部门 / 非目标月：作废票不进入 skipped（域外忽略）
        _ticket(ticket_no="V-003", apply_unit="发酵工程部",
                raw={"variables": {"wf_process_terminate": "true"}}),
        _ticket(ticket_no="V-004", start_time=_dt(2026, 9, 1, 9),
                raw={"variables": {"wf_process_terminate": "true"}}),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 1
    assert [s.ticket_no for s in plan.skipped] == ["V-001"]
    assert plan.skipped[0].reason == "作废/数据不足"


# ── 6.1 用例 9: 缺少开始/结束时间 → 跳过（部门/月份过滤后的语义，P-3） ──

def test_missing_time_skipped() -> None:
    tickets = [
        # 目标部门域内：缺开始时间 → 跳过（月份不明，已属目标部门域）
        _ticket(ticket_no="T-001", start_time=None),
        # 目标部门+目标月：动火（非按次）缺结束时间 → 跳过
        _ticket(ticket_no="T-002", end_time=None),
        # 非目标部门：缺时间不进入 skipped
        _ticket(ticket_no="T-003", start_time=None, apply_unit="发酵工程部"),
        # 非目标月（9 月）：缺结束时间不进入 skipped
        _ticket(ticket_no="T-004", end_time=None, start_time=_dt(2026, 9, 5, 8)),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.records == []
    reasons = {s.ticket_no: s.reason for s in plan.skipped}
    assert reasons == {"T-001": "缺少开始时间", "T-002": "缺少结束时间"}


# ── 6.1 用例 9b: 按次/块/罐计费票种缺结束时间 → 兜底不跳过（P-2） ──

def test_occurrence_types_without_end_time_not_skipped() -> None:
    tickets = [
        _ticket(ticket_no="BP-001", ticket_type="blind_plate", end_time=None),
        _ticket(ticket_no="TE-001", ticket_type="temporary_electricity", end_time=None),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.skipped == []
    assert plan.matched_tickets == 2
    by_label = {r.operation_type: r for r in plan.records}
    assert set(by_label) == {"抽堵盲板", "临时用电"}
    # 兜底 end=start（保持 start 时间基线）
    for r in plan.records:
        assert r.end_time == r.start_time

    # 仍缺 start_time → 无时间基线，跳过
    plan2 = SubsidyPlanBuilder.build(
        [_ticket(ticket_no="BP-002", ticket_type="blind_plate",
                 start_time=None, end_time=None)],
        CERT_MAP, "环保", 2026, 8,
    )
    assert plan2.records == []
    assert [s.reason for s in plan2.skipped] == ["缺少开始时间"]


def test_occurrence_types_amount_default_rate() -> None:
    """P-2 回归：盲板/临电缺结束时间按次计费，金额=默认费率，时长不影响。"""
    tickets = [
        _ticket(ticket_no="BP-001", ticket_type="blind_plate", end_time=None,
                guardian="张三"),
        _ticket(ticket_no="TE-001", ticket_type="temporary_electricity", end_time=None,
                guardian="李四"),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)
    assert plan.matched_tickets == 2

    result = SubsidyService.calculate(plan.records, year=2026, month=8)

    amounts = {r.operation_type: r.subsidy_amount for r in result.details}
    assert amounts == {"抽堵盲板": 10.0, "临时用电": 15.0}
    assert all(r.billing_unit_label == "次/块/罐" for r in result.details)
    assert all(r.raw_hours == 0.0 for r in result.details)


# ── 6.1 用例 9c: domain_tickets 口径（部门+月份命中，不含 void，P-3） ──

def test_domain_tickets_count() -> None:
    tickets = [
        _ticket(ticket_no="D-001", guardian="张三"),  # 命中 → 计入
        _ticket(ticket_no="D-002", guardian="李四"),  # 命中 → 待核对
        _ticket(ticket_no="D-003",                    # 命中但 void → 不计 domain
                raw={"variables": {"wf_process_terminate": "true"}}),
        _ticket(ticket_no="D-004", start_time=None),  # 缺开始时间（月不明）→ 非 domain
        _ticket(ticket_no="D-005", apply_unit="发酵工程部", guardian="张三"),  # 非目标部门
        _ticket(ticket_no="D-006", start_time=_dt(2026, 9, 1, 9)),           # 非目标月
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.domain_tickets == 2
    assert plan.matched_tickets == 2  # D-001(张三) + D-002(李四) 均匹配证书
    assert plan.skipped_tickets == 2  # D-003(作废) + D-004(缺开始时间)
    assert {s.ticket_no for s in plan.skipped} == {"D-003", "D-004"}


# ── 6.1 用例 10: 未知作业类型 → 跳过 ──

def test_unknown_op_type_skipped() -> None:
    tickets = [
        _ticket(ticket_type="unknown_type", ticket_no="K-001"),
        _ticket(ticket_type="hot_work", ticket_no="K-002"),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 1
    assert [s.ticket_no for s in plan.skipped] == ["K-001"]
    assert plan.skipped[0].reason == "未知作业类型"


# ── 6.1 用例 11: 地点为空容忍（受限/断路/盲板） ──

def test_location_content_tolerate_empty_site() -> None:
    tickets = [
        # 受限空间：地点空，内容有
        _ticket(ticket_no="L-001", ticket_type="confined_space",
                work_site=None, work_content="清罐作业",
                start_time=_dt(2026, 8, 1, 8), end_time=_dt(2026, 8, 1, 10)),
        # 断路：地点/内容全空
        _ticket(ticket_no="L-002", ticket_type="road_breaking",
                work_site=None, work_content="",
                start_time=_dt(2026, 8, 1, 10), end_time=_dt(2026, 8, 1, 12)),
        # 盲板：同上
        _ticket(ticket_no="L-003", ticket_type="blind_plate",
                work_site="管线钳位", work_content=None,
                start_time=_dt(2026, 8, 1, 12), end_time=_dt(2026, 8, 1, 14)),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 3
    by_no = {
        t.ticket_no: r.location_content
        for t, r in zip(tickets, plan.records, strict=True)
    }
    assert by_no["L-001"] == "清罐作业"
    assert by_no["L-002"] == ""
    assert by_no["L-003"] == "管线钳位"


# ── 6.1 用例 12: 跨月窗口去重/过滤（可选） ──

def test_cross_month_window_dedup() -> None:
    # 模拟窗口（前后各 1 月）拉回的重复/邻月票：7/8/9 月，目标 8 月
    tickets = [
        _ticket(ticket_no="W-001", start_time=_dt(2026, 7, 20, 9)),
        _ticket(ticket_no="W-001", start_time=_dt(2026, 8, 10, 9)),  # 同票号重复（窗口边界）
        _ticket(ticket_no="W-002", start_time=_dt(2026, 8, 15, 9)),
        _ticket(ticket_no="W-003", start_time=_dt(2026, 9, 1, 9)),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    # 仅 8 月的票进入 records（重复票号按各自开始时间独立过滤）
    assert plan.total_tickets == 4
    assert plan.matched_tickets == 2
    assert plan.domain_tickets == 2  # 8 月命中 2 张（7/9 月与重复票不属目标月域）
    assert plan.skipped == []


# ── 6.1 用例 13: 经 SubsidyService.calculate 全链路回归（午休扣除 + 二级动火连续按天） ──

def test_regression_subsidy_calculate() -> None:
    ticket = _ticket(
        ticket_no="R-001",
        guardian="张三",
        level="二级",
        work_site="精制二楼外包间",
        work_content="传递窗焊接",
        start_time=_dt(2026, 8, 1, 8),
        end_time=_dt(2026, 8, 1, 17),
    )

    plan = SubsidyPlanBuilder.build([ticket], CERT_MAP, "环保", 2026, 8)
    assert plan.matched_tickets == 1

    result = SubsidyService.calculate(plan.records, year=2026, month=8)

    assert result.stats.total_records == 1
    assert result.stats.guardian_count == 1
    assert result.stats.a_cert_count == 1
    detail = result.details[0]
    assert detail.guardian_level == "A证"
    assert detail.operation_type == "动火作业"
    assert detail.operation_level == "二级"
    # 8:00-17:00 → 总 9h，扣午休 1.5h → 有效 7.5h<8h → 非连续，按半小时 15×8=120 元
    assert detail.billing_unit_label == "半小时"
    assert detail.unit_price == 8
    assert detail.subsidy_amount == 120
    assert "扣除午休" in detail.remark
    assert "连续作业按天" not in detail.remark
    assert result.stats.total_amount == 120


# ── 补充用例: 中文标签与 SUBSIDY_RATES 兼容（8 类全覆盖） ──

def test_op_labels_compatible_with_subsidy_rates() -> None:
    assert set(_OP_TYPE_LABEL.values()) <= set(SUBSIDY_RATES.keys())
    # 8 类票均有映射
    assert len(_OP_TYPE_LABEL) == 8


# ── 补充用例: 证书映射提取（A 优先 + 姓名去空格） ──

class _FakeResult:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class _FakeSession:
    """最小 mock：只提供 async execute(...) -> result.all()（不触真实 DB）。"""

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    async def execute(self, statement: Any) -> _FakeResult:
        return _FakeResult(self._rows)


@pytest.mark.asyncio
async def test_build_certificate_map_a_preferred_and_name_normalized() -> None:
    rows = [
        ("张三", "guardian_b"),
        ("张三", "guardian_a"),  # 同名 A+B → A 优先
        ("王 五", "guardian_a"),  # 姓名含空格 → 去空格
        ("李四", "guardian_b"),
        ("赵六", "guardian_a"),
        ("张三", "guardian_b"),
    ]
    db = _FakeSession(rows)

    cert_map = await build_certificate_map(db)  # type: ignore[arg-type]

    assert cert_map == {"张三": "A证", "王五": "A证", "李四": "B证", "赵六": "A证"}


# ── 同监护人同日时间重叠去重（一次作业多张票，只按最高计） ──

def test_overlapping_tickets_keep_highest_amount() -> None:
    """同日重叠：动火一级(130) > 登高一级(70) → 只留动火，登高进 skipped。"""
    tickets = [
        _ticket(ticket_no="DH-1", ticket_type="hot_work",
                start_time=_dt(2026, 8, 1, 9), end_time=_dt(2026, 8, 1, 17, 5)),
        _ticket(ticket_no="GC-1", ticket_type="height_work",
                start_time=_dt(2026, 8, 1, 9, 12), end_time=_dt(2026, 8, 1, 18)),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 1
    assert plan.records[0].ticket_no == "DH-1"
    assert len(plan.skipped) == 1
    assert plan.skipped[0].ticket_no == "GC-1"
    assert "与DH-1同日时间重叠" in plan.skipped[0].reason


def test_overlapping_chain_component() -> None:
    """A∩B、B∩C 连通归同组（A∩C 可不重叠），只留金额最高。"""
    tickets = [
        # 三张受限空间，默认费率 10/半小时，越长金额越高
        _ticket(ticket_no="SX-A", ticket_type="confined_space",
                start_time=_dt(2026, 8, 1, 8), end_time=_dt(2026, 8, 1, 10)),
        _ticket(ticket_no="SX-B", ticket_type="confined_space",
                start_time=_dt(2026, 8, 1, 9), end_time=_dt(2026, 8, 1, 13)),
        _ticket(ticket_no="SX-C", ticket_type="confined_space",
                start_time=_dt(2026, 8, 1, 12), end_time=_dt(2026, 8, 1, 14)),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 1
    assert plan.records[0].ticket_no == "SX-B"  # 4h > 2h
    assert {s.ticket_no for s in plan.skipped} == {"SX-A", "SX-C"}


def test_same_day_non_overlap_kept_all() -> None:
    """同日先后不重叠 → 全部保留。"""
    tickets = [
        _ticket(ticket_no="M-1",
                start_time=_dt(2026, 8, 1, 8), end_time=_dt(2026, 8, 1, 10)),
        _ticket(ticket_no="M-2",
                start_time=_dt(2026, 8, 1, 10), end_time=_dt(2026, 8, 1, 12)),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 2
    assert plan.skipped == []


def test_overlap_grouping_is_per_guardian_and_day() -> None:
    """不同监护人/不同日不互相影响。"""
    tickets = [
        _ticket(ticket_no="P-1", guardian="张三",
                start_time=_dt(2026, 8, 1, 8), end_time=_dt(2026, 8, 1, 12)),
        _ticket(ticket_no="P-2", guardian="李四",
                start_time=_dt(2026, 8, 1, 8), end_time=_dt(2026, 8, 1, 12)),
        _ticket(ticket_no="P-3", guardian="张三",
                start_time=_dt(2026, 8, 2, 8), end_time=_dt(2026, 8, 2, 12)),
    ]

    plan = SubsidyPlanBuilder.build(tickets, CERT_MAP, "环保", 2026, 8)

    assert plan.matched_tickets == 3
    assert plan.skipped == []


# ── 发酵部门受限空间：按张计费、不参与重叠去重 ──

def test_ferment_confined_space_not_deduped() -> None:
    """发酵工程部受限空间：同日重叠不参与去重 → 全部保留（每张 30 元）。"""
    tickets = [
        _ticket(ticket_no="SX-F-1", ticket_type="confined_space", apply_unit="发酵工程部",
                start_time=_dt(2026, 8, 1, 8), end_time=_dt(2026, 8, 1, 10)),
        _ticket(ticket_no="SX-F-2", ticket_type="confined_space", apply_unit="发酵工程部",
                start_time=_dt(2026, 8, 1, 9), end_time=_dt(2026, 8, 1, 12)),
    ]
    plan = SubsidyPlanBuilder.build(tickets, {"张三": "A证"}, "发酵工程部", 2026, 8)
    assert plan.matched_tickets == 2       # 不去重
    assert plan.skipped == []
    # 非发酵部门受限空间仍参与去重（重叠只保留一张）
    tickets2 = [
        _ticket(ticket_no="SX-O-1", ticket_type="confined_space", apply_unit="环保部",
                start_time=_dt(2026, 8, 1, 8), end_time=_dt(2026, 8, 1, 10)),
        _ticket(ticket_no="SX-O-2", ticket_type="confined_space", apply_unit="环保部",
                start_time=_dt(2026, 8, 1, 9), end_time=_dt(2026, 8, 1, 12)),
    ]
    plan2 = SubsidyPlanBuilder.build(tickets2, {"张三": "A证"}, "环保", 2026, 8)
    assert plan2.matched_tickets == 1
