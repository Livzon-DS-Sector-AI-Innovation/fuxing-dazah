"""职称评审飞书通知卡片（v3）。

- 结果卡：只含结果，不含评委名单与投票明细（评委名单对申报人保密）
- 评委待投票提醒卡：附匿名评审人编号，提示登录内网系统投票
open_id 优先取 hr.employees.feishu_open_id（覆盖未登录内网的员工），兜底 identity.users。
"""

import json
import logging
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import async_session_factory

logger = logging.getLogger(__name__)


async def _get_feishu_token() -> str:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": settings.FEISHU_APP_ID,
                "app_secret": settings.FEISHU_APP_SECRET,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("tenant_access_token", "")
        if not token:
            raise RuntimeError("获取飞书token失败: " + json.dumps(data))
        return str(token)


async def _lookup_open_id(name: str) -> str | None:
    """按姓名查 open_id：优先 hr.employees（通讯录同步），兜底 identity.users。"""
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text(
                    "SELECT feishu_open_id FROM hr.employees "
                    "WHERE name = :name AND is_deleted = false "
                    "AND feishu_open_id IS NOT NULL LIMIT 1"
                ),
                {"name": name},
            )
            row = result.fetchone()
            if row and row[0]:
                return str(row[0])
            result = await db.execute(
                text(
                    "SELECT feishu_open_id FROM identity.users "
                    "WHERE name = :name AND is_deleted = false "
                    "AND feishu_open_id IS NOT NULL LIMIT 1"
                ),
                {"name": name},
            )
            row = result.fetchone()
            if row and row[0]:
                return str(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("查找open_id失败(%s): %s", name, exc)
    logger.warning("未找到用户 %s 的飞书open_id，无法推送", name)
    return None


async def _send_card(open_id: str, card: dict[str, Any]) -> bool:
    try:
        token = await _get_feishu_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "open_id"},
                json={
                    "receive_id": open_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card),
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("发送飞书消息异常: %s", exc)
        return False


def _action_button(text: str, action: str, application_id: UUID, button_type: str = "primary") -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
        "value": {"action": action, "application_id": str(application_id)},
    }


async def send_dept_review_card(
    *,
    manager_name: str,
    activity_name: str,
    applicant_name: str,
    apply_level: str,
    sequence: str,
    application_id: UUID,
) -> bool:
    """给部门负责人发初审卡片（按钮：通过/退回）。"""
    open_id = await _lookup_open_id(manager_name)
    if not open_id:
        return False
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 职称申报初审 — {activity_name}"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**{manager_name}**，您好！\n\n"
                    f"{applicant_name} 申报 **{sequence}·{apply_level}**，"
                    "请核对申报材料并进行部门初审。"
                ),
            },
            {
                "tag": "action",
                "actions": [
                    _action_button("通过", "title_dept_approve", application_id),
                    _action_button("退回", "title_dept_reject", application_id, button_type="danger"),
                ],
            },
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "通过后申报将进入评委投票环节。"}],
            },
        ],
    }
    return await _send_card(open_id, card)


async def send_final_review_card(
    *,
    leader_name: str,
    applicant_name: str,
    apply_level: str,
    vote_summary: str,
    application_id: UUID,
) -> bool:
    """给分管领导发终审卡片（按钮：审定通过/审定驳回）。"""
    open_id = await _lookup_open_id(leader_name)
    if not open_id:
        return False
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🔎 职称评审终审"},
            "template": "orange",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**{leader_name}**，您好！\n\n"
                    f"{applicant_name} 申报 **{apply_level}** 已通过评委投票，"
                    f"投票情况：{vote_summary}。\n请进行最终审定。"
                ),
            },
            {
                "tag": "action",
                "actions": [
                    _action_button("审定通过", "title_final_approve", application_id),
                    _action_button("审定驳回", "title_final_reject", application_id, button_type="danger"),
                ],
            },
        ],
    }
    return await _send_card(open_id, card)


async def send_result_card(
    *,
    applicant_name: str,
    activity_name: str,
    level_name: str,
    passed: bool,
) -> bool:
    """给申报人发结果卡（不透露评委名单与投票明细）。"""
    open_id = await _lookup_open_id(applicant_name)
    if not open_id:
        return False
    emoji = "🎉" if passed else "💪"
    result_text = "通过" if passed else "未通过"
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{emoji} 职称评审结果 — {activity_name}"},
            "template": "green" if passed else "orange",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**{applicant_name}**，您好！\n\n"
                    f"您申报的 **{level_name}** 评审结果：**{result_text}**"
                ),
            },
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "如有疑问请联系人力资源部。"}],
            },
        ],
    }
    return await _send_card(open_id, card)


async def send_judge_reminder(
    *,
    judge_name: str,
    activity_name: str,
    applicant_name: str,
    judge_code: str,
) -> bool:
    """给评委发待投票提醒卡（附匿名评审人编号）。"""
    open_id = await _lookup_open_id(judge_name)
    if not open_id:
        return False
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🗳 职称评审投票提醒 — {activity_name}"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**{judge_name}**，您好！\n\n"
                    f"您有新的投票任务（{applicant_name} 的申报）。\n"
                    "请登录内网系统「职称评审」的「我的投票」页面完成投票。"
                ),
            },
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": "投票结果仅用于评审汇总，评委之间互不可见。"}
                ],
            },
        ],
    }
    return await _send_card(open_id, card)
