"""中控报警分析 — Markdown 渲染（纯函数）。

渲染每日分析总结（按车间分节 + 异常模式/设备热点 + AI 汇总 + 整改建议）。
结构：今日研判 → 核心指标 → 报警类型/车间/异常模式/维度分布 → 重复高风险点
→ 明细（按车间）→ AI 汇总分析 → 整改建议 → 提示。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.modules.safety.service.central_alarm.aggregator import CentralAlarmDailyAgg

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"
_PATTERN_LABEL = {
    "normal_transient": "正常瞬报",
    "repeated": "重复报警",
    "false_alarm": "误报",
    "anomalous": "异常依赖",
}
_DIMENSION_LABEL = {
    "process": "工艺",
    "operation": "操作",
    "equipment": "设备",
    "other": "其他",
}
# 异常/风险模式（计入异常占比）
_RISK_PATTERNS = ("repeated", "false_alarm", "anomalous")


def render_daily_report(
    agg: CentralAlarmDailyAgg,
    ai_summary: dict[str, Any] | None = None,
    *,
    window_start_utc: datetime | None = None,
    window_end_utc: datetime | None = None,
) -> str:
    """渲染每日分析总结 Markdown。

    Args:
        agg: 日报聚合结果
        ai_summary: 汇总 AI 结果（{summary, key_issues, rectification_suggestions}），
                    失败为 None → 省略 AI 汇总块
        window_start_utc / window_end_utc: rolling 窗口（前日17:00~当日17:00）显示；
                                          自然日窗口时 None → 显示「当日」
    """
    lines: list[str] = []
    date_str = agg.target_date.isoformat()

    # ── 标题 ──
    lines.append(f"📊 **中控报警日报分析** · {date_str}")
    lines.append(DIVIDER)
    if window_start_utc and window_end_utc:
        lines.append(f"统计区间：{_bj(window_start_utc)} ~ {_bj(window_end_utc)}")
    else:
        lines.append("统计区间：当日")
    lines.append("统计口径：高高压力 / 高高液位（不含泡碱操作）/ 回收车间高高温")
    lines.append("")

    # ── 报警概要（AI 汇总；AI 失败时用分布推断）──
    lines.append("**🔍 报警概要**")
    if ai_summary and ai_summary.get("summary"):
        lines.append(ai_summary["summary"])
    else:
        lines.append(_build_overview(agg))

    # ── 报警指标（总数/车间 + 类型/车间/异常模式/维度分布，分项对齐）──
    lines.append("")
    lines.append("**📌 报警指标**")
    lines.append(f"- 报警总数：**{agg.total} 起**　·　覆盖车间：**{len(agg.workshop_groups)} 个**")
    if agg.alarm_type_distribution:
        lines.append("- 📈 报警类型分布：" + _inline_dist(agg.alarm_type_distribution))
    if agg.workshop_distribution:
        lines.append("- 🏭 车间分布：" + _inline_dist(agg.workshop_distribution))
    if agg.pattern_distribution:
        lines.append("- 🚨 异常模式分布：" + _inline_dist(agg.pattern_distribution, labeler=_PATTERN_LABEL))
    if agg.dimension_distribution:
        lines.append("- 🧭 维度分布：" + _inline_dist(agg.dimension_distribution, labeler=_DIMENSION_LABEL))

    # ── 重点问题 / 整改建议（AI）──
    key_issues = (ai_summary or {}).get("key_issues") or []
    if key_issues:
        lines.append("")
        lines.append("**📌 重点问题**")
        for i, issue in enumerate(key_issues, 1):
            lines.append(f"{i}. {issue}")
    suggestions = (ai_summary or {}).get("rectification_suggestions") or []
    if suggestions:
        lines.append("")
        lines.append("**✅ 整改建议**")
        for i, sug in enumerate(suggestions, 1):
            lines.append(f"{i}. {sug}")

    if agg.total == 0:
        lines.append("")
        lines.append("（当日无报警记录，运行平稳）")
        lines.append(DIVIDER)
        return "\n".join(lines)

    # ── 重复/高风险点 ──
    hotspots = _hotspots(agg.records)
    lines.append("")
    lines.append(DIVIDER)
    lines.append("**🔁 重复/高风险点**")
    if hotspots:
        for ws, post, atype, cnt in hotspots:
            lines.append(f"- **{ws} · {post or '?'}** · {atype}：**{cnt} 次**")
    else:
        lines.append("（今日暂无明显重复/高风险点）")

    # ── 明细（按车间分节）──
    lines.append("")
    lines.append(DIVIDER)
    lines.append(f"**📋 报警明细（{agg.total} 条）**")
    for workshop, records in (agg.workshop_groups.items() or [("全部", agg.records)]):
        lines.append(f"### {workshop}")
        for r in records:
            tags = []
            if r.ai_alarm_type:
                tags.append(r.ai_alarm_type)
            if r.ai_pattern:
                tags.append(_PATTERN_LABEL.get(r.ai_pattern, r.ai_pattern))
            if r.ai_dimension:
                tags.append(_DIMENSION_LABEL.get(r.ai_dimension, r.ai_dimension))
            tag_str = " · ".join(tags) if tags else "未分析"
            lines.append(
                f"- {_bj(r.alarm_date)} {r.post or '?'} | {r.alarm_description or ''}"
                f"（{tag_str}）"
            )

    lines.append("")
    lines.append("📎 **数据源**：飞书多维表格 · [中控报警统计](https://j0eukrlohu.feishu.cn/base/OdMRbCWr3aNEZKsFz94cAt12nzh)")
    return "\n".join(lines)


def _build_overview(agg: CentralAlarmDailyAgg) -> str:
    """计算一句话「今日研判」（基于分布，AI 失败时也给出）。"""
    if agg.total == 0:
        return "今日无报警记录，生产运行平稳。"
    top_ws = _top_kv(agg.workshop_distribution)
    top_type = _top_kv(agg.alarm_type_distribution)
    risk_n = sum(1 for r in agg.records if r.ai_pattern in _RISK_PATTERNS)
    parts = []
    if top_ws:
        parts.append(f"报警主要集中在 **{top_ws[0]}**（{top_ws[1]} 起）")
    if top_type:
        parts.append(f"以 **{top_type[0]}** 为主（{top_type[1]} 起）")
    if risk_n and agg.total:
        parts.append(f"异常/重复 {risk_n} 起（占 {risk_n / agg.total * 100:.0f}%），需重点关注")
    if not parts:
        parts.append("报警整体平稳，无明显异常集中")
    return "、".join(parts) + "。"


def _hotspots(records: Any) -> list[tuple[str, str, str, int]]:
    """同 (workshop, post, ai_alarm_type) 的异常/重复记录计数 → TOP 热点。

    仅统计 ai_pattern ∈ (repeated, anomalous) 的记录；按次数降序取前 5。
    """
    counter: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in records:
        if r.ai_pattern not in _RISK_PATTERNS:
            continue
        key = (r.workshop or "?", r.post or "?", r.ai_alarm_type or "其他")
        counter[key] += 1
    return [
        (ws, post, atype, cnt)
        for (ws, post, atype), cnt in sorted(counter.items(), key=lambda kv: -kv[1])[:5]
    ]


def _top_kv(dist: dict[str, int]) -> tuple[str, int] | None:
    """dist 最大 key/value（空返回 None）。"""
    if not dist:
        return None
    k, v = max(dist.items(), key=lambda kv: kv[1])
    return k, v


def _inline_dist(dist: dict[str, int], labeler: dict[str, Any] | None = None) -> str:
    """分布内联字符串（值降序）：`其他 21 · 高温 17 · ...`。"""
    parts: list[str] = []
    for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
        label = labeler.get(k, k) if labeler else k
        parts.append(f"{label} {v}")
    return " · ".join(parts)


def _append_dist(lines: list[str], dist: dict[str, int], labeler: dict[str, Any] | None = None) -> None:
    """追加分布（值降序，key 可选中文映射）。"""
    for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
        label = labeler.get(k, k) if labeler else k
        lines.append(f"- {label}：**{v}**")


def _bj(dt: datetime | None) -> str:
    """UTC → 北京时间字符串（M/D HH:MM）。"""
    if dt is None:
        return "?"
    return (dt + timedelta(hours=8)).strftime("%m/%d %H:%M")
