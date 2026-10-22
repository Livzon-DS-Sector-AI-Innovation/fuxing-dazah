"""判定引擎（S1 体系标准符合性核查）——纯函数，today 可注入。

四态（DESIGN §3.4）：
- ok          达标（计数下限型满足即达；比率/上限型周期满且满足）
- in_progress 进行中（周期未满未满足；period_end 型周期未满一律进行中）
- missed      未达标（周期已满未满足；人工项勾「未完成」）
- no_data     无数据（源未接入/指标未注册/人工项「不适用」）——绝不与未达标混算

口径单点：window_for 的周期窗口、compare 的比较符解析都在本模块；
metrics.py 的取数器与 page.py 的聚合只消费这里的判定结果。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

ST_OK = "ok"
ST_IN_PROGRESS = "in_progress"
ST_MISSED = "missed"
ST_NO_DATA = "no_data"

logger = logging.getLogger(__name__)

PERIOD_LONG_CYCLE = "长周期(3年)"
LONG_CYCLE_DAYS = 3 * 365


@dataclass(frozen=True)
class StandardRow:
    """核查表一行（中文列名已在 page 层解析为业务字段）。"""

    record_id: str
    no: str
    year: str
    clause: str
    basis: str | None = None
    element: str | None = None
    metric_key: str | None = None
    operator: str | None = None  # ≥ / ≤ / =
    target_value: float | None = None
    unit: str | None = None
    period: str | None = None  # 年度 / 半年 / 季度 / 月度
    department: tuple[str, ...] = ()
    owner: str | None = None
    last_done_on: date | None = None  # 长周期项锚点（「上次完成日期」）
    manual_result: str | None = None  # 已完成 / 未完成 / 不适用


@dataclass(frozen=True)
class MetricOutcome:
    """取数器输出：值 / 无数据原因 / 证据摘要。"""

    value: float | None = None
    no_data_reason: str | None = None
    evidence: tuple[dict[str, str], ...] = ()

    @property
    def is_no_data(self) -> bool:
        return self.value is None


@dataclass(frozen=True)
class MetricSpec:
    """指标注册表条目（settle 见 metrics.py）。"""

    key: str
    label: str
    unit: str
    settle: str  # "early" | "period_end"


@dataclass(frozen=True)
class PeriodWindow:
    start: date
    end: date  # 窗口最后一日（含）

    def ended(self, today: date) -> bool:
        return today > self.end

    @property
    def key(self) -> str:
        y = self.start.year
        if self.start.month == 1 and self.end.month == 12:
            return str(y)
        if self.start.month == 1 and self.end.month == 6:
            return f"{y}H1"
        if self.start.month == 7 and self.end.month == 12:
            return f"{y}H2"
        if self.start.day == 1 and self.end.month == self.start.month + 2:
            return f"{y}Q{(self.start.month - 1) // 3 + 1}"
        return f"{y}-{self.start.month:02d}"


@dataclass(frozen=True)
class Verdict:
    status: str
    actual_display: str | None = None
    residual_days: int | None = None  # 进行中距周期末天数
    note: str | None = None


def _month_end(y: int, m: int) -> date:
    # 下月 1 日的前一天（12 月单独处理避免跨年）
    return date(y, 12, 31) if m == 12 else date(y, m + 1, 1) - timedelta(days=1)


def window_for(period: str, today: date) -> PeriodWindow:
    """周期窗口（北京时间日界语义，调用方保证 today 已是北京日）。"""
    y = today.year
    if period == "年度":
        return PeriodWindow(date(y, 1, 1), date(y, 12, 31))
    if period == "半年":
        if today.month <= 6:
            return PeriodWindow(date(y, 1, 1), date(y, 6, 30))
        return PeriodWindow(date(y, 7, 1), date(y, 12, 31))
    if period == "季度":
        q_start = (today.month - 1) // 3 * 3 + 1
        q_end_month = q_start + 2
        return PeriodWindow(date(y, q_start, 1), _month_end(y, q_end_month))
    if period == "月度":
        return PeriodWindow(date(y, today.month, 1), _month_end(y, today.month))
    # 未知周期值（清单维护者手误）→ 退化为年度窗口并告警，判定不炸
    logger.warning("未知周期值 %r，退化为年度窗口", period)
    return PeriodWindow(date(y, 1, 1), date(y, 12, 31))


def _compare(value: float, operator: str | None, target: float | None) -> bool:
    if target is None:
        return False
    if operator == "≤":
        return value <= target
    if operator == "=":
        return value == target
    return value >= target  # 缺省按 ≥（schema 比较符仅 ≥/≤/=）


def judge(
    row: StandardRow,
    spec: MetricSpec | None,
    outcome: MetricOutcome,
    window: PeriodWindow,
    today: date,
) -> Verdict:
    """单条标准的四态判定。spec=None 且行有 metric_key 表示未注册指标。

    window 由调用方注入（与评估日解耦）：实时视图传 window_for(period, today)
    ——窗口恒含 today，自动项不会出现 missed（「还没完成」以 in_progress 呈现，
    历史欠账由二期 snapshot 定格时传历史窗口判 ok/missed）。人工项不受窗口影响。
    """
    unit = row.unit or ""

    if not row.metric_key and row.period == PERIOD_LONG_CYCLE:
        # 长周期（3 年）项：锚点=「上次完成日期」，周期常开无进行中态
        if row.last_done_on is None:
            return Verdict(ST_MISSED, note="未登记上次完成日期")
        elapsed = (today - row.last_done_on).days
        display = f"上次 {row.last_done_on.isoformat()}"
        if elapsed <= LONG_CYCLE_DAYS:
            return Verdict(ST_OK, actual_display=display)
        return Verdict(ST_MISSED, actual_display=display, note="距上次已超 3 年")

    if not row.metric_key:
        manual = row.manual_result
        if manual == "已完成":
            return Verdict(ST_OK, actual_display="已完成")
        if manual == "未完成":
            return Verdict(ST_MISSED, actual_display="未完成")
        if manual == "不适用":
            return Verdict(ST_NO_DATA, note="不适用")
        return Verdict(ST_IN_PROGRESS, note="待人工核查")

    if spec is None or outcome.is_no_data:
        reason = outcome.no_data_reason or "指标未注册"
        return Verdict(ST_NO_DATA, note=reason)

    display = f"{outcome.value:g}{unit}"
    satisfied = _compare(outcome.value, row.operator, row.target_value)

    if satisfied and spec.settle == "early":
        return Verdict(ST_OK, actual_display=display)
    if window.ended(today):
        return Verdict(
            ST_OK if satisfied else ST_MISSED,
            actual_display=display,
        )
    note = "当前达标" if satisfied else None
    return Verdict(
        ST_IN_PROGRESS,
        actual_display=display,
        residual_days=(window.end - today).days,
        note=note,
    )
