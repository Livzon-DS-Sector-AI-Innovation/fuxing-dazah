"""危化品库存每日分析日报（超量 + 昨日环比 + 主要危化品汇总 + 结论）。

设计（2026-08-31 业务要求，2026-09-02 优化）：
- 取消禁忌混存分析，仅分析库存量风险；
- 🔴 库存超量：实际库存超过设定限量；按「超限倍数」（当前库存÷限量）降序，
  同倍数按超量吨数降序；附部门维度汇总与重点问题小结；
- 🟠/🔵 库存急剧上升/下降：较昨日的变化达到「变化比例 + 变化量」双阈值
  （阈值可经环境变量配置，默认 比例≥30% 且 绝对量≥1.0 T，避免正常波动误报）；
- 汇总当前库存量 Top N 的危化品（按物料名聚合全公司总量）及较昨日变化/趋势；
  另附「数据状态」列：值较昨日无变化且今日无任何数据写入（updated_at 未刷新）的行
  标记「未更新」，区分「真无变化」与「部门未报数」。

纯计算 + 纯渲染，无 IO；昨日数据由调用方（daily_job）从快照表读取传入。
"""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time as dtime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.modules.safety.schemas.chemical_inventory import CHEMICAL_DEPARTMENT_LABELS

# 急剧变化阈值（环境变量可覆盖）
SURGE_RATIO_DEFAULT = "0.30"          # 变化比例 ≥ 30%
SURGE_ABS_T_DEFAULT = "1.0"           # 且 绝对变化量 ≥ 1.0 T
SURGE_RATIO_ENV = "SAFETY_CHEMICAL_INVENTORY_SURGE_RATIO"
SURGE_ABS_T_ENV = "SAFETY_CHEMICAL_INVENTORY_SURGE_ABS_T"

# 汇总表展示条数（按今日库存量取 Top）
SUMMARY_TOP_N = 15


def get_surge_thresholds() -> tuple[Decimal, Decimal]:
    """返回 (变化比例阈值, 绝对变化量阈值(T))，读取环境变量，非法值回退默认。"""
    def _parse(env: str, default: str) -> Decimal:
        try:
            return Decimal(str(os.getenv(env, default))).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        except Exception:  # noqa: BLE001
            return Decimal(default)

    ratio = _parse(SURGE_RATIO_ENV, SURGE_RATIO_DEFAULT)
    abs_t = _parse(SURGE_ABS_T_ENV, SURGE_ABS_T_DEFAULT)
    return ratio, abs_t


def _beijing_today_start_utc() -> datetime:
    """今日（北京时间）零点对应的 UTC 时刻——「今日有数据写入」的判定基准。"""
    now_bj = datetime.now(UTC) + timedelta(hours=8)
    return datetime.combine(now_bj.date(), dtime.min, tzinfo=UTC) - timedelta(hours=8)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


@dataclass
class OverLimitItem:
    """单条记录超量（超量按记录行判定：每条记录有独立限量）。"""

    material_name: str
    department: str
    storage_location: str
    total: Decimal
    limit: Decimal
    over: Decimal
    ratio: Decimal = Decimal("0")  # 超限倍数 total/limit

    @property
    def department_label(self) -> str:
        """部门枚举 → 中文名，未收录的枚举原样显示。"""
        return CHEMICAL_DEPARTMENT_LABELS.get(self.department, self.department) if self.department else "部门未填"


@dataclass
class DeptOverSummary:
    """部门维度超量汇总（按超量项数降序、同数按部门内最高倍数降序）。"""

    department: str
    items: list[OverLimitItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def department_label(self) -> str:
        return CHEMICAL_DEPARTMENT_LABELS.get(self.department, self.department) if self.department else "部门未填"

    @property
    def max_ratio(self) -> Decimal:
        return max(i.ratio for i in self.items)


@dataclass
class MaterialChange:
    """某物料当日 vs 昨日的变化（物料名聚合全公司总量）。

    prev/cur/delta 为 None 表示无环比数据（首个快照日）。
    """

    material_name: str
    prev: Decimal | None
    cur: Decimal
    delta: Decimal | None = None
    ratio: Decimal | None = None  # delta/prev，prev<=0 时为 None
    not_updated: bool = False     # 值无变化且今日无任何数据写入（部门未报数）


@dataclass
class DailyAnalysis:
    """日报分析结果。"""

    report_date: date
    has_prev: bool = True                    # 昨日是否有快照（首日 False）
    over_limit_items: list[OverLimitItem] = field(default_factory=list)
    dept_over_summary: list[DeptOverSummary] = field(default_factory=list)
    surge: list[MaterialChange] = field(default_factory=list)
    decline: list[MaterialChange] = field(default_factory=list)
    summary: list[MaterialChange] = field(default_factory=list)

    @property
    def over_limit_count(self) -> int:
        return len(self.over_limit_items)

    @property
    def surge_count(self) -> int:
        return len(self.surge)

    @property
    def decline_count(self) -> int:
        return len(self.decline)

    def has_risk(self) -> bool:
        return bool(self.over_limit_items or self.surge or self.decline)


def _fmt_t(value: Decimal | None) -> str:
    """吨数值，最多 4 位小数并去掉尾部 0（78.916 / 39 / 40.0392）。"""
    if value is None:
        return "-"
    v = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    s = format(v, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _fmt_delta(value: Decimal | None) -> str:
    """带符号变化量，+10 / -20.05；None（无环比）显示 —。"""
    if value is None:
        return "—"
    if value == 0:
        return "0"
    sign = "+" if value > 0 else ""
    return f"{sign}{_fmt_t(value)}"


def _fmt_ratio(ratio: Decimal | None) -> str:
    if ratio is None:
        return ""
    return f"({ratio * 100:.0f}%)"


def _fmt_times(ratio: Decimal) -> str:
    """超限倍数，保留 2 位小数（1.80 / 5.00）。"""
    return format(ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def compute_daily_analysis(
    records: list[Any],
    prev_snapshot_rows: list[Any],
    *,
    surge_ratio: Decimal | None = None,
    surge_abs_t: Decimal | None = None,
) -> DailyAnalysis:
    """对当日记录做超量判定 + 与昨日快照环比，产出 DailyAnalysis。

    Args:
        records: 当前 ChemicalInventoryRecord 列表（全量、未删除）。
        prev_snapshot_rows: 昨日 daily 快照行（material_name/total_quantity_t 可用）；
            空列表表示首个快照日（无昨日数据）。
        surge_ratio/surge_abs_t: 急剧变化阈值；None 时从环境变量读取。
    """
    if surge_ratio is None or surge_abs_t is None:
        default_ratio, default_abs = get_surge_thresholds()
        surge_ratio = surge_ratio if surge_ratio is not None else default_ratio
        surge_abs_t = surge_abs_t if surge_abs_t is not None else default_abs

    # ── 今日按物料名聚合（同一危化品多处存放合计）──
    today_totals: dict[str, Decimal] = {}
    for rec in records:
        name = getattr(rec, "material_name", "") or "?"
        total = _to_decimal(getattr(rec, "total_quantity_t", None)) or Decimal("0")
        today_totals[name] = today_totals.get(name, Decimal("0")) + total

    # ── 数据新鲜度：台账 updated_at 仅在值变化时刷新；今日（北京）零点后没有任何
    # 记录刷新的物料视为「未更新」（0 变化可能是部门没报数，而非真无变化）──
    today_start = _beijing_today_start_utc()
    updated_names: set[str] = set()
    for rec in records:
        ts = getattr(rec, "updated_at", None)
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts >= today_start:
            updated_names.add(getattr(rec, "material_name", "") or "?")

    # ── 超量：按记录行判定（限量是行级字段）──
    over_items: list[OverLimitItem] = []
    for rec in records:
        total = _to_decimal(getattr(rec, "total_quantity_t", None))
        limit = _to_decimal(getattr(rec, "max_limit", None))
        if total is None or limit is None or limit <= 0 or total <= limit:
            continue
        over_items.append(OverLimitItem(
            material_name=getattr(rec, "material_name", "") or "?",
            department=getattr(rec, "department", "") or "",
            storage_location=getattr(rec, "storage_location", "") or "",
            total=total,
            limit=limit,
            over=total - limit,
            ratio=total / limit,
        ))
    # 按超限倍数降序，同倍数按超量吨数降序
    over_items.sort(key=lambda x: (-x.ratio, -x.over))

    # ── 部门维度超量汇总：项数降序，同数按部门内最高倍数降序 ──
    by_dept: dict[str, list[OverLimitItem]] = defaultdict(list)
    for item in over_items:
        by_dept[item.department].append(item)
    dept_over_summary = [DeptOverSummary(department=dept, items=items) for dept, items in by_dept.items()]
    dept_over_summary.sort(key=lambda d: (-d.count, -d.max_ratio))

    analysis = DailyAnalysis(report_date=date.today(), has_prev=bool(prev_snapshot_rows))

    # ── 昨日按物料名聚合 ──
    prev_totals: dict[str, Decimal] = {}
    for row in prev_snapshot_rows:
        name = getattr(row, "material_name", "") or "?"
        total = _to_decimal(getattr(row, "total_quantity_t", None)) or Decimal("0")
        prev_totals[name] = prev_totals.get(name, Decimal("0")) + total

    changes: list[MaterialChange] = []
    if analysis.has_prev:
        for name in sorted(set(today_totals) | set(prev_totals)):
            prev = prev_totals.get(name, Decimal("0"))
            cur = today_totals.get(name, Decimal("0"))
            delta = cur - prev
            if delta == 0:
                continue
            # ratio 存原始倍数（0.5=50%），便于阈值比较与渲染
            ratio_raw = delta / prev if prev > 0 else None
            changes.append(MaterialChange(
                material_name=name, prev=prev, cur=cur, delta=delta, ratio=ratio_raw,
            ))

        # ── 急剧上升/下降：变化比例与变化量双达标 ──
        # prev<=0（新出现物料）时无比例可言，仅按绝对变化量判定
        for chg in changes:
            if chg.delta > 0:
                if chg.delta >= surge_abs_t and (chg.prev <= 0 or chg.ratio >= surge_ratio):
                    analysis.surge.append(chg)
            else:
                if -chg.delta >= surge_abs_t and (chg.prev <= 0 or chg.ratio is not None and -chg.ratio >= surge_ratio):
                    analysis.decline.append(chg)
        analysis.surge.sort(key=lambda x: -x.delta)
        analysis.decline.sort(key=lambda x: x.delta)

    # ── 汇总：今日库存 Top N（含较昨日变化/趋势）──
    by_name = {c.material_name: c for c in changes}
    summary: list[MaterialChange] = []
    for name, total in sorted(today_totals.items(), key=lambda kv: -kv[1]):
        if total <= 0:
            continue
        if name in by_name:
            summary.append(by_name[name])
        else:
            summary.append(MaterialChange(
                material_name=name,
                prev=prev_totals.get(name) if analysis.has_prev else None,
                cur=total,
                delta=Decimal("0") if analysis.has_prev else None,
                ratio=None,
            ))
        if len(summary) >= SUMMARY_TOP_N:
            break

    # 「未更新」标记：值较昨日无变化（或无环比）且今日无任何数据写入
    for chg in summary:
        chg.not_updated = (
            (chg.delta is None or chg.delta == 0)
            and chg.material_name not in updated_names
        )

    analysis.over_limit_items = over_items
    analysis.dept_over_summary = dept_over_summary
    analysis.summary = summary
    return analysis


def _trend(chg: MaterialChange) -> str:
    if chg.delta is None:
        return "—"
    if chg.delta > 0:
        return "↑"
    if chg.delta < 0:
        return "↓"
    return "—"


def render_daily_report(analysis: DailyAnalysis) -> str:
    """渲染日报 Markdown（对齐 2026-08-31 业务示例结构）。"""
    date_str = analysis.report_date.isoformat()
    lines = [
        "📊 **危化品库存每日分析日报**",
        f"📅 {date_str}",
        "",
        "一、今日重点风险",
        f"🔴 库存超量：{analysis.over_limit_count}项",
        f"🟠 库存急剧上升：{analysis.surge_count}项",
        f"🔵 库存急剧下降：{analysis.decline_count}项",
    ]

    if analysis.over_limit_items:
        lines.extend(["", "🔴 **超量预警**（按超限倍数降序）"])
        for i, item in enumerate(analysis.over_limit_items, start=1):
            loc = f"{item.department_label}｜{item.storage_location}" if item.storage_location else item.department_label
            lines.append(
                f"{i}. {item.material_name}（{loc}）：当前库存 {_fmt_t(item.total)} T，"
                f"限量 {_fmt_t(item.limit)} T，超量 {_fmt_t(item.over)} T，超限 {_fmt_times(item.ratio)} 倍"
            )

        lines.extend(["", "**部门超量汇总**"])
        for dept in analysis.dept_over_summary:
            items_desc = "、".join(
                f"{i.material_name}（{_fmt_times(i.ratio)} 倍）" for i in dept.items
            )
            lines.append(f"· {dept.department_label}：{dept.count} 项超量，{items_desc}")

    if analysis.surge or analysis.decline:
        lines.extend(["", "二、库存异常变化"])
        for chg in analysis.surge:
            ratio = _fmt_ratio(chg.ratio)
            lines.append(
                f"🟠 {chg.material_name}：昨日 {_fmt_t(chg.prev)} T → 今日 {_fmt_t(chg.cur)} T，"
                f"增加 {_fmt_t(chg.delta)} T{(' ' + ratio) if ratio else ''}"
            )
        for chg in analysis.decline:
            ratio = _fmt_ratio(-chg.ratio)
            lines.append(
                f"🔵 {chg.material_name}：昨日 {_fmt_t(chg.prev)} T → 今日 {_fmt_t(chg.cur)} T，"
                f"减少 {_fmt_t(-chg.delta)} T{(' ' + ratio) if ratio else ''}"
            )

    lines.extend(["", "三、主要危化品库存汇总"])
    if not analysis.has_prev:
        lines.append("· 昨日无快照数据，暂无环比，今日起开始记录。")
    elif not analysis.summary:
        lines.append("· 今日无库存记录。")
    else:
        lines.append("危化品 ｜ 今日库存 ｜ 较昨日变化 ｜ 趋势 ｜ 数据状态")
        for chg in analysis.summary:
            status = "⚠️ 未更新" if chg.not_updated else "已更新"
            lines.append(
                f"· {chg.material_name} ｜ {_fmt_t(chg.cur)} T ｜ "
                f"{_fmt_delta(chg.delta)} T ｜ {_trend(chg)} ｜ {status}"
            )

    lines.extend(["", "四、今日库存结论"])
    if analysis.over_limit_items:
        # 重点小结：超量项目最多的部门 + 超限倍数最高的物料
        top_dept = analysis.dept_over_summary[0]
        top_item = analysis.over_limit_items[0]
        parts = [f"今日重点关注 {analysis.over_limit_count}项超量库存"]
        if top_dept.count >= 2:
            parts.append(f"超量集中在{top_dept.department_label}（{top_dept.count}项）")
        parts.append(
            f"超限最高为{top_item.material_name}（{top_item.department_label}）"
            f"{_fmt_times(top_item.ratio)} 倍，建议优先核实处置"
        )
        extra = []
        if analysis.surge_count:
            extra.append(f"{analysis.surge_count}项异常上升")
        if analysis.decline_count:
            extra.append(f"{analysis.decline_count}项异常下降")
        if extra:
            parts.append(f"另有{'、'.join(extra)}库存")
        parts.append("其余危化品库存整体波动正常")
        lines.append("，".join(parts) + "。")
    elif analysis.surge_count or analysis.decline_count:
        lines.append(
            f"今日无超量库存，重点关注 {analysis.surge_count}项异常上升、"
            f"{analysis.decline_count}项异常下降库存；其余危化品库存整体波动正常。"
        )
    else:
        lines.append("今日无超量库存与异常波动，危化品库存整体正常。")

    return "\n".join(lines)
