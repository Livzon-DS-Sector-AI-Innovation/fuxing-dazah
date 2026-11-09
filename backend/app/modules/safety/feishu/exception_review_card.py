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
    "WRITEBACK_LABELS",
    "build_exception_review_card",
    "build_writeback_result_card",
    "extract_button_values",
    "handle_review_card_action",
    "send_review_summary_card",
]

CARD_SCOPE = "hazard_exception_review"

_CARD_TITLE = "隐患例外复核报告 — observe · 不写回"

# P2-1：写回状态 → 卡片标题后缀（observe 批/未触达报告保持原标题不变）
_WRITEBACK_TITLE_SUFFIX: dict[str, str] = {
    "success": "auto · 已写回 AI 列",
    "failed": "auto · 写回失败",
    "cas_conflict": "auto · 冲突放弃",
    "gate_blocked": "auto · 闸门拦截",
    "pending_confirm": "待人工确认",
}

# 写回状态 → 中文（与前端 HazardQualityPanel.WRITEBACK_LABELS 同口径）
WRITEBACK_LABELS: dict[str, str] = {
    "not_attempted": "未写回",
    "pending_confirm": "待人工确认",
    "success": "已写回",
    "failed": "写回失败",
    "cas_conflict": "冲突放弃",
    "gate_blocked": "闸门拦截",
}


def _card_title(report: ExceptionReviewReport) -> str:
    suffix = _WRITEBACK_TITLE_SUFFIX.get(report.writeback)
    return (
        f"隐患例外复核报告 — {suffix}"
        if suffix
        else _CARD_TITLE
    )


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
    """单条复核报告的 markdown 摘要（候选证据语义，人工为准）。

    P2-1：writeback 已触达（非 not_attempted）时追加写回状态行；
    observe 批全为 not_attempted，产出与 P1-3 逐字节一致。
    """
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
    writeback_line = (
        f"- 写回状态：{WRITEBACK_LABELS.get(report.writeback, report.writeback)}"
        f"{f'（{report.writeback_note}）' if report.writeback_note else ''}\n"
        if report.writeback != "not_attempted"
        else ""
    )
    return (
        f"**{report.record_id}** [{label}]（{source}）· {rescued_mark}\n"
        f"- 失败原因：{failure}\n"
        f"- AI 新结论依据：{basis[:160]}\n"
        f"- 建议动作：{action}\n"
        f"{writeback_line}"
        f"- AI vs 人工：{diff_lines}"
    )


def build_exception_review_card(report: ExceptionReviewReport) -> dict[str, Any]:
    """单条复核报告卡（observe · 不写回；按钮=收到/忽略/有用/没用）。

    P2-1 F4：「有用/没用」= rescued 人工改判（回写 Redis 报告，
    effective_rescued=人工优先）；仍无任何写回/执行语义。
    """
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
    value_useful = {
        "scope": CARD_SCOPE,
        "action": "useful",
        "record_id": report.record_id,
    }
    value_useless = {
        "scope": CARD_SCOPE,
        "action": "useless",
        "record_id": report.record_id,
    }
    # P2-1：写回已触达（auto 批）正文头不再声明「不写回」；observe 批原文不变
    if report.writeback == "not_attempted":
        lead = (
            "⚠️ **observe 模式**：以下为 AI 复核员的**候选证据**，不写回任何表格列；"
            "人工列唯一权威，是否采纳由安全管理员决定。\n\n"
        )
    else:
        lead = (
            "ℹ️ **auto 批注**：本条已经分级处置（见「写回状态」行）；"
            "人工列唯一权威，AI 仅写 AI 列。\n\n"
        )
    content = (
        lead
        + _report_markdown(report)
        + "\n\n「有用/没用」= 对 rescued 判定的人工反馈（改判回写报告，可更改）。"
    )
    return build_card_dict(
        _card_title(report),
        content,
        header_template="turquoise",
        elements=[
            {"tag": "hr"},
            button_row(
                _callback_button(value_ack, "✅ 收到", "primary"),
                _callback_button(value_dismiss, "已忽略", "default"),
            ),
            button_row(
                _callback_button(value_useful, "👍 有用", "primary"),
                _callback_button(value_useless, "👎 没用", "default"),
            ),
        ],
    )


def build_writeback_result_card(
    reports: list[ExceptionReviewReport],
) -> dict[str, Any]:
    """auto 批逐条写回结果卡（D4：成功/失败/待确认/冲突 逐条状态一览）。

    一卡列全批（非逐条发卡，防刷屏）；仅列写回已触达的报告，按钮无——
    结果卡是通知不是动作入口（确认动作走安全助手会话）。
    """
    rows = "".join(
        f"- **{r.record_id}**：{WRITEBACK_LABELS.get(r.writeback, r.writeback)}"
        f"{f'（{r.writeback_note}）' if r.writeback_note else ''}\n"
        for r in reports
        if r.writeback != "not_attempted"
    ) or "- （本批无写回活动）\n"
    content = f"⚙️ **auto 写回结果（逐条）**\n\n{rows}"
    return build_card_dict("例外复核写回结果 — auto", content, header_template="turquoise")


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
    """卡片回调：ack/dismiss 仅 PATCH 终态；useful/useless 人工改判回写报告。

    - useful/useless（P2-1 F4）：``record_human_feedback`` 回写 Redis 报告
      （人工>程序；30 天窗口内可改判），再 PATCH 卡片终态；报告缺失仍
      PATCH「反馈失效」提示、返回 True（动作已受理，不重试不炸）；
    - 未知动作（尤其任何写回/执行语义的 value）一律不处理并返回 False。
    """
    action = str(payload.get("action") or "")
    if action not in ("ack", "dismiss", "useful", "useless"):
        logger.warning("例外复核卡片未知动作，忽略: %r", payload)
        return False
    message_id = (
        event_data.get("open_message_id")
        or event_data.get("context", {}).get("open_message_id")
        or ""
    )
    record_id = str(payload.get("record_id") or "")
    if action == "ack":
        state_text = "✅ 已收到（observe 留痕，不写回）"
    elif action == "dismiss":
        state_text = "已忽略（observe 留痕，不写回）"
    else:
        from app.modules.safety.service.hazard_direct.exception_reviewer import (
            record_human_feedback,
        )

        applied = await record_human_feedback(record_id, action)
        mark = "👍 有用" if action == "useful" else "👎 没用"
        state_text = (
            f"{mark} · 已改判 rescued（人工优先）"
            if applied
            else f"{mark} · 反馈失效（报告已过期或不存在）"
        )
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
    # P2-1 auto 标注（Q2C）：仅 auto 批切换标题/追加写回统计行并加发逐条结果卡；
    # observe 批（无写回活动）文案与 P1-3 逐字节一致。
    is_auto = result.has_writeback_activity
    auto_lines = ""
    if is_auto:
        auto_lines = (
            f"\n- 写回成功：{result.writeback_success} 条"
            f"｜失败：{result.writeback_failed} 条"
            f"｜**待人工确认：{result.pending_confirm} 条**"
            "（major/escalate——请在安全助手会话点名复核后确认写回）"
        )
        await _send_card_raw(chat_id, build_writeback_result_card(result.reports))
    batch_label = "auto · 分级写回" if is_auto else "observe · 不写回"
    summary = (
        f"📋 **例外复核汇总（{batch_label}）**\n\n"
        f"- 已复核：{result.reviewed} 条\n"
        f"- rescued：{result.rescued} 条\n"
        f"- 因每日上限未复核：{result.skipped} 条"
        + (f"（{result.stopped_reason}）" if result.stopped_reason else "")
        + auto_lines
        + "\n\n详见上方单条报告卡；看板路径：安全 → AI 识别质量 → 例外复核 Tab。"
    )
    return await send_group_card(
        chat_id,
        f"例外复核汇总 — {'auto' if is_auto else 'observe'}",
        summary,
        header_template="turquoise",
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
