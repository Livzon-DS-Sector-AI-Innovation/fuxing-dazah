"""周五卡（逐项反馈版）+ 两个安全速递格子 —— 纯函数（无 DB 无 IO）。

交互（2026-11-24 实机反馈改版，用户拍板）：**每个变更一个填写框**——
表单内逐项「最新进展 input + ☑进展不变 checkbox」，底部一个提交按钮一次
提交全部；不再有全局「其余变更进展不变」按钮与 select 下拉（旧版卡面见
git 历史；旧卡的 ecf_unchanged_ 回调仍兼容受理，落 dispatch.response_type）。

卡结构（DESIGN §4 改版）：自建完整卡片 JSON 2.0（send_user_card_dict 发送、
update_card PATCH 复用同一构建器）。变更清单放同一个 markdown 正文块（十几项
也只有一个正文元素）；反馈表单元素数 = 2×项数+1（13 项=27，远低于上限）。
input/checkbox 的 name 携带 record_id（form 回调 action.value 不一定返回，
action.name 必然在；form_value 按 name 回传逐项值）。

单项状态回显（提交后 PATCH 重建）：填过进展 → ✅ 行；勾过进展不变 → ☑ 行；
表单保留可继续提交（重复提交以最后一次为准）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.modules.safety.feishu.daily_digest import DigestCell

SCOPE = "ehs_change_followup"
SUBMIT_NAME_PREFIX = "ecf_submit_"
# 旧版全局按钮（已停用渲染；旧卡回调兼容受理）
UNCHANGED_NAME_PREFIX = "ecf_unchanged_"
# 逐项表单组件 name 前缀（后接 record_id）
PROG_INPUT_PREFIX = "ecf_prog_"
UNCHK_INPUT_PREFIX = "ecf_unchk_"

_TITLE_MAX = 24       # 卡面变更名称截断
_PROGRESS_MAX = 60    # 卡面进展行截断
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
    # 已反馈态（回填重建用）
    replied_progress: str = ""
    replied_at_short: str = ""        # HH:MM
    marked_unchanged: bool = False
    marked_at_short: str = ""         # HH:MM


@dataclass(frozen=True)
class FridayCardView:
    """周五卡全量视图（发送与 PATCH 重建共用）。"""

    officer_name: str
    departments: str
    week_no: int
    date_label: str                   # 如 11-27 周五
    items: tuple[CardItemView, ...] = ()
    change_table_url: str = ""        # 「打开变更表」链接（可空）


def _item_block(item: CardItemView) -> list[str]:
    """一项变更的正文块（3-4 行内；已反馈状态行随重建回显）。"""
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
    elif item.marked_unchanged:
        lines.append(
            f"  ☑ {item.change_no}：进展不变，无需更新（{item.marked_at_short}）"
        )
    elif item.progress:
        lines.append(f"  进展：{_short(item.progress, _PROGRESS_MAX)}")
    return lines


def _submit_value(dispatch_id: str) -> str:
    return json.dumps(
        {"scope": SCOPE, "action": "submit", "dispatch_id": dispatch_id},
        ensure_ascii=False,
    )


def _form_elements(view: FridayCardView, dispatch_id: str) -> list[dict[str, Any]]:
    """反馈区：说明 + 每项「信息块 + input + checker」+ 一个提交按钮。

    每项的变更信息（编号/名称/审批详情链接/状态/预计实施/第 N 周督办/进展/
    已反馈行）随该行一起放进表单（2026-11-24 实机反馈：上方清单与表单标签
    重复展示，用户要求合成一处）——form 容器内放 markdown 已实测支持。
    """
    elements: list[dict[str, Any]] = [{
        "tag": "markdown",
        "content": (
            "请在周一 09:00 前反馈：每项变更可直接填写新进展"
            "（会写进变更表「变更最新具体进展」），无变化的勾选「进展不变」；"
            "填完点底部「提交反馈」。已反馈过的项可继续补充，以最后一次为准。"
        ),
    }]
    form_elements: list[dict[str, Any]] = []
    for item in view.items:
        form_elements.append({
            "tag": "markdown",
            "content": "\n".join(_item_block(item)),
        })
        form_elements.append({
            "tag": "input",
            "name": f"{PROG_INPUT_PREFIX}{item.record_id}",
            "placeholder": {"tag": "plain_text", "content": "填写新进展（无变化可不填）"},
        })
        form_elements.append({
            # 飞书卡片 2.0 的勾选组件是 checker（2026-11-24 实机实测：
            # checkbox 报 not support tag；checker 属性为 text + checked）
            "tag": "checker",
            "name": f"{UNCHK_INPUT_PREFIX}{item.record_id}",
            "text": {"tag": "plain_text", "content": "进展不变，无需更新"},
            "checked": False,
        })
    form_elements.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "提交反馈"},
        "type": "primary",
        "form_action_type": "submit",
        "name": f"{SUBMIT_NAME_PREFIX}{dispatch_id}",
        "value": _submit_value(dispatch_id),
    })
    elements.append({"tag": "form", "name": "ecf_form", "elements": form_elements})
    return elements


def build_friday_card(view: FridayCardView, dispatch_id: str) -> dict[str, Any]:
    """构建/重建周五卡完整 JSON（send_user_card_dict 发送、update_card PATCH）。

    变更清单只出现一次：顶部只留问候语，每项的完整信息随行进入表单
    （2026-11-24 实机反馈：上方清单与表单标签重复展示）。
    """
    lead = (
        f"{view.officer_name} 您好，以下 {len(view.items)} 项变更尚未验收完毕，"
        "请跟进督办（每项下方填写）："
    )
    body: list[dict[str, Any]] = [{"tag": "markdown", "content": lead}]
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
    zone = "已私发各变更的分管安全员，收卡人可在卡片内逐项提交进展或标记进展不变"

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
