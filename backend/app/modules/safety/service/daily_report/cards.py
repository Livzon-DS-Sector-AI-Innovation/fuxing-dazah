"""AI+安全日报卡片构建——纯函数，JSON 2.0（notification.build_card_dict 信封）。

对齐需求截图（图1/图3/图4）：
- 每日汇总卡（群，一日一张 PATCH）：头部副标题+生成按钮，**全员模块化**
  （每人：姓名+状态标签+今日重点/完成情况摘要+AI 行+查看详情按钮），
  底部四格统计条（已提交/AI评价/待补充/已推送）
- 表单卡（DM）：五段 multiline input + 步骤提示（修改路径预填）
- 详情卡（DM，图4）：员工完整五段式最终日报全文（待补充者附 AI 建议）
- 建议/失败卡（DM）、负责人日报全文卡（群）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.modules.safety.feishu.notification import build_card_dict, button_row

#: 卡片回调 scope（business_agent_bot_handler 路由键）
SCOPE = "daily_report"

#: 表单提交按钮 name（form 回调 action.name 必然返回，据此路由）
FORM_SUBMIT_NAME = "dr_submit"

#: 五段内部键（表单 input name = form_value 键 = store 段键）
SECTION_INPUT_NAMES = ("work", "done", "coord", "risk", "plan")

SECTION_META = {
    "work": ("今日重点工作", "做了什么：工作对象、区域、类型"),
    "done": ("完成情况", "到什么程度：数量、结论、进度、未完成项"),
    "coord": ("需要协调事项", "需协调的问题、进展及需要的支持；确无填「暂无」"),
    "risk": ("风险/问题报备", "具体风险+现有措施+整改安排；确无填「暂无」"),
    "plan": ("明日重点工作计划", "明日工作安排；可不填"),
}

#: 状态标签（图3口径：已完成=已推送）
STATUS_LABELS = {
    "done": ("✅ 已推送", "green"),
    "pending": ("🕐 待补充", "orange"),
    "eval_error": ("🔴 评价异常", "red"),
    "none": ("⚪ 未提交", "grey"),
}

#: 摘要截断长度
_BRIEF_LEN = 60


def callback_button(text: str, action: str, *, btn_type: str = "primary", **extra: Any) -> dict[str, Any]:
    """回调按钮（value 双写 dict + behaviors，对齐 r3/例外复核卡模式）。"""
    value: dict[str, Any] = {"scope": SCOPE, "action": action, **extra}
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": btn_type,
        "value": value,
        "behaviors": [{"type": "callback", "value": value}],
    }


def toast(text: str) -> dict[str, Any]:
    """card.action.trigger 同步 ACK 携带的轻提示。"""
    return {"toast": {"type": "info", "content": text}}


def brief(text: str, limit: int = _BRIEF_LEN) -> str:
    """摘要：压成一行并截断。"""
    cleaned = (text or "").strip().replace("\n", "；")
    if not cleaned:
        return "（空）"
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


# ═══════════════════════════════════════════════════════════
# 表单卡（DM，图1）
# ═══════════════════════════════════════════════════════════

def build_form_card(
    date_key: str,
    defaults: dict[str, str] | None = None,
    profile: Any = None,
) -> dict[str, Any]:
    """五段式填写表单卡。defaults 非空 = 修改路径（预填当前内容）。

    profile（profiles.PersonProfile）非空 = 按该人业务范围定制各段提示语。
    """
    from .profiles import form_hints

    defaults = defaults or {}
    hints = form_hints(profile)
    inputs: list[dict[str, Any]] = []
    for key in SECTION_INPUT_NAMES:
        label, placeholder = SECTION_META[key]
        placeholder = hints.get(key) or placeholder
        item: dict[str, Any] = {
            "tag": "input",
            "name": key,
            "required": key != "plan",
            "label": {"tag": "plain_text", "content": label},
            "placeholder": {"tag": "plain_text", "content": placeholder},
            "input_type": "multiline_text",
            "max_length": 1000,
        }
        prefill = (defaults.get(key) or "").strip()
        if prefill:
            item["default_value"] = prefill
        inputs.append(item)

    submit_value = {"scope": SCOPE, "action": "submit", "date_key": date_key}
    inputs.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "提交"},
        "type": "primary",
        "form_action_type": "submit",
        # form 回调中 action.value 不一定返回，action.name 必然存在 → name 路由
        "name": FORM_SUBMIT_NAME,
        # value 双重 JSON 编码对齐 progress_card（事件侧再编码一次，回调双重 decode）
        "value": json.dumps(submit_value, ensure_ascii=False),
    })
    form = {"tag": "form", "name": f"daily_report_form_{date_key}", "elements": inputs}

    is_modify = bool(any((defaults.get(k) or "").strip() for k in SECTION_INPUT_NAMES))
    profile_line = (
        f"\n常见方向参考：**{profile.direction}**——提示语按你的画像生成，"
        "写当日实际工作即可，**不限于**这些方向" if profile else ""
    )
    intro = (
        f"**{date_key} 日报修改**（步骤 2/2：AI 建议已预填在下方，按实际情况补充后提交最终版）"
        if is_modify
        else f"**{date_key} 日报填写**（步骤 1/2：首次提交 → AI 建议 → 修改并提交最终版；"
             "明日计划可不填，无协调/风险填「暂无」）"
    ) + profile_line
    return build_card_dict(
        "AI+安全日报",
        intro,
        header_template="blue" if is_modify else "orange",
        elements=[form],
    )


# ═══════════════════════════════════════════════════════════
# 每日汇总卡（群，图3）
# ═══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MemberView:
    """员工模块视图（service.compute_state 产出）。"""

    open_id: str
    name: str
    status: str            # done / pending / eval_error / none（未提交）
    work_brief: str
    done_brief: str
    ai_line: str           # 已完成=AI摘要；待补充=第一条建议；未提交=空
    full_text: str = ""    # 折叠面板五段全文（service 预填，速递格子同款详情）


@dataclass(frozen=True)
class DailyCardState:
    """汇总卡状态快照（service.refresh_daily_card 计算）。"""

    date_key: str
    members: tuple[MemberView, ...] = field(default_factory=tuple)
    total: int = 0
    submitted: int = 0
    ai_done: int = 0
    pending: int = 0
    pushed: int = 0
    draft_markdown: str = ""
    published_at: str = ""


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, STATUS_LABELS["none"])[0]


def _at(name: str, open_id: str) -> str:
    """@ 提及（safety 应用作用域 open_id）；仅用于待补充催办。"""
    if open_id:
        return f"<at id={open_id}></at>"
    return name


#: 状态 → 速递格子 text_tag 颜色（daily_digest 同枚举）
STATUS_TAG_COLORS = {
    "done": "green",
    "pending": "orange",
    "eval_error": "red",
    "none": "grey",
}


def _full_text(member: MemberView) -> str:
    """折叠面板里的五段全文（build 时由 service 预填进 member.full_text）。"""
    return getattr(member, "full_text", "")


def member_cell(member: MemberView, date_key: str) -> dict[str, Any]:
    """员工格子 = 安全速递同款（daily_digest._cell_element 同构）。

    灰底 column_set + text_tag 状态标签 + 姓名标题 + 概览（今日重点/完成情况）
    + 灰字 AI 行 + 内嵌「📄 查看详情」collapsible_panel（五段全文，不截断）。
    未提交者无面板，附【📝 去填写】按钮。
    """
    shown = _at(member.name, member.open_id) if member.status == "pending" else member.name
    overview = [
        f"<text_tag color='{STATUS_TAG_COLORS.get(member.status, 'grey')}'>"
        f"{_status_label(member.status)}</text_tag> **{shown}**",
    ]
    if member.status == "none":
        overview.append("今日尚未提交")
    else:
        overview.append(f"⊙ 今日重点：{brief(member.work_brief)}")
        overview.append(f"✓ 完成情况：{brief(member.done_brief)}")
    if member.ai_line:
        overview.append(f"<font color='grey'>{member.ai_line}</font>")

    left_elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": "\n".join(overview)},
    ]
    detail = "" if member.status == "none" else _full_text(member)  # 未提交防御：永不出面板
    if detail:
        left_elements.append({
            "tag": "collapsible_panel",
            "expanded": False,
            "border": {"color": "grey", "corner_radius": "5px"},
            "margin": "6px 0px 0px 0px",
            "header": {"title": {"tag": "plain_text", "content": "📄 查看详情"}},
            "elements": [{"tag": "markdown", "content": detail}],
        })
    elif member.status == "none":
        left_elements.append(callback_button("📝 去填写", "open_form", btn_type="default"))

    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "grey",
        "margin": "0px 0px 8px 0px",
        "columns": [{
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_align": "center",
            "padding": "8px 4px 8px 12px",
            "elements": left_elements,
        }],
    }


def stats_markdown(state: DailyCardState) -> str:
    """底部统计条（图3 四格）。"""
    return (
        f"📋 已提交 **{state.submitted}/{state.total}**　｜　"
        f"🤖 AI评价 **{state.ai_done}/{state.total}**　｜　"
        f"⚠️ 待补充 **{state.pending}**　｜　"
        f"✅ 已推送最终版 **{state.pushed}**"
    )


def daily_card_subtitle(state: DailyCardState) -> str:
    """头部副标题（图3：「今日已汇总 8 人日报，AI 已完成一次评价并输出最终版」）。"""
    if state.published_at:
        return f"负责人日报已发布（{state.published_at}）"
    return (
        f"今日已汇总 {state.submitted} 人日报，"
        f"AI 已完成一次评价{'并输出最终版' if state.pushed else ''}"
    )


def daily_card_elements(state: DailyCardState) -> list[dict[str, Any]]:
    """汇总卡元素区：操作按钮 → 全员模块 → 统计条 →（草稿预览）。"""
    elements: list[dict[str, Any]] = []
    # 操作按钮行：【填写/修改】常驻（图1 固定入口，已提交者点开=预填修改），
    # 生成/发布按阶段追加；已发布后仍保留填写入口（内容修订口径）
    buttons = [callback_button("📝 填写/修改今日日报", "open_form")]
    if state.published_at:
        pass
    elif state.draft_markdown:
        buttons.append(callback_button("🚀 发布负责人日报", "publish", btn_type="default"))
    else:
        buttons.append(callback_button("✨ 一键生成部门负责人日报", "gen_leader", btn_type="default"))
    elements.append(button_row(*buttons))
    elements.append({"tag": "hr"})
    for member in state.members:
        elements.append(member_cell(member, state.date_key))
    elements.append({"tag": "markdown", "content": stats_markdown(state)})
    if state.draft_markdown and not state.published_at:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "markdown",
            "content": "📋 负责人日报草稿已生成，待负责人核验发布 👇\n"
                       + state.draft_markdown[:1000]
                       + ("\n…（截断，发布后看全文）" if len(state.draft_markdown) > 1000 else ""),
        })
    return elements


def build_daily_card(state: DailyCardState) -> dict[str, Any]:
    """全量卡（首发与 PATCH 同构）：content 空——统计条只在元素区底部出现一次。"""
    return build_card_dict(
        f"安全部门日报汇总 | {state.date_key}",
        "",
        header_template="green" if state.published_at else "blue",
        elements=daily_card_elements(state),
        subtitle=daily_card_subtitle(state),
    )


# ═══════════════════════════════════════════════════════════
# 其余 DM 卡（建议 / 失败 / 负责人全文）
# ═══════════════════════════════════════════════════════════

def build_submitted_state_card(date_key: str, message: str, *, error: bool = False) -> dict[str, Any]:
    """表单卡提交后的原地状态卡（PATCH 替换原表单，防重复提交混淆——
    progress_card.build_submitted_card 同款模式）。"""
    from .config import bj_now

    now_str = bj_now().strftime("%H:%M")
    if error:
        return build_card_dict(
            "⚠️ 日报提交失败",
            f"**{date_key}**\n\n{message}\n\n请在群汇总卡重新点【📝 填写/修改今日日报】重试。"
            f"\n\n⏱ {now_str}",
            header_template="red",
        )
    return build_card_dict(
        "✅ 日报已提交",
        f"**{date_key}**\n\n{message}\n\n⏱ {now_str}",
        header_template="green",
    )

def build_suggestion_card(
    date_key: str,
    name: str,
    sections: dict[str, str],
    suggestions: list[str],
    overall: str,
) -> dict[str, Any]:
    """AI 建议卡（DM）：原文回显 + 建议 + 修改按钮（预填表单）。"""
    lines = [f"**{date_key} 日报初稿已收到**，AI 评价如下（每天仅此一轮）：", "", f"> 总评：{overall}", ""]
    for idx, sug in enumerate(suggestions, 1):
        lines.append(f"{idx}. {sug}")
    lines += ["", "---", "**你的初稿**："]
    for key in SECTION_INPUT_NAMES:
        text = (sections.get(key) or "").strip()
        if text:
            lines.append(f"- **{SECTION_META[key][0]}**：{text}")
    elements = [
        {"tag": "hr"},
        button_row(callback_button("✏️ 修改并完成（预填初稿）", "open_form")),
    ]
    return build_card_dict(
        "AI 日报评价",
        "\n".join(lines),
        header_template="blue",
        elements=elements,
    )


def build_eval_fail_card(date_key: str, error: str) -> dict[str, Any]:
    """评价失败卡（DM）：留初稿 + 重试按钮（唯一重评入口）。"""
    content = (
        f"**{date_key} 日报初稿已保存**，但 AI 评价失败：{error}\n\n"
        "可点击下方按钮重试；也可先【修改并完成】直接提交最终版（无建议消化环节）。"
    )
    elements = [
        {"tag": "hr"},
        button_row(callback_button("🔄 重试AI评价", "retry_eval")),
        button_row(callback_button("✏️ 修改并完成", "open_form")),
    ]
    return build_card_dict("AI 日报评价异常", content, header_template="red", elements=elements)


def build_leader_report_card(date_key: str, report_markdown: str) -> dict[str, Any]:
    """负责人日报全文卡（群，发布时新发）。"""
    return build_card_dict(
        f"【部门日报】{date_key}",
        report_markdown,
        header_template="green",
    )
