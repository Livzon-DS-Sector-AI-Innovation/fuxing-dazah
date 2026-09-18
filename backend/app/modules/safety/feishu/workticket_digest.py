"""作业票审核「速递卡」构建器（发安全信息化平台试用群）。

与特殊作业速递卡同款折叠风格（纯文字，不带图片）：

- 蓝色横幅头部：标题 + 审核统计副标题
- 问候语 + 票类型分布一行
- 问题票逐条「标签 + 票号 + 部门地点 + 违规摘要」条目卡（驳回优先，待补其次）
- 通过票聚合一行
- 完整明细收进底部折叠面板（默认收起，信息零丢失）

构建失败 / 卡片超限返回 None，调用方回退旧长卡——绝不因速递卡构建失败漏发审核日报。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import date as date_cls
from typing import Any

from app.modules.safety.feishu.notification import build_card_dict
from app.modules.safety.feishu.special_op_digest import DigestCard
from app.modules.safety.workticket_review.parser import WorkTicket
from app.modules.safety.workticket_review.report_builder import (
    _cn_detail,
    _fmt_site_content,
    _ticket_type_name,
)
from app.modules.safety.workticket_review.rule_engine import Violation

logger = logging.getLogger(__name__)

# 卡片 JSON 序列化大小上限（飞书消息 content 上限 30KB，留余量）
_MAX_CARD_BYTES = 25_000

# 问题票最多逐条展示数，超出部分指向折叠面板
_MAX_PROBLEM_ITEMS = 6

# 作业类型中文名 → text_tag 颜色（与特殊作业速递卡一致；兼容带/不带「作业」后缀）
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
    "动火作业", "受限空间作业", "高处作业", "吊装作业",
    "临时用电作业", "动土作业", "断路作业", "盲板抽堵作业",
]


def _type_color(type_name: str) -> str:
    return _TYPE_TAG_COLORS.get(type_name) or _TYPE_TAG_COLORS.get(
        type_name.removesuffix("作业"), "grey",
    )


def build_workticket_digest(
    review_date: date_cls | str,
    tickets: Sequence[WorkTicket],
    violations_by_ticket: dict[str, list[Violation]],
    stats: dict[str, Any],
    full_markdown: str,
) -> DigestCard | None:
    """构建速递卡；构建异常或超限返回 None，调用方回退旧长卡。"""
    try:
        return _build(review_date, tickets, violations_by_ticket, stats, full_markdown)
    except Exception:
        logger.warning("作业票速递卡构建失败，回退旧长卡", exc_info=True)
        return None


def _build(
    review_date: date_cls | str,
    tickets: Sequence[WorkTicket],
    violations_by_ticket: dict[str, list[Violation]],
    stats: dict[str, Any],
    full_markdown: str,
) -> DigestCard | None:
    real_map: dict[str, tuple[WorkTicket, list[Violation]]] = {}
    insufficient_map: dict[str, tuple[WorkTicket, list[Violation]]] = {}
    compliant: list[WorkTicket] = []
    for ticket in tickets:
        ticket_no = ticket.ticket_no or ticket.process_instance_id or ""
        violations = list(violations_by_ticket.get(ticket_no) or [])
        real = [v for v in violations if not v.not_applicable and not _is_insufficient(v)]
        insufficient = [v for v in violations if not v.not_applicable and _is_insufficient(v)]
        if real:
            real_map[ticket_no] = (ticket, real)
        if insufficient:
            insufficient_map[ticket_no] = (ticket, insufficient)
        if not real and not insufficient:
            compliant.append(ticket)

    date_text = (
        review_date.isoformat() if isinstance(review_date, date_cls) else str(review_date)
    )
    title = f"📋 作业票审核速递 | {date_text}"
    subtitle = (
        f"今日审核 {stats.get('total', len(tickets))} 票 ｜ "
        f"通过 {stats.get('compliant_count', len(compliant))} · "
        f"驳回 {stats.get('violation_count', len(real_map))} · "
        f"待补 {stats.get('data_insufficient', len(insufficient_map))}"
    )

    elements: list[dict[str, Any]] = []

    # 问题票逐条（先驳回后待补）
    problem_items: list[tuple[str, str, WorkTicket, list[Violation]]] = [
        ("red", "驳回", t, vs) for t, vs in real_map.values()
    ] + [
        ("yellow", "待补数据", t, vs) for t, vs in insufficient_map.values()
    ]
    for tag_color, tag_text, ticket, violations in problem_items[:_MAX_PROBLEM_ITEMS]:
        elements.append(_problem_card(tag_color, tag_text, ticket, violations))
    hidden = len(problem_items) - _MAX_PROBLEM_ITEMS
    if hidden > 0:
        elements.append({
            "tag": "markdown",
            "content": (
                f"<font color='grey'>其余 {hidden} 张问题票见「完整明细」</font>"
            ),
        })

    # 通过票聚合
    if compliant:
        elements.append({
            "tag": "markdown",
            "content": (
                f"<text_tag color='green'>通过</text_tag>"
                f" **{len(compliant)} 票**：{_type_summary(compliant)}"
            ),
        })

    # 完整明细折叠面板（去掉旧卡首行标题，避免重复）
    lines = full_markdown.split("\n")
    if lines and lines[0].lstrip().startswith("📋"):
        lines = lines[1:]
    detail = "\n".join(lines).strip()
    if detail:
        elements.append({
            "tag": "collapsible_panel",
            "expanded": False,
            "border": {"color": "grey", "corner_radius": "5px"},
            "header": {"title": {"tag": "plain_text", "content": "📄 完整明细（点击展开）"}},
            "elements": [{"tag": "markdown", "content": detail}],
        })

    greeting = _greeting(tickets, stats, len(real_map))
    card = build_card_dict(title, greeting, "blue", elements, subtitle=subtitle)
    size = len(json.dumps(card, ensure_ascii=False).encode("utf-8"))
    if size > _MAX_CARD_BYTES:
        logger.warning("作业票速递卡序列化 %d 字节超上限，回退旧长卡", size)
        return None
    return DigestCard(
        title=title,
        content=greeting,
        elements=elements,
        header_template="blue",
        subtitle=subtitle,
    )


def _is_insufficient(v: Violation) -> bool:
    return not v.not_applicable and v.detail.strip().startswith("数据不足")


def _greeting(
    tickets: Sequence[WorkTicket],
    stats: dict[str, Any],
    real_count: int,
) -> str:
    total = stats.get("total", len(tickets))
    prefix = f"Hi，今日作业票审核 **{total}** 张"
    if real_count:
        prefix += f"，**{real_count}** 张驳回"
    chips = _type_chips(tickets)
    lines = [prefix + "："]
    if chips:
        lines.append(f"<font color='grey'>{chips}</font>")
    return "\n".join(lines)


def _type_chips(tickets: Sequence[WorkTicket]) -> str:
    counts: dict[str, int] = {}
    for t in tickets:
        name = _ticket_type_name(t.ticket_type)
        counts[name] = counts.get(name, 0) + 1
    parts = [
        f"{name} {counts[name]}"
        for name in _TYPE_ORDER
        if counts.get(name, 0) > 0
    ]
    # 未知类型兜底（保持信息不丢）
    for name, cnt in counts.items():
        if name not in _TYPE_ORDER:
            parts.append(f"{name} {cnt}")
    return " · ".join(parts)


def _type_summary(tickets: Sequence[WorkTicket]) -> str:
    counts: dict[str, int] = {}
    for t in tickets:
        name = _ticket_type_name(t.ticket_type)
        counts[name] = counts.get(name, 0) + 1
    return "、".join(f"{name} ×{cnt}" for name, cnt in sorted(counts.items()))


def _problem_card(
    tag_color: str,
    tag_text: str,
    ticket: WorkTicket,
    violations: list[Violation],
) -> dict[str, Any]:
    cn_type = _ticket_type_name(ticket.ticket_type)
    lines = [
        f"<text_tag color='{tag_color}'>{tag_text}</text_tag>"
        f" <text_tag color='{_type_color(cn_type)}'>{cn_type}</text_tag>",
        f"**{ticket.ticket_no or ticket.process_instance_id or '（无票号）'}**",
    ]
    site_content = _fmt_site_content(ticket)
    if site_content:
        lines.append(f"<font color='grey'>{site_content}</font>")
    if violations:
        first = violations[0]
        desc = f"{first.rule_name}: {_cn_detail(first.detail)}"
        if len(desc) > 50:
            desc = desc[:50] + "…"
        if len(violations) > 1:
            desc += f"（共 {len(violations)} 项）"
        lines.append(f"⚠️ {desc}")
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
            "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
        }],
    }
