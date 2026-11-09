"""P1-3 例外复核 observe 确认卡 —— 构建 / 发送 / 回调（仅改卡片状态）。

observe 铁律在卡片层的体现：

- 标题与正文显式标注「observe · 不写回」；
- 按钮只有「收到 / 忽略」（ack/dismiss），**没有任何执行语义**——回调仅
  PATCH 卡片终态文案，不存在写回/通知/任务触发路径；
- 与 Agent 确认流（PendingAction confirm/cancel）完全隔离，卡片 scope=
  ``hazard_exception_review`` 独立路由。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.modules.safety.feishu.notification import (
    build_card_dict,
    button_row,
    send_group_card,
    update_card,
)
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    ExceptionReviewReport,
    ReviewRunResult,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CARD_SCOPE",
    "build_exception_review_card",
    "extract_button_values",
    "handle_review_card_action",
    "send_review_summary_card",
]

CARD_SCOPE = "hazard_exception_review"

_CARD_TITLE = "隐患例外复核报告 — observe · 不写回"


def _callback_button(value: dict[str, Any], text: str, btn_type: str) -> dict[str, Any]:
    """回调按钮（value 携带 scope/action/record_id；behaviors 双写兼容）。"""
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": btn_type,
        "value": value,
        "behaviors": [{"type": "callback", "value": value}],
    }


def _report_markdown(report: ExceptionReviewReport) -> str:
    """单条复核报告的 markdown 摘要（候选证据语义，人工为准）。"""
    label = str(report.exception_label.value)
    source = str(report.review_source.value)
    action = str(report.proposed_action.value)
    basis = report.ai_conclusion.major_hazard_basis or "（无可用依据）"
    rescued_mark = "✅ rescued" if report.rescued else "—"
    diff_lines = "".join(
        f"\n  - {d.field}: AI={d.ai_value or '空'} / 人工={d.manual_value or '空'}"
        f"（{'一致' if d.agree else '分歧'}）"
        for d in report.diff
    ) or "\n  - （无可比对字段）"
    failure = report.failure_reason or "—"
    return (
        f"**{report.record_id}** [{label}]（{source}）· {rescued_mark}\n"
        f"- 失败原因：{failure}\n"
        f"- AI 新结论依据：{basis[:160]}\n"
        f"- 建议动作：{action}\n"
        f"- AI vs 人工：{diff_lines}"
    )


def build_exception_review_card(report: ExceptionReviewReport) -> dict[str, Any]:
    """单条复核报告卡（observe · 不写回；按钮=收到/忽略）。"""
    value_ack = {
        "scope": CARD_SCOPE,
        "action": "ack",
        "record_id": report.record_id,
    }
    value_dismiss = {
        "scope": CARD_SCOPE,
        "action": "dismiss",
        "record_id": report.record_id,
    }
    content = (
        "⚠️ **observe 模式**：以下为 AI 复核员的**候选证据**，不写回任何表格列；"
        "人工列唯一权威，是否采纳由安全管理员决定。\n\n"
        + _report_markdown(report)
    )
    return build_card_dict(
        _CARD_TITLE,
        content,
        header_template="turquoise",
        elements=[
            {"tag": "hr"},
            button_row(
                _callback_button(value_ack, "✅ 收到", "primary"),
                _callback_button(value_dismiss, "已忽略", "default"),
            ),
        ],
    )


def extract_button_values(card: dict[str, Any]) -> list[dict[str, Any]]:
    """从卡片结构提取本域按钮 value（测试与回调校验共用）。"""
    values: list[dict[str, Any]] = []
    body = card.get("body") or {}
    for element in body.get("elements", []):
        columns = element.get("columns") or []
        for column in columns:
            for inner in column.get("elements", []):
                value = inner.get("value")
                if isinstance(value, dict) and value.get("scope") == CARD_SCOPE:
                    values.append(value)
    return values


async def handle_review_card_action(
    payload: dict[str, Any], event_data: dict[str, Any]
) -> bool:
    """卡片回调：ack/dismiss 仅 PATCH 卡片终态（无任何执行/写路径）。

    未知动作（尤其任何写语义的 value）一律不处理并返回 False。
    """
    action = str(payload.get("action") or "")
    if action not in ("ack", "dismiss"):
        logger.warning("例外复核卡片未知动作，忽略: %r", payload)
        return False
    message_id = (
        event_data.get("open_message_id")
        or event_data.get("context", {}).get("open_message_id")
        or ""
    )
    record_id = str(payload.get("record_id") or "")
    state_text = "✅ 已收到（observe 留痕，不写回）" if action == "ack" else "已忽略（observe 留痕，不写回）"
    card = build_card_dict(
        _CARD_TITLE,
        f"**{record_id}** · {state_text}",
        header_template="grey",
    )
    if message_id:
        await update_card(message_id, card)
    return True


async def send_review_summary_card(
    chat_id: str, result: ReviewRunResult
) -> str | None:
    """一批复核结果的汇总卡（每条报告一卡逐条发送 + 末尾汇总卡）。

    Returns: 汇总卡 message_id（失败 None，不抛异常）。
    """
    for report in result.reports:
        card = build_exception_review_card(report)
        message_id = await _send_card_raw(chat_id, card)
        if message_id is None:
            logger.warning(
                "例外复核单卡发送失败（继续后续）: record_id=%s", report.record_id
            )
    summary = (
        f"📋 **例外复核汇总（observe · 不写回）**\n\n"
        f"- 已复核：{result.reviewed} 条\n"
        f"- rescued：{result.rescued} 条\n"
        f"- 因每日上限未复核：{result.skipped} 条"
        + (f"（{result.stopped_reason}）" if result.stopped_reason else "")
        + "\n\n详见上方单条报告卡；看板路径：安全 → AI 识别质量 → 例外复核 Tab。"
    )
    return await send_group_card(
        chat_id, "例外复核汇总 — observe", summary, header_template="turquoise"
    )


async def _send_card_raw(chat_id: str, card: dict[str, Any]) -> str | None:
    """按 message_id 通道发送已构建卡片（复用 notification 发送链）。"""
    try:
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        from app.modules.safety.feishu.client import (
            get_safety_feishu_client,
            get_safety_tenant_token,
        )

        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(json.dumps(card, ensure_ascii=False, default=str))
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.acreate(req)
        if not resp.success():
            logger.error("例外复核卡片发送失败: code=%s msg=%s", resp.code, resp.msg)
            return None
        return resp.data.message_id if resp.data else None
    except Exception:  # noqa: BLE001 — 发卡失败不阻断复核流程
        logger.exception("例外复核卡片发送异常")
        return None
