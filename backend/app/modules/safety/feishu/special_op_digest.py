"""特殊作业日报「速递卡」构建器（飞书卡片 JSON 2.0）。

把 ReportBuilder 的长文日报改造成速递式布局（对齐飞书社区「专属速递」卡风格）：

- 蓝色横幅头部：标题 + 统计副标题（晨报含计划内外拆分；晚报为「晚报」标签 +
  完成/进行/待作业/夜间进度）
- 问候语 + 类型分布一行
- 高风险逐条「标签 + 标题 + 时间地点 + 内容」纯文字条目卡（灰底，不带图片；
  晚报只放未完成高风险，另加 ✅ 已完成 / 🌙 夜间作业聚合条目）
- 中/低风险聚合条目 + 今日新增 + 安全提示
- 完整长文收纳进底部折叠面板（默认收起，信息零丢失）

数据口径与 ``ReportBuilder.build`` 完全一致（同一份 records/stats/ai_analysis）。
任何构建异常 / 卡片超限都返回 None，由调用方回退旧长卡——绝不因速递卡构建
失败漏发日报。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.feishu.notification import build_card_dict
from app.modules.safety.schemas.special_op_daily import AIDailyAnalysisResult
from app.modules.safety.service.special_op_contract import SpecialOpRecord
from app.modules.safety.service.special_operation_daily_report import ReportBuilder

logger = logging.getLogger(__name__)

# 卡片 JSON 序列化大小上限：飞书 interactive 消息 content 上限 30KB，留安全余量
_MAX_CARD_BYTES = 25_000

# 高风险条目最多逐条展示数，超出部分指向折叠面板
_MAX_HIGH_ITEMS = 6

# 作业类型 → text_tag 颜色
_TYPE_TAG_COLORS: dict[str, str] = {
    "动火作业": "orange",
    "受限空间": "indigo",
    "高处作业": "blue",
    "吊装作业": "purple",
    "临时用电": "yellow",
    "动土作业": "carmine",
    "断路作业": "turquoise",
    "盲板抽堵": "wathet",
}

_TYPE_ORDER = [
    "动火作业", "受限空间", "高处作业", "吊装作业",
    "临时用电", "动土作业", "断路作业", "盲板抽堵",
]


@dataclass(frozen=True)
class DigestCard:
    """速递卡构建产物：send_group_card 所需的全量参数。"""

    title: str
    content: str
    elements: list[dict[str, Any]]
    header_template: str = "blue"
    subtitle: str | None = None
    header_tags: list[dict[str, Any]] | None = None


async def build_special_op_digest(
    report_date: date,
    mode: str,
    reports: Sequence[SpecialOpRecord],
    stats: dict[str, int],
    ai_analysis: AIDailyAnalysisResult | None,
    full_markdown: str,
    now: datetime | None = None,
) -> DigestCard | None:
    """构建速递卡；仅 today / afternoon 模式生效。

    构建异常或卡片超限时返回 None，由调用方回退推送旧长卡
    （ReportBuilder.build 的产物 full_markdown）。
    """
    if not ReportBuilder._is_today_family(mode):
        return None
    try:
        return await _build(
            report_date, mode, reports, stats, ai_analysis, full_markdown, now=now,
        )
    except Exception:
        logger.warning("速递卡构建失败，回退旧长卡", exc_info=True)
        return None


async def _build(
    report_date: date,
    mode: str,
    reports: Sequence[SpecialOpRecord],
    stats: dict[str, int],
    ai_analysis: AIDailyAnalysisResult | None,
    full_markdown: str,
    now: datetime | None = None,
) -> DigestCard | None:
    now_eff = now or datetime.now(UTC)
    high = sorted(
        [r for r in reports if r.daily_risk_level == "high"],
        key=ReportBuilder._sort_key,
    )
    medium = [r for r in reports if r.daily_risk_level == "medium"]
    low = [r for r in reports if r.daily_risk_level == "low"]

    is_afternoon = mode == "afternoon"
    if is_afternoon:
        # 晚报布局：已完成/进行中/待作业 + 夜间作业；高风险条目只放未完成项
        completed = [r for r in reports if ReportBuilder.is_completed(r, now_eff)]
        ongoing = [
            r for r in reports
            if not ReportBuilder.is_completed(r, now_eff)
            and ReportBuilder.is_ongoing(r, now_eff)
        ]
        night = ReportBuilder.select_night_ops(report_date, reports)
        focus_high = [r for r in high if not ReportBuilder.is_completed(r, now_eff)]
        title = f"📋 特殊作业速递·晚报 | {report_date.strftime('%Y-%m-%d')}"
        subtitle = (
            f"今日 {stats.get('effective_total', len(reports))} 项 ｜"
            f" 完成 {len(completed)} · 进行 {len(ongoing)}"
            f" · 待作业 {len(reports) - len(completed) - len(ongoing)} ｜ 夜间 {len(night)}"
        )
        header_tags: list[dict[str, Any]] | None = [{
            "tag": "text_tag",
            "text": {"tag": "plain_text", "content": "晚报"},
            "color": "orange",
        }]
        greeting = _afternoon_greeting(now_eff, reports, completed, ongoing)
    else:
        completed = []
        ongoing = []
        night = []
        focus_high = high
        planned_n = sum(1 for r in reports if r.report_type == "planned")
        unplanned_n = sum(1 for r in reports if r.report_type == "unplanned")
        title = f"📋 特殊作业速递 | {report_date.strftime('%Y-%m-%d')}"
        subtitle = (
            f"今日计划 {stats.get('effective_total', len(reports))} 项"
            f" ｜ 高 {len(high)} · 中 {len(medium)} · 低 {len(low)}"
        )
        if planned_n or unplanned_n:
            subtitle += f" ｜ 计划内 {planned_n} · 计划外 {unplanned_n}"
        header_tags = None
        greeting = _greeting(mode, reports, high)

    elements: list[dict[str, Any]] = []

    if is_afternoon and completed:
        completed_high = [r for r in completed if r.daily_risk_level == "high"]
        elements.append({
            "tag": "markdown",
            "content": (
                f"✅ <text_tag color='green'>已完成</text_tag>"
                f" **{len(completed)} 项**（含高风险 {len(completed_high)}）："
                f"{_agg_summary(completed)}"
            ),
        })

    # 今日新增（与长文同口径：当天 BJT 08:00 后新提交；空窗口不渲染）
    new_ops = ReportBuilder.select_new_ops(report_date, reports, mode, now=now_eff)
    if new_ops:
        unplanned_new = sum(1 for r in new_ops if r.report_type == "unplanned")
        mark = f"（计划外 {unplanned_new}）" if unplanned_new else ""
        elements.append({
            "tag": "markdown",
            "content": (
                f"🆕 <text_tag color='yellow'>今日新增</text_tag>"
                f" **{len(new_ops)} 项**{mark}：{_agg_summary(new_ops)}"
            ),
        })

    if is_afternoon and night:
        night_lines = [
            f"🌙 <text_tag color='indigo'>夜间作业</text_tag> **{len(night)} 项**（18:00 后）"
        ]
        night_sorted = sorted(
            night,
            key=lambda r: (
                r.planned_start_time or datetime.min.replace(tzinfo=UTC),
                r.feishu_record_id or "",
            ),
        )
        for r in night_sorted:
            cn = ReportBuilder._cn_label(r.operation_type)
            level = {"high": "高风险", "medium": "中风险", "low": "低风险"}.get(
                r.daily_risk_level or "", "中风险"
            )
            line = f"• {cn}｜{(r.department or '?').strip()}"
            span = ReportBuilder._hm_span(r)
            if span:
                line += f" {span}"
            line += (
                f" <font color='grey'>{level}"
                f" · {ReportBuilder.progress_label(r, now_eff)}</font>"
            )
            night_lines.append(line)
        elements.append({"tag": "markdown", "content": "\n".join(night_lines)})

    # 高风险逐条条目卡（纯文字；晚报只放未完成项）
    for r in focus_high[:_MAX_HIGH_ITEMS]:
        elements.append(_high_item_card(r))
    if len(focus_high) > _MAX_HIGH_ITEMS:
        elements.append({
            "tag": "markdown",
            "content": (
                f"<font color='grey'>其余 {len(focus_high) - _MAX_HIGH_ITEMS} 项高风险"
                "见「完整明细」</font>"
            ),
        })

    # 中/低风险聚合条目
    if medium:
        med_mark = ""
        if is_afternoon:
            medium_unfinished = sum(
                1 for r in medium if not ReportBuilder.is_completed(r, now_eff)
            )
            med_mark = f"（未完成 {medium_unfinished}）"
        elements.append({
            "tag": "markdown",
            "content": (
                f"<text_tag color='orange'>常规作业</text_tag>"
                f" **{len(medium)} 项**{med_mark}：{_agg_summary(medium)}"
            ),
        })
    if low:
        elements.append({
            "tag": "markdown",
            "content": (
                f"<text_tag color='green'>低风险</text_tag>"
                f" **{len(low)} 项**：{_agg_summary(low)}"
            ),
        })

    # 安全提示（AI 生成优先，回退规则引擎）
    tips = _tips(ai_analysis, high, medium)
    if tips:
        tip_lines = ["**📌 安全提示**"] + [
            f"{i}. {t}" for i, t in enumerate(tips, 1)
        ]
        elements.append({"tag": "markdown", "content": "\n".join(tip_lines)})

    # 完整明细折叠面板（默认收起，信息零丢失）
    elements.append(_detail_panel(full_markdown))

    # 超限保护：飞书消息 content 上限 30KB，超限回退旧长卡
    card = build_card_dict(
        title,
        greeting,
        header_template="blue",
        elements=elements,
        subtitle=subtitle,
        header_tags=header_tags,
    )
    size = len(json.dumps(card, ensure_ascii=False).encode("utf-8"))
    if size > _MAX_CARD_BYTES:
        logger.warning("速递卡序列化 %d 字节超上限，回退旧长卡", size)
        return None
    return DigestCard(
        title=title,
        content=greeting,
        elements=elements,
        header_template="blue",
        subtitle=subtitle,
        header_tags=header_tags,
    )


def _afternoon_greeting(
    now: datetime,
    reports: Sequence[SpecialOpRecord],
    completed: Sequence[SpecialOpRecord],
    ongoing: Sequence[SpecialOpRecord],
) -> str:
    """晚报首元素：截至今时的进度一行 + 类型分布。"""
    bj_hm = (now + timedelta(hours=8)).strftime("%H:%M")
    pending_n = len(reports) - len(completed) - len(ongoing)
    prefix = (
        f"Hi，截至今日 {bj_hm}，特殊作业 **{len(reports)}** 项："
        f"已完成 **{len(completed)}** ｜ 进行中 **{len(ongoing)}** ｜ 待作业 **{pending_n}**："
    )
    lines = [prefix]
    chips = _type_chips(reports)
    if chips:
        lines.append(f"<font color='grey'>{chips}</font>")
    return "\n".join(lines)


def _greeting(
    mode: str,
    reports: Sequence[SpecialOpRecord],
    high: Sequence[SpecialOpRecord],
) -> str:
    """首元素问候语：总数 + 重点风险 + 类型分布。"""
    label = "今日"
    prefix = f"Hi，{label}计划特殊作业 **{len(reports)}** 项"
    if high:
        prefix += f"，重点关注高风险 **{len(high)}** 项"
    lines = [prefix + "："]
    chips = _type_chips(reports)
    if chips:
        lines.append(f"<font color='grey'>{chips}</font>")
    return "\n".join(lines)


def _type_chips(reports: Sequence[SpecialOpRecord]) -> str:
    """类型分布一行（与 ReportBuilder 概况同口径：类型计数 + 关联作业）。"""
    type_counts: dict[str, int] = {}
    associated = 0
    for r in reports:
        cn = ReportBuilder._cn_label(r.operation_type)
        type_counts[cn] = type_counts.get(cn, 0) + 1
        all_types: set[str] = {cn}
        other = r.other_operation_types or []
        if isinstance(other, list):
            for t in other:
                all_types.add(ReportBuilder._cn_label(t) if isinstance(t, str) else str(t))
        inferred = r.inferred_operation_types or []
        if isinstance(inferred, list):
            for t in inferred:
                all_types.add(str(t))
        if len(all_types) >= 2:
            associated += 1
    parts = [
        f"{t} {type_counts[t]}"
        for t in _TYPE_ORDER
        if type_counts.get(t, 0) > 0
    ]
    if associated > 0:
        parts.append(f"关联作业 {associated}")
    return " · ".join(parts)


def _high_item_card(r: SpecialOpRecord) -> dict[str, Any]:
    """单条高风险条目卡：column_set 纯文字、灰底。"""
    cn = ReportBuilder._cn_label(r.operation_type)
    tag_color = _TYPE_TAG_COLORS.get(cn, "grey")
    body_lines = [
        f"<text_tag color='red'>高风险</text_tag> <text_tag color='{tag_color}'>{cn}</text_tag>",
        f"**{_item_title(r)}**",
    ]
    meta_parts: list[str] = []
    if r.planned_start_time:
        span = ReportBuilder._bj_time(r.planned_start_time)
        if r.planned_end_time:
            span += f"—{ReportBuilder._bj_time(r.planned_end_time)[-5:]}"
        meta_parts.append(f"⏱ {span}")
    unit = (r.contractor_name or r.personnel_type or "").strip()
    if unit:
        meta_parts.append(unit)
    if meta_parts:
        body_lines.append(f"<font color='grey'>{' ｜ '.join(meta_parts)}</font>")
    desc = (r.work_description or "").strip()
    if desc:
        if len(desc) > 42:
            desc = desc[:42] + "…"
        body_lines.append(desc)

    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "grey",
        "margin": "0px 0px 6px 0px",
        "columns": [{
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_align": "center",
            "padding": "8px 12px",
            "elements": [{"tag": "markdown", "content": "\n".join(body_lines)}],
        }],
    }


def _item_title(r: SpecialOpRecord) -> str:
    dept = (r.department or "").strip() or "未知部门"
    loc = (r.location or "").strip()
    title = f"{dept}｜{loc}" if loc else dept
    if len(title) > 30:
        title = title[:30] + "…"
    return title


def _agg_summary(items: Sequence[SpecialOpRecord]) -> str:
    """「类型 ×N（部门列表）」聚合（与 ReportBuilder 中/低风险段同口径）。"""
    by_type: dict[str, list[SpecialOpRecord]] = {}
    for r in items:
        by_type.setdefault(ReportBuilder._cn_label(r.operation_type), []).append(r)
    parts = []
    for t, its in sorted(by_type.items(), key=lambda x: (-len(x[1]), x[0])):
        depts = sorted({r.department or "?" for r in its})
        parts.append(
            f"{t} ×{len(its)}（{'、'.join(depts[:5])}{'…' if len(depts) > 5 else ''}）"
        )
    return "、".join(parts)


def _tips(
    ai_analysis: AIDailyAnalysisResult | None,
    high: Sequence[SpecialOpRecord],
    medium: Sequence[SpecialOpRecord],
) -> list[str]:
    if ai_analysis and ai_analysis.enhanced_tips:
        cleaned = [
            re.sub(r"^\d+[.、)]\s*", "", tip).strip()
            for tip in ai_analysis.enhanced_tips[:3]
        ]
        return [t for t in cleaned if t]
    return list(ReportBuilder._tips(list(high), list(medium)))[:3]


def _detail_panel(full_markdown: str) -> dict[str, Any]:
    """完整明细折叠面板：默认收起，展开后是旧长卡全文（去掉重复的标题行）。"""
    lines = full_markdown.split("\n")
    if lines and lines[0].lstrip().startswith("📋"):
        lines = lines[1:]
    detail = "\n".join(lines).strip()
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "border": {"color": "grey", "corner_radius": "5px"},
        "header": {
            "title": {"tag": "plain_text", "content": "📄 完整明细（点击展开）"},
        },
        "elements": [{"tag": "markdown", "content": detail}],
    }
