"""AI+安全日报卡片构建——纯函数，JSON 2.0（notification.build_card_dict 信封）。

三张交互卡 + 一张全文卡：
- 每日入口卡（群，一日一张 PATCH 更新）：进度 + 未完成名单 + 填写/生成/发布按钮
- 表单卡（DM）：四段 multiline input + 提交按钮（name=dr_submit 路由）
- 建议/失败卡（DM）：AI 一轮评价结果 + 修改/重试按钮
- 负责人日报全文卡（群，发布时新发）
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

#: 四段表单 input name（form_value 键）
SECTION_INPUT_NAMES = ("work", "done", "issue", "plan")

SECTION_META = {
    "work": ("今日重点工作", "做了什么：工作对象、区域、类型"),
    "done": ("完成情况", "到什么程度：数量、结论、进度、未完成项"),
    "issue": ("问题与协调", "问题 + 已采取措施 + 需谁支持；确无填「无」"),
    "plan": ("明日计划", "明日工作安排；可不填"),
}


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


# ═══════════════════════════════════════════════════════════
# 表单卡（DM）
# ═══════════════════════════════════════════════════════════

def build_form_card(date_key: str, defaults: dict[str, str] | None = None) -> dict[str, Any]:
    """四段式填写表单卡。defaults 非空 = 修改路径（预填当前内容）。"""
    defaults = defaults or {}
    inputs: list[dict[str, Any]] = []
    for key in SECTION_INPUT_NAMES:
        label, placeholder = SECTION_META[key]
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
    intro = (
        f"**{date_key} 日报修改**：AI 建议已预填在下方，请按实际情况补充后提交最终版。"
        if is_modify
        else f"**{date_key} 日报填写**：四段式（明日计划可不填），提交后 AI 会给一轮补充建议。"
    )
    return build_card_dict(
        "AI+安全日报",
        intro,
        header_template="blue" if is_modify else "orange",
        elements=[form],
    )


# ═══════════════════════════════════════════════════════════
# 每日入口卡（群）
# ═══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DailyCardState:
    """入口卡状态快照（service.refresh_daily_card 计算）。"""

    date_key: str
    done_count: int = 0
    total: int = 0
    #: (name, open_id) —— 待补充用 @ 提及催办
    pending: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    not_submitted: tuple[str, ...] = field(default_factory=tuple)
    draft_markdown: str = ""
    published_at: str = ""
    eval_error: tuple[str, ...] = field(default_factory=tuple)


def _at(name: str, open_id: str) -> str:
    """@ 提及（safety 应用作用域 open_id）。"""
    if open_id:
        return f"<at id={open_id}></at>"
    return name


def daily_card_markdown(state: DailyCardState) -> str:
    lines = [
        f"**{state.date_key} AI+安全日报**",
        f"完成进度：**{state.done_count}/{state.total}**（已完成 / 应提交）",
    ]
    pending_names = "、".join(_at(n, oid) for n, oid in state.pending) or "无"
    lines.append(f"🟡 待补充（AI 建议待消化）：{pending_names}")
    not_sub = "、".join(state.not_submitted) or "无"
    lines.append(f"⚪ 未提交：{not_sub}")
    if state.eval_error:
        lines.append(f"🔴 评价异常（重试入口在本人私信卡片）：{'、'.join(state.eval_error)}")
    if state.published_at:
        lines.append(f"\n✅ 负责人日报**已发布**（{state.published_at}）")
    elif state.draft_markdown:
        lines.append("\n📋 负责人日报草稿已生成，待负责人核验发布 👇")
    if state.pending or state.not_submitted:
        if not state.published_at:
            lines.append("\n> 填写入口全天开放；负责人生成汇总前请先消化未完成名单。")
    return "\n".join(lines)


def daily_card_elements(state: DailyCardState) -> list[dict[str, Any]]:
    """入口卡按钮区：填写（全员）+ 生成/发布（负责人）。"""
    buttons = [callback_button("📝 填写今日日报", "open_form", btn_type="primary")]
    if state.published_at:
        pass  # 已发布：不再给生成/发布按钮
    elif state.draft_markdown:
        buttons.append(callback_button("🚀 发布负责人日报", "publish"))
    else:
        buttons.append(
            callback_button("📊 生成负责人日报", "gen_leader", btn_type="default"),
        )
    elements: list[dict[str, Any]] = [{"tag": "hr"}, button_row(*buttons)]
    if state.draft_markdown and not state.published_at:
        preview = {
            "tag": "markdown",
            "content": state.draft_markdown[:1200] + ("\n…（截断，发布后看全文）" if len(state.draft_markdown) > 1200 else ""),
        }
        elements = [preview, {"tag": "hr"}, *elements]  # 预览 → hr → hr+按钮
    return elements


def build_daily_card(state: DailyCardState) -> dict[str, Any]:
    return build_card_dict(
        "AI+安全日报",
        daily_card_markdown(state),
        header_template="green" if state.published_at else "orange",
        elements=daily_card_elements(state),
    )


# ═══════════════════════════════════════════════════════════
# DM 卡（建议 / 失败 / 修改入口）
# ═══════════════════════════════════════════════════════════

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
    from .evaluation import SECTION_LABELS

    for key in ("work", "done", "issue", "plan"):
        text = (sections.get(key) or "").strip()
        if text:
            lines.append(f"- **{SECTION_LABELS[key]}**：{text}")
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
