"""判定引擎四态测试（S1 体系标准符合性核查引擎）。

口径：docs/DESIGN-安全目标责任与绩效模块-体系标准符合性核查引擎-20261021.md §3.4。
窗口由调用方注入（与评估日解耦）：实时视图窗口恒含评估日（自动项无 missed），
ended 分支供二期 snapshot 定格（历史窗口）复用——两组用例分开钉死。
纯函数 today/窗口可注入，全部用固定日期，不依赖真实时钟。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.standard_check.engine import (
    ST_IN_PROGRESS,
    ST_MISSED,
    ST_NO_DATA,
    ST_OK,
    MetricOutcome,
    MetricSpec,
    PeriodWindow,
    StandardRow,
    judge,
    window_for,
)

TODAY = date(2026, 10, 21)


def _row(**kw) -> StandardRow:
    base = dict(
        record_id="r1",
        no="D6-01",
        year="2026",
        clause="综合或专项应急预案演练每半年≥1次",
        basis=None,
        element="应急管理",
        metric_key="drill.count.comprehensive_or_special",
        operator="≥",
        target_value=1.0,
        unit="次",
        period="半年",
        department=("安环部",),
        owner=None,
        last_done_on=None,
        manual_result=None,
    )
    base.update(kw)
    return StandardRow(**base)


def _spec(**kw) -> MetricSpec:
    base = dict(
        key="drill.count.comprehensive_or_special",
        label="综合/专项演练次数",
        unit="次",
        settle="early",
    )
    base.update(kw)
    return MetricSpec(**base)


class TestWindow:
    def test_year_window(self) -> None:
        w = window_for("年度", TODAY)
        assert (w.start, w.end) == (date(2026, 1, 1), date(2026, 12, 31))

    def test_half_year_window(self) -> None:
        w = window_for("半年", TODAY)
        assert (w.start, w.end) == (date(2026, 7, 1), date(2026, 12, 31))
        assert window_for("半年", date(2026, 3, 1)).start == date(2026, 1, 1)

    def test_quarter_window(self) -> None:
        w = window_for("季度", TODAY)
        assert (w.start, w.end) == (date(2026, 10, 1), date(2026, 12, 31))

    def test_month_window(self) -> None:
        w = window_for("月度", TODAY)
        assert (w.start, w.end) == (date(2026, 10, 1), date(2026, 10, 31))

    def test_ended_only_after_end(self) -> None:
        assert not window_for("月度", TODAY).ended(TODAY)
        assert window_for("月度", date(2026, 9, 30)).ended(TODAY)

    def test_window_keys(self) -> None:
        assert window_for("年度", TODAY).key == "2026"
        assert window_for("半年", TODAY).key == "2026H2"
        assert window_for("季度", TODAY).key == "2026Q4"
        assert window_for("月度", TODAY).key == "2026-10"


class TestJudgeRealtime:
    """实时视图：窗口=评估日所在周期（恒未满）——自动项只有 ok/in_progress/no_data。"""

    def test_early_settle_satisfied_is_ok(self) -> None:
        v = judge(
            _row(), _spec(), MetricOutcome(value=2.0),
            window_for("半年", TODAY), TODAY,
        )
        assert v.status == ST_OK
        assert v.actual_display == "2次"

    def test_early_settle_unsatisfied_is_in_progress(self) -> None:
        v = judge(
            _row(), _spec(), MetricOutcome(value=0.0),
            window_for("半年", TODAY), TODAY,
        )
        assert v.status == ST_IN_PROGRESS
        assert v.residual_days == (date(2026, 12, 31) - TODAY).days
        assert v.note is None

    def test_period_end_is_in_progress_even_if_satisfied(self) -> None:
        """比率/上限型：周期未满一律进行中（防中途达标假象），note 标当前达标。"""
        row = _row(metric_key="hazard.on_time_close_rate", operator="≥",
                   target_value=95.0, unit="%", period="季度")
        spec = _spec(key="hazard.on_time_close_rate", settle="period_end", unit="%")
        v = judge(row, spec, MetricOutcome(value=100.0), window_for("季度", TODAY), TODAY)
        assert v.status == ST_IN_PROGRESS
        assert v.note == "当前达标"
        assert v.actual_display == "100%"

    def test_no_data_never_missed(self) -> None:
        """源未接入 ≠ 未达标（冤案零容忍）。"""
        v = judge(
            _row(metric_key="training.completion_rate"),
            _spec(key="training.completion_rate"),
            MetricOutcome(no_data_reason="training 域未接入"),
            window_for("年度", TODAY), TODAY,
        )
        assert v.status == ST_NO_DATA
        assert "training" in v.note

    def test_unregistered_metric_key_is_no_data(self) -> None:
        v = judge(
            _row(metric_key="no.such.key"), None,
            MetricOutcome(no_data_reason="指标未注册"),
            window_for("年度", TODAY), TODAY,
        )
        assert v.status == ST_NO_DATA


class TestJudgeFrozen:
    """ended 分支：供二期 snapshot 定格（历史窗口+晚于窗口末的评估日）复用。"""

    def test_early_settle_ended_unsatisfied_is_missed(self) -> None:
        """2026H1 窗口（1-1~6-30）已满仍为 0 → 未达标。"""
        v = judge(
            _row(period="半年"), _spec(),
            MetricOutcome(value=0.0),
            window_for("半年", date(2026, 6, 15)), date(2026, 7, 10),
        )
        assert v.status == ST_MISSED

    def test_period_end_ended(self) -> None:
        row = _row(metric_key="hazard.on_time_close_rate", operator="≥",
                   target_value=95.0, unit="%", period="季度")
        spec = _spec(key="hazard.on_time_close_rate", settle="period_end", unit="%")
        q3 = window_for("季度", date(2026, 9, 15))
        assert judge(row, spec, MetricOutcome(value=97.0), q3, date(2026, 10, 5)).status == ST_OK
        assert judge(row, spec, MetricOutcome(value=80.0), q3, date(2026, 10, 5)).status == ST_MISSED

    def test_operators_le_and_eq(self) -> None:
        row = _row(operator="≤", target_value=0.0, unit="起")
        spec = _spec(key="accident.count", settle="period_end")
        y2026 = window_for("年度", date(2026, 6, 1))
        assert judge(row, spec, MetricOutcome(value=0.0), y2026, date(2027, 1, 2)).status == ST_OK
        assert judge(row, spec, MetricOutcome(value=2.0), y2026, date(2027, 1, 2)).status == ST_MISSED
        row_eq = _row(operator="=", target_value=100.0, unit="%")
        spec_eq = _spec(key="oh.exam_rate", settle="period_end")
        assert judge(row_eq, spec_eq, MetricOutcome(value=100.0), y2026, date(2027, 1, 2)).status == ST_OK
        assert judge(row_eq, spec_eq, MetricOutcome(value=98.0), y2026, date(2027, 1, 2)).status == ST_MISSED


class TestJudgeManual:
    def test_manual_done_is_ok(self) -> None:
        v = judge(
            _row(metric_key=None, manual_result="已完成"), None, MetricOutcome(),
            window_for("年度", TODAY), TODAY,
        )
        assert v.status == ST_OK

    def test_manual_not_done_is_missed(self) -> None:
        v = judge(
            _row(metric_key=None, manual_result="未完成"), None, MetricOutcome(),
            window_for("年度", TODAY), TODAY,
        )
        assert v.status == ST_MISSED

    def test_manual_na_is_no_data(self) -> None:
        """不适用不计入符合率。"""
        v = judge(
            _row(metric_key=None, manual_result="不适用"), None, MetricOutcome(),
            window_for("年度", TODAY), TODAY,
        )
        assert v.status == ST_NO_DATA

    def test_manual_blank_is_in_progress(self) -> None:
        v = judge(
            _row(metric_key=None, manual_result=None), None, MetricOutcome(),
            window_for("年度", TODAY), TODAY,
        )
        assert v.status == ST_IN_PROGRESS
        assert "待人工核查" in v.note


class TestJudgeLongCycle:
    """长周期（3 年）项：锚点=上次完成日期，周期常开。"""

    def _lc(self, last: date | None) -> StandardRow:
        return _row(metric_key=None, period="长周期(3年)", last_done_on=last, manual_result=None)

    def test_within_three_years_is_ok(self) -> None:
        v = judge(self._lc(date(2024, 6, 1)), None, MetricOutcome(), window_for("年度", TODAY), TODAY)
        assert v.status == ST_OK
        assert "2024-06-01" in v.actual_display

    def test_over_three_years_is_missed(self) -> None:
        v = judge(self._lc(date(2023, 1, 1)), None, MetricOutcome(), window_for("年度", TODAY), TODAY)
        assert v.status == ST_MISSED
        assert "超 3 年" in v.note

    def test_blank_anchor_is_missed(self) -> None:
        v = judge(self._lc(None), None, MetricOutcome(), window_for("年度", TODAY), TODAY)
        assert v.status == ST_MISSED
        assert "未登记" in v.note
