"""AI+安全日报卡片回调——scope=daily_report / form 按钮 dr_submit。

2.9s ACK 契约（r3_card 同款）：
- submit / open_form / retry_eval：快路径同步执行（Bitable 写 + toast）
- gen_leader / publish：LLM/发卡慢操作 → 后台 task + toast，完成后 PATCH 群卡
铁律：按钮 value 是不可信静态内容，身份只认 event_data.operator.open_id。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.modules.safety.service.daily_report import cards, config, service

logger = logging.getLogger(__name__)


def _operator(event_data: dict[str, Any]) -> str:
    operator = event_data.get("operator", {})
    return (
        operator.get("open_id")
        or operator.get("user_id")
        or ""
    )


def _form_sections(event_data: dict[str, Any]) -> dict[str, str]:
    """form_value → 四段内容（input name = work/done/issue/plan）。"""
    form_value = event_data.get("action", {}).get("form_value", {}) or {}
    sections: dict[str, str] = {}
    for key in cards.SECTION_INPUT_NAMES:
        value = form_value.get(key)
        if isinstance(value, str):
            sections[key] = value.strip()
    return sections


def _required_keys() -> tuple[str, ...]:
    """必填段（明日计划外全部必填，无协调/风险填「暂无」）。"""
    return tuple(k for k in cards.SECTION_INPUT_NAMES if k != "plan")


def _log_task(coro: Any, *, tag: str, operator: str) -> None:  # pragma: no cover - 薄封装
    async def _runner() -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001 — 后台任务失败留日志不外抛
            logger.exception("日报后台任务失败: tag=%s operator=%s", tag, operator)

    try:
        asyncio.get_running_loop()
        asyncio.create_task(_runner())
    except RuntimeError:  # 无事件循环（测试环境）——直接丢弃
        coro.close()


async def handle_daily_report_card_action(
    payload: dict[str, Any],
    event_data: dict[str, Any],
) -> dict[str, Any] | None:
    """daily_report 卡片动作分发（business_agent_bot_handler 路由入口）。"""
    operator = _operator(event_data) or str(payload.get("operator_open_id") or "")
    action = str(payload.get("action") or "")
    # form 回调 action.value 不一定随回调返回（progress_card 先例）——按钮 name
    # 必然存在，dr_submit 即提交动作，缺失 value 时兜底，防提交静默丢弃
    if not action and event_data.get("action", {}).get("name") == cards.FORM_SUBMIT_NAME:
        action = "submit"
    date_key = config.normalize_date_key(payload.get("date_key"))

    if not config.enabled():
        return cards.toast("AI+安全日报功能未开启")

    if action == "submit":
        sections = _form_sections(event_data)
        if not all(sections.get(k) for k in _required_keys()):
            return {"toast": {"type": "error", "content": "明日计划外各段均为必填（无协调/风险请填「暂无」）"}}
        # 写表链含多次飞书 API（≈1s/次），2.9s ACK 窗口内只做纯校验，
        # 全链后台化；结果 PATCH 原表单卡为状态卡（无锚回退 DM）
        source_msg_id = str(event_data.get("context", {}).get("open_message_id") or "")
        _log_task(
            service.submit_and_notify(operator, sections, date_key, source_msg_id=source_msg_id),
            tag="submit", operator=operator,
        )
        return cards.toast("提交处理中，本卡片即将变更为结果状态…")

    if action == "open_form":
        _log_task(
            service.open_form_dm_notify(operator, date_key),
            tag="open_form", operator=operator,
        )
        return cards.toast("表单生成中，稍后私信给你 ✉️")

    if action == "retry_eval":
        _log_task(
            service.run_evaluation(date_key, operator, force=True),
            tag="retry_eval", operator=operator,
        )
        return cards.toast("AI 评价重试中，结果稍后私信你")

    if action == "gen_leader":
        _log_task(
            service.generate_leader(operator, date_key),
            tag="gen_leader", operator=operator,
        )
        return cards.toast("负责人日报生成中（仅汇总已完成最终版），稍后更新本卡")

    if action == "publish":
        _log_task(
            service.publish(operator, date_key),
            tag="publish", operator=operator,
        )
        return cards.toast("发布中，全文日报稍后发到群里")

    logger.warning("日报卡片未知动作: action=%s payload=%s", action, json.dumps(payload, ensure_ascii=False)[:200])
    return None
