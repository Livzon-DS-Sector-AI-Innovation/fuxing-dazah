"""WorkTicketRuleEngine 纯函数单测（feature ticket 04）。

覆盖 5 条规则的关键边界：
  - TIME_ORDER：合法链 / 5 种倒挂 / gasless 退化链 / 开始=审批
  - GAS_VALIDITY：30min 边界 / 31min 违规 / 开始前无记录 / gasless 不适用
  - DURATION：动火一级 8h / 8h01s / 二级 72h / 受限 24h / 临电 360h / 高处 72h / 无阈值不适用
  - GAS_INTERVAL：受限 >2.5h（开始→验收）期间覆盖 / ≤2.5h 不适用 / 缺验收时间数据不足 /
                  动火午后（验收跨 12:00）/ 未跨 12:00 不适用
  - PERSONNEL_CERT：触发词精确匹配（气焊（割）触发/塑料焊不触发）/ 三类违规 / 持证通过 /
                    非动火不适用 / 缺动火方式数据不足
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.safety.workticket_review.parser import (
    GasRecord,
    PersonnelRecord,
    WorkTicket,
)
from app.modules.safety.workticket_review.rule_engine import (
    Violation,
    WorkTicketRuleEngine,
)

TZ = ZoneInfo("Asia/Shanghai")
ENGINE = WorkTicketRuleEngine()


def _dt(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=TZ)


def _gas(dt: datetime) -> GasRecord:
    return GasRecord(analysis_time=dt)


def _ticket(
    ticket_type: str,
    *,
    apply_time: datetime | None = None,
    approve_time: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    finish_time: datetime | None = None,
    level: str | None = None,
    gas_analysis: list[GasRecord] | None = None,
    gasless: bool = False,
    work_mode: str | None = None,
    personnel: list[PersonnelRecord] | None = None,
) -> WorkTicket:
    return WorkTicket(
        ticket_type=ticket_type,
        ticket_no="TEST-001",
        apply_time=apply_time,
        approve_time=approve_time,
        start_time=start_time,
        end_time=end_time,
        finish_time=finish_time,
        level=level,
        gas_analysis=gas_analysis or [],
        gasless=gasless,
        work_mode=work_mode,
        personnel=personnel or [],
    )


def _filter(violations: list[Violation], rule_no: str) -> list[Violation]:
    return [v for v in violations if v.rule_no == rule_no]


# ── 规则一：TIME_ORDER ──
def test_time_order_legal_chain() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 20),
        start_time=_dt(2026, 8, 26, 8, 20),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 10, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 10))],
    )
    assert _filter(ENGINE.evaluate(ticket), "TIME_ORDER") == []


def test_time_order_apply_after_gas() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 30),
        approve_time=_dt(2026, 8, 26, 9, 0),
        start_time=_dt(2026, 8, 26, 9, 0),
        end_time=_dt(2026, 8, 26, 11, 0),
        finish_time=_dt(2026, 8, 26, 11, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 0))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "TIME_ORDER")
    assert len(vs) == 1
    assert "申请晚于气体分析" in vs[0].detail


def test_time_order_gas_after_approve() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 10),
        start_time=_dt(2026, 8, 26, 8, 30),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 10, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 20))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "TIME_ORDER")
    assert len(vs) == 1
    assert "气体分析晚于审批" in vs[0].detail


def test_time_order_approve_after_start() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 30),
        start_time=_dt(2026, 8, 26, 8, 20),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 10, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 5))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "TIME_ORDER")
    assert len(vs) == 1
    assert "审批晚于开始" in vs[0].detail


def test_time_order_start_not_before_end() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 20),
        start_time=_dt(2026, 8, 26, 10, 0),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 10, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 10))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "TIME_ORDER")
    assert len(vs) == 1
    assert "开始时间不早于结束时间" in vs[0].detail


def test_time_order_end_after_finish() -> None:
    # 应需求已删除规则一第5条「结束晚于完工验收」，验收仅作数据不复核。
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 20),
        start_time=_dt(2026, 8, 26, 8, 20),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 9, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 10))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "TIME_ORDER")
    assert vs == []  # 结束晚于验收不再判违规


def test_time_order_gasless_chain() -> None:
    ticket = _ticket(
        "height_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 20),
        start_time=_dt(2026, 8, 26, 8, 20),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 10, 30),
        level="1",
        gasless=True,
    )
    assert _filter(ENGINE.evaluate(ticket), "TIME_ORDER") == []


def test_time_order_equal_approve_start_is_legal() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 20),
        start_time=_dt(2026, 8, 26, 8, 20),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 10, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 10))],
    )
    assert _filter(ENGINE.evaluate(ticket), "TIME_ORDER") == []


def test_time_order_gas_after_start_not_time_order() -> None:
    # 气体分析晚于开始（gas > start）：规则一仅比较相邻节点（申请-气体-审批-开始-结束-验收），
    # 不直接比较 气体↔开始，因此不应判 TIME_ORDER；该情形应由 GAS_VALIDITY 兜底。
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 8, 0),
        approve_time=_dt(2026, 8, 26, 8, 20),
        start_time=_dt(2026, 8, 26, 8, 20),
        end_time=_dt(2026, 8, 26, 10, 0),
        finish_time=_dt(2026, 8, 26, 10, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 9, 0))],  # 晚于开始
    )
    vs = ENGINE.evaluate(ticket)
    assert _filter(vs, "TIME_ORDER") == []
    assert any(
        v.rule_no == "GAS_VALIDITY" and "无有效气体分析记录" in v.detail for v in vs
    )


# ── 规则二：GAS_VALIDITY ──
def test_gas_validity_30min_pass() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 9, 0),
        approve_time=_dt(2026, 8, 26, 9, 50),
        start_time=_dt(2026, 8, 26, 10, 0),
        end_time=_dt(2026, 8, 26, 11, 0),
        finish_time=_dt(2026, 8, 26, 11, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 9, 30))],
    )
    assert _filter(ENGINE.evaluate(ticket), "GAS_VALIDITY") == []


def test_gas_validity_31min_violation() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 9, 0),
        approve_time=_dt(2026, 8, 26, 9, 50),
        start_time=_dt(2026, 8, 26, 10, 0),
        end_time=_dt(2026, 8, 26, 11, 0),
        finish_time=_dt(2026, 8, 26, 11, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 9, 29))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_VALIDITY")
    assert len(vs) == 1
    assert "超过 30 分钟" in vs[0].detail


def test_gas_validity_no_record_before_start() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 9, 0),
        approve_time=_dt(2026, 8, 26, 9, 50),
        start_time=_dt(2026, 8, 26, 10, 0),
        end_time=_dt(2026, 8, 26, 11, 0),
        finish_time=_dt(2026, 8, 26, 11, 30),
        level="1",
        gas_analysis=[],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_VALIDITY")
    assert len(vs) == 1
    assert "无有效气体分析记录" in vs[0].detail


def test_gas_validity_gasless_not_applicable() -> None:
    ticket = _ticket(
        "height_work",
        start_time=_dt(2026, 8, 26, 10, 0),
        end_time=_dt(2026, 8, 26, 11, 0),
        gasless=True,
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_VALIDITY")
    assert len(vs) == 1
    assert vs[0].not_applicable is True


# ── 规则三：DURATION ──
def test_duration_hot_work_grade1_8h_pass() -> None:
    ticket = _ticket(
        "hot_work",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 16, 0),
        level="1",
    )
    assert _filter(ENGINE.evaluate(ticket), "DURATION") == []


def test_duration_hot_work_8h_plus_1s_violation() -> None:
    ticket = _ticket(
        "hot_work",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 16, 0, 1),
        level="1",
    )
    vs = _filter(ENGINE.evaluate(ticket), "DURATION")
    assert len(vs) == 1
    assert "超过上限" in vs[0].detail


def test_duration_hot_work_grade2_72h_pass() -> None:
    ticket = _ticket(
        "hot_work",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 29, 8, 0),
        level="2",
    )
    assert _filter(ENGINE.evaluate(ticket), "DURATION") == []


def test_duration_confined_24h_pass() -> None:
    ticket = _ticket(
        "confined_space",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 27, 8, 0),
    )
    assert _filter(ENGINE.evaluate(ticket), "DURATION") == []


def test_duration_temporary_electricity_360h_pass() -> None:
    ticket = _ticket(
        "temporary_electricity",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 9, 10, 8, 0),
    )
    assert _filter(ENGINE.evaluate(ticket), "DURATION") == []


def test_duration_height_work_72h_pass() -> None:
    ticket = _ticket(
        "height_work",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 29, 8, 0),
        gasless=True,
    )
    assert _filter(ENGINE.evaluate(ticket), "DURATION") == []


def test_duration_no_threshold_types_not_applicable() -> None:
    for ticket_type in ("lifting", "excavation", "road_breaking", "blind_plate"):
        ticket = _ticket(
            ticket_type,
            start_time=_dt(2026, 8, 26, 8, 0),
            end_time=_dt(2026, 8, 26, 18, 0),
            gasless=True,
        )
        vs = _filter(ENGINE.evaluate(ticket), "DURATION")
        assert len(vs) == 1, ticket_type
        assert vs[0].not_applicable is True, ticket_type
        assert "无时长上限" in vs[0].detail, ticket_type


# ── 规则四：GAS_INTERVAL（受限·监测频率 + 动火·午后检测，口径=开始→完工验收） ──
def test_gas_interval_confined_short_duration_no_record_not_applicable() -> None:
    # 开始→验收 1.5h ≤ 2.5h：不要求期间检测记录（作业前分析已覆盖）
    ticket = _ticket(
        "confined_space",
        apply_time=_dt(2026, 8, 26, 7, 50),
        approve_time=_dt(2026, 8, 26, 7, 55),
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 9, 30),
        finish_time=_dt(2026, 8, 26, 9, 30),
        gas_analysis=[_gas(_dt(2026, 8, 26, 7, 45))],  # 仅作业前分析
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert vs[0].not_applicable is True
    assert "未超过 2.5 小时" in vs[0].detail


def test_gas_interval_confined_exactly_2_5h_no_record_not_applicable() -> None:
    # 开始→验收恰好 2.5 小时：未超过 2.5h，不要求期间检测记录
    ticket = _ticket(
        "confined_space",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 10, 30),
        finish_time=_dt(2026, 8, 26, 10, 30),
        gas_analysis=[_gas(_dt(2026, 8, 26, 7, 45))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert vs[0].not_applicable is True


def test_gas_interval_confined_gap_over_2h_violation() -> None:
    ticket = _ticket(
        "confined_space",
        apply_time=_dt(2026, 8, 26, 7, 50),
        approve_time=_dt(2026, 8, 26, 7, 55),
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 12, 0),
        finish_time=_dt(2026, 8, 26, 12, 30),
        gas_analysis=[
            _gas(_dt(2026, 8, 26, 8, 0)),
            _gas(_dt(2026, 8, 26, 10, 30)),
            _gas(_dt(2026, 8, 26, 12, 0)),
        ],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert "超过 2 小时" in vs[0].detail


def test_gas_interval_confined_no_record_violation() -> None:
    ticket = _ticket(
        "confined_space",
        apply_time=_dt(2026, 8, 26, 7, 50),
        approve_time=_dt(2026, 8, 26, 7, 55),
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 12, 0),
        finish_time=_dt(2026, 8, 26, 12, 30),
        gas_analysis=[_gas(_dt(2026, 8, 26, 7, 45))],  # 作业前分析，不计入作业期间
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert "作业期间无气体分析记录" in vs[0].detail
    assert "超过 2.5 小时" in vs[0].detail


def test_gas_interval_confined_single_record_gap_to_finish_violation() -> None:
    # 3h 作业仅开始后 0.5h 一次记录：末条记录→完工验收超过 2h → 违规
    ticket = _ticket(
        "confined_space",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 11, 0),
        finish_time=_dt(2026, 8, 26, 11, 0),
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 30))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert "超过 2 小时" in vs[0].detail


def test_gas_interval_confined_full_coverage_pass() -> None:
    # 4h 作业记录覆盖全程（含首尾边界），间隔均 ≤ 2h → 合格
    ticket = _ticket(
        "confined_space",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 12, 0),
        finish_time=_dt(2026, 8, 26, 12, 0),
        gas_analysis=[
            _gas(_dt(2026, 8, 26, 8, 0)),
            _gas(_dt(2026, 8, 26, 9, 0)),
            _gas(_dt(2026, 8, 26, 11, 0)),
            _gas(_dt(2026, 8, 26, 12, 0)),
        ],
    )
    assert _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL") == []


def test_gas_interval_confined_missing_finish_data_insufficient() -> None:
    # 缺少完工验收时间：数据不足（无论时长如何，先报告缺字段）
    ticket = _ticket(
        "confined_space",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 12, 0),
        gas_analysis=[],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert vs[0].not_applicable is False
    assert "数据不足" in vs[0].detail
    assert "finish_time" in vs[0].detail


def test_gas_interval_hot_work_noon_has_record_pass() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 7, 30),
        approve_time=_dt(2026, 8, 26, 7, 45),
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 18, 0),
        finish_time=_dt(2026, 8, 26, 18, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 13, 0))],
    )
    assert _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL") == []


def test_gas_interval_hot_work_noon_no_record_violation() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 7, 30),
        approve_time=_dt(2026, 8, 26, 7, 45),
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 18, 0),
        finish_time=_dt(2026, 8, 26, 18, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 30))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert "午后无气体分析记录" in vs[0].detail


def test_gas_interval_hot_work_not_cross_noon_not_applicable() -> None:
    ticket = _ticket(
        "hot_work",
        apply_time=_dt(2026, 8, 26, 7, 30),
        approve_time=_dt(2026, 8, 26, 7, 45),
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 11, 0),
        finish_time=_dt(2026, 8, 26, 11, 30),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 8, 30))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert vs[0].not_applicable is True
    assert "未覆盖午后期" in vs[0].detail


def test_gas_interval_hot_work_missing_finish_data_insufficient() -> None:
    # 缺少完工验收时间：数据不足（无法判断验收是否覆盖 12:00 后）
    ticket = _ticket(
        "hot_work",
        start_time=_dt(2026, 8, 26, 8, 0),
        end_time=_dt(2026, 8, 26, 18, 0),
        level="1",
        gas_analysis=[_gas(_dt(2026, 8, 26, 13, 0))],
    )
    vs = _filter(ENGINE.evaluate(ticket), "GAS_INTERVAL")
    assert len(vs) == 1
    assert vs[0].not_applicable is False
    assert "数据不足" in vs[0].detail
    assert "finish_time" in vs[0].detail


# ── 规则五：PERSONNEL_CERT 人员证件判定 ──
def _person(role: str, name: str = "", cert_no: str = "") -> PersonnelRecord:
    return PersonnelRecord(role=role, name=name, cert_no=cert_no)


def test_personnel_cert_non_hot_work_not_applicable() -> None:
    ticket = _ticket("height_work", work_mode="电焊", personnel=[])
    (v,) = _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT")
    assert v.not_applicable is True


def test_personnel_cert_mode_missing_insufficient() -> None:
    ticket = _ticket("hot_work", work_mode=None)
    (v,) = _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT")
    assert v.not_applicable is False
    assert v.detail.startswith("数据不足")


def test_personnel_cert_mode_without_weld_not_applicable() -> None:
    ticket = _ticket("hot_work", work_mode="角磨机,电钻,切割机", personnel=[])
    (v,) = _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT")
    assert v.not_applicable is True


def test_personnel_cert_plastic_weld_not_triggered() -> None:
    """'塑料焊' 不在 电焊/氩弧焊/气焊（割） 之列，不得泛匹配'焊'字误触发。"""
    ticket = _ticket("hot_work", work_mode="塑料焊", personnel=[])
    (v,) = _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT")
    assert v.not_applicable is True


def test_personnel_cert_gas_cut_triggered() -> None:
    """显示值 '气焊（割）' 含 '气焊' 子串，应触发。"""
    ticket = _ticket("hot_work", work_mode="气焊（割）,角磨机", personnel=[])
    (v,) = _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT")
    assert v.not_applicable is False
    assert v.detail.startswith("数据不足") is False
    assert "未登记" in v.detail or "证件" in v.detail


def test_personnel_cert_certified_pass() -> None:
    """特种作业人员持证 + 普工无证 → 通过（普工不参与判定）。"""
    ticket = _ticket(
        "hot_work",
        work_mode="电焊,角磨机",
        personnel=[
            _person("特种作业人员", "刘飞云", "T410522198402010817"),
            _person("普工", "吴志刚"),
        ],
    )
    assert _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT") == []


def test_personnel_cert_empty_cert_violation_lists_names() -> None:
    ticket = _ticket(
        "hot_work",
        work_mode="电焊,角磨机",
        personnel=[
            _person("特种作业人员", "郑德干"),
            _person("普工", "吴志刚"),
        ],
    )
    (v,) = _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT")
    assert v.not_applicable is False
    assert "郑德干" in v.detail
    assert "吴志刚" not in v.detail


def test_personnel_cert_no_specialist_row_violation() -> None:
    ticket = _ticket(
        "hot_work",
        work_mode="氩弧焊",
        personnel=[_person("普工", "吴志刚")],
    )
    (v,) = _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT")
    assert v.not_applicable is False
    assert "未登记" in v.detail


def test_personnel_cert_no_table_violation() -> None:
    ticket = _ticket("hot_work", work_mode="电焊,角磨机", personnel=[])
    (v,) = _filter(ENGINE.evaluate(ticket), "PERSONNEL_CERT")
    assert v.not_applicable is False
    assert "未登记" in v.detail
