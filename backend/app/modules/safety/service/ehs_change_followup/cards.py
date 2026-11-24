"""周五卡三态 + 两个安全速递格子 —— 纯函数（无 DB 无 IO）。

卡结构（DESIGN §4）：自建完整卡片 JSON 2.0（send_user_card_dict 发送、
update_card PATCH 复用同一构建器）。全部变更放同一个 markdown 正文块
（十几项也只有一个正文元素，不超单卡 200 元素）；表单 = select（选项值=
record_id，展示=编号+名称截断）+ input + submit 按钮。
按钮 name 携带 dispatch_id（form 回调 action.value 不一定返回，name 必然在）。

三态：
- 初始：说明 + 「进展不变」按钮 + 表单；
- 部分提交（提交过 ≥1 次进展）：正文底部追加 ✅ 提交行，表单保留，
  「进展不变」按钮撤掉；
- 已反馈（点了「进展不变」）：正文底部追加已反馈行，按钮和表单都撤掉。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.modules.safety.feishu.daily_digest import DigestCell
from app.modules.safety.feishu.notification import button_row

SCOPE = "ehs_change_followup"
SUBMIT_NAME_PREFIX = "ecf_submit_"
UNCHANGED_NAME_PREFIX = "ecf_unchanged_"

_TITLE_MAX = 24       # 卡面变更名称截断
_OPTION_TEXT_MAX = 60  # select 选项文本截断（编号+名称）
_PROGRESS_MAX = 60     # 卡面进展行截断
_DIGEST_DETAIL_MAX = 400  # 速递格子明细行截断

TAG_COLOR = "orange"
TAG_TEXT = "变更督办"


def toast(content: str, type_: str = "success") -> dict[str, Any]:
    """卡片回调 ACK toast。"""
    return {"toast": {"type": type_, "content": content}}


def _short(text: str | None, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


@dataclass(frozen=True)
class CardItemView:
    """构建周五卡/重建卡所需的一项变更视图。"""

    record_id: str
    change_no: str
    title: str = ""
    status_shown: str = ""
    acceptance_note: str = ""
    progress: str = ""
    expected_start: str | None = None
    approval_url: str | None = None
    nag_weeks: int = 1
    # 已提交态（回填重建用）
    replied_progress: str = ""
    replied_at_short: str = ""        # HH:MM


@dataclass(frozen=True)
class FridayCardView:
    """周五卡全量视图（发送与 PATCH 重建共用）。"""

    officer_name: str
    departments: str
    week_no: int
    date_label: str                   # 如 11-27 周五
    items: tuple[CardItemView, ...] = ()
    has_replies: bool = False         # 提交过 ≥1 次进展（撤「进展不变」按钮，表单保留）
    responded_unchanged_at: str = ""  # HH:MM（非空=已反馈态，按钮和表单都撤）
    change_table_url: str = ""        # 「打开变更表」链接（可空）


def _item_block(item: CardItemView) -> list[str]:
    """一项变更的正文块（3 行内）。"""
    head = item.change_no or item.record_id
    title = _short(item.title, _TITLE_MAX) or "（无名称）"
    if item.approval_url:
        head = f"**{head}** {title} [审批详情]({item.approval_url})"
    else:
        head = f"**{head}** {title}"
    status = item.status_shown or "状态未填"
    meta = [status]
    if item.expected_start:
        meta.append(f"预计实施 {item.expected_start}")
    if item.nag_weeks > 1:
        meta.append(f"第 {item.nag_weeks} 周督办")
    if item.acceptance_note:
        meta.append(item.acceptance_note)
    lines = [head, "  " + " ｜ ".join(meta)]
    if item.replied_progress:
        lines.append(
            f"  ✅ {item.change_no}：{_short(item.replied_progress, _PROGRESS_MAX)}"
            f"（{item.replied_at_short}）"
        )
    elif item.progress:
        lines.append(f"  进展：{_short(item.progress, _PROGRESS_MAX)}")
    return lines


def _submit_value(dispatch_id: str) -> str:
    return json.dumps(
        {"scope": SCOPE, "action": "submit", "dispatch_id": dispatch_id},
        ensure_ascii=False,
    )


def _unchanged_value(dispatch_id: str) -> str:
    return json.dumps(
        {"scope": SCOPE, "action": "unchanged", "dispatch_id": dispatch_id},
        ensure_ascii=False,
    )


def _form_elements(view: FridayCardView, dispatch_id: str) -> list[dict[str, Any]]:
    """反馈区：说明 + 「进展不变」按钮（未提交过才在）+ 表单（已反馈则都撤）。"""
    elements: list[dict[str, Any]] = []
    if view.responded_unchanged_at:
        elements.append({
            "tag": "markdown",
            "content": (
                f"✅ 已反馈：其余变更进展不变，无需更新"
                f"（{view.responded_unchanged_at}）"
            ),
        })
        return elements
    elements.append({
        "tag": "markdown",
        "content": (
            "请在周一 09:00 前反馈：\n"
            "· 有新进展 → 选变更、填进展后点「提交进展」，"
            "会写进变更表「变更最新具体进展」\n"
            + (
                "· 已提交过进展的变更可继续补充提交"
                if view.has_replies
                else "· 其余都没变化 → 点下面的按钮"
            )
        ),
    })
    # 「进展不变」只在从未提交过进展时提供（§4：提交进展后按钮撤掉）
    if not view.has_replies:
        elements.append(button_row({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "✅ 其余变更进展不变，无需更新"},
            "type": "default",
            "name": f"{UNCHANGED_NAME_PREFIX}{dispatch_id}",
            "value": _unchanged_value(dispatch_id),
        }))
    options = [
        {
            "text": {
                "tag": "plain_text",
                "content": _short(
                    f"{it.change_no or it.record_id} {it.title}", _OPTION_TEXT_MAX,
                ),
            },
            "value": it.record_id,
        }
        for it in view.items
    ][:99]  # select 选项上限 99（当前单人最多 13 项）
    elements.append({
        "tag": "form",
        "name": "ecf_form",
        "elements": [
            {
                "tag": "select_static",
                "name": "change",
                "placeholder": {"tag": "plain_text", "content": "请选择变更"},
                "options": options,
            },
            {
                "tag": "input",
                "name": "progress",
                "required": True,
                "label": {"tag": "plain_text", "content": "最新进展"},
                "placeholder": {"tag": "plain_text", "content": "请填写本次进展"},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "提交进展"},
                "type": "primary",
                "form_action_type": "submit",
                "name": f"{SUBMIT_NAME_PREFIX}{dispatch_id}",
                "value": _submit_value(dispatch_id),
            },
        ],
    })
    return elements


def build_friday_card(view: FridayCardView, dispatch_id: str) -> dict[str, Any]:
    """构建/重建周五卡完整 JSON（send_user_card_dict 发送、update_card PATCH）。"""
    body: list[dict[str, Any]] = []
    lines: list[str] = [
        f"{view.officer_name} 您好，以下 {len(view.items)} 项变更尚未验收完毕，"
        "请跟进督办：",
        "",
    ]
    for item in view.items:
        lines.extend(_item_block(item))
        lines.append("")
    body.append({"tag": "markdown", "content": "\n".join(lines).rstrip()})
    body.append({"tag": "hr"})
    body.extend(_form_elements(view, dispatch_id))
    if view.change_table_url:
        body.append({
            "tag": "markdown",
            "content": f"📋 [打开变更表]({view.change_table_url})",
        })
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "fill"},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"⏰ EHS变更周度督办 · 未验收 {len(view.items)} 项",
            },
            "subtitle": {
                "tag": "plain_text",
                "content": f"{view.departments} · 第 {view.week_no} 周（{view.date_label}）",
            },
            "template": "orange",
        },
        "body": {"elements": body},
    }


# ── 速递格子 ──

@dataclass(frozen=True)
class DigestDispatchView:
    """周五格子里一位安全员的送达明细。"""

    officer_name: str
    departments: str
    change_nos: tuple[str, ...] = ()
    sent: bool = True


@dataclass
class FridayDigestView:
    """周五速递格子视图（DESIGN §6）。"""

    total_todo: int = 0
    terminated_count: int = 0
    excluded: tuple[tuple[str, str], ...] = ()   # (change_no, 标注)
    stale_accepted: tuple[str, ...] = ()          # 验收已通过但状态没改
    dispatched: list[DigestDispatchView] = field(default_factory=list)
    unsent_departments: tuple[str, ...] = ()      # 未配置安全员的部门（含项数展示由调用方拼）


def build_friday_cell(view: FridayDigestView) -> DigestCell:
    """周五速递格子：概览 + 已私发对象 + 未纳入督办 + 未发送 + 提示。"""
    sent_people = [d for d in view.dispatched if d.sent]
    stats = (
        f"未验收 **{view.total_todo}** 项 ｜ "
        f"已私发 **{len(sent_people)}** 人（{len(sent_people)} 张卡送达）"
    )
    zone = "已私发各变更的分管安全员，收卡人可在卡片内直接提交进展"

    detail: list[str] = [f"**已私发对象（{len(sent_people)} 人）**"]
    for d in sent_people:
        detail.append(
            f"- {d.officer_name}（{_short(d.departments, 60)}）："
            f"{('、'.join(d.change_nos)) or '—'}"
        )
    failed = [d for d in view.dispatched if not d.sent]
    if failed:
        detail.append("")
        detail.append("**未送达**")
        detail.extend(f"- {d.officer_name}（{_short(d.departments, 60)}）" for d in failed)

    detail.append("")
    detail.append("**未纳入督办**")
    detail.append(f"- 变更中止 {view.terminated_count} 项")
    detail.append(
        f"- 排除待确认 {len(view.excluded)} 项"
        "（状态填了已验收但无已通过的验收单，待业务确认）"
    )
    if view.excluded:
        detail.append(
            "  " + "、".join(f"{no}（{note}）" for no, note in view.excluded)
        )

    if view.unsent_departments:
        detail.append("")
        detail.append("**未发送**")
        detail.extend(f"- {d}（未配置分管安全员）" for d in view.unsent_departments)

    if view.stale_accepted:
        detail.append("")
        detail.append("**提示**")
        detail.append(
            f"- {len(view.stale_accepted)} 项验收已通过但状态没改，"
            "可把变更状态改为「已验收」：" + "、".join(view.stale_accepted)
        )

    return DigestCell(
        tag_color=TAG_COLOR,
        tag_text=TAG_TEXT,
        title="EHS变更周度督办",
        stats=stats,
        zone=zone,
        detail=_clip_detail(detail),
    )


@dataclass
class MondayCategoryGroup:
    """周一格子一类下的一组（部门维度）。"""

    department: str
    officer_name: str
    change_nos: tuple[str, ...] = ()
    # 更新类的展示行（编号：进展摘要（卡片提交 HH:MM）），其余类为空
    updated_lines: tuple[str, ...] = ()


@dataclass
class MondayDigestView:
    """周一速递格子视图（DESIGN §6）。"""

    not_updated: list[MondayCategoryGroup] = field(default_factory=list)
    unchanged: list[MondayCategoryGroup] = field(default_factory=list)
    updated: list[MondayCategoryGroup] = field(default_factory=list)
    friday_total: int = 0
    closed_count: int = 0

    @property
    def not_updated_count(self) -> int:
        return sum(len(g.change_nos) for g in self.not_updated)

    @property
    def unchanged_count(self) -> int:
        return sum(len(g.change_nos) for g in self.unchanged)

    @property
    def updated_count(self) -> int:
        return sum(len(g.change_nos) for g in self.updated)


def build_monday_cell(view: MondayDigestView) -> DigestCell:
    """周一速递格子：三类计数 + 本周已关闭 + 三类明细（按部门/安全员分组）。"""
    stats = (
        f"未更新 **{view.not_updated_count}** 项 ｜ "
        f"进展不变 **{view.unchanged_count}** 项 ｜ "
        f"更新 **{view.updated_count}** 项"
    )
    zone = f"周五督办 {view.friday_total} 项，本周已关闭 {view.closed_count} 项"

    def _groups(groups: list[MondayCategoryGroup]) -> list[str]:
        lines: list[str] = []
        for g in groups:
            nos = "、".join(g.change_nos)
            head = f"- {g.department}（{g.officer_name}）"
            lines.append(f"{head}：{nos}" if nos else head)
            lines.extend(f"   {x}" for x in g.updated_lines)
        return lines or ["- 无"]

    detail: list[str] = []
    detail.append(f"**① 未更新（{view.not_updated_count} 项）**")
    detail.extend(_groups(view.not_updated))
    detail.append("")
    detail.append(f"**② 进展不变，无需更新（{view.unchanged_count} 项）**")
    detail.extend(_groups(view.unchanged))
    detail.append("")
    detail.append(f"**③ 更新（{view.updated_count} 项）**")
    detail.extend(_groups(view.updated))

    return DigestCell(
        tag_color=TAG_COLOR,
        tag_text=TAG_TEXT,
        title="EHS变更督办总结",
        stats=stats,
        zone=zone,
        detail=_clip_detail(detail),
    )


def _clip_detail(lines: list[str], limit: int = _DIGEST_DETAIL_MAX) -> str:
    """明细超长时逐行截断（格子 detail 完整展示为原则，仅兜底防超卡）。"""
    out = []
    for line in lines:
        out.append(line if len(line) <= limit else line[: limit - 1] + "…")
    return "\n".join(out)
