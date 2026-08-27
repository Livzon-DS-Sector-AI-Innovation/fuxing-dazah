"""职称评审飞书通知卡片（v3）。

- 结果卡：只含结果，不含评委名单与投票明细（评委名单对申报人保密）
- 评委待投票提醒卡：附匿名评审人编号，提示登录内网系统投票
open_id 优先取 hr.employees.feishu_open_id（覆盖未登录内网的员工），兜底 identity.users。
消息发送统一走平台集成 app/platform/integrations/feishu/notification.py。
"""

import logging
from typing import Any

from sqlalchemy import text

from app.core.database import async_session_factory

logger = logging.getLogger(__name__)


async def _lookup_open_id(name: str) -> str | None:
    """按姓名查 open_id：优先 hr.employees（通讯录同步），兜底 identity.users。

    同名多人且 open_id 不一致时返回 None（无法唯一定位，宁可不发也不发错人）。
    """
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text(
                    "SELECT DISTINCT feishu_open_id FROM hr.employees "
                    "WHERE name = :name AND is_deleted = false "
                    "AND feishu_open_id IS NOT NULL"
                ),
                {"name": name},
            )
            rows = result.fetchall()
            if len(rows) == 1 and rows[0][0]:
                return str(rows[0][0])
            if len(rows) > 1:
                logger.warning("按姓名查到 %d 个 open_id，无法唯一定位，跳过: %s", len(rows), name)
                return None
            result = await db.execute(
                text(
                    "SELECT DISTINCT feishu_open_id FROM identity.users "
                    "WHERE name = :name AND is_deleted = false "
                    "AND feishu_open_id IS NOT NULL"
                ),
                {"name": name},
            )
            rows = result.fetchall()
            if len(rows) == 1 and rows[0][0]:
                return str(rows[0][0])
            if len(rows) > 1:
                logger.warning("按姓名查到 %d 个 open_id（identity），无法唯一定位，跳过: %s", len(rows), name)
                return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("查找open_id失败(%s): %s", name, exc)
    logger.warning("未找到用户 %s 的飞书open_id，无法推送", name)
    return None


async def _send_card(open_id: str, card: dict[str, Any]) -> bool:
    """发送卡片（走平台集成层：SDK + token 管理 + 业务码校验）。

    必须用全局 FEISHU 应用发送：identity.users.feishu_open_id 由 SSO 登录
    （全局应用）产生，而 open_id 分应用域——用 HR 独立应用发送会被飞书拒绝
    （99992361 open_id cross app）。
    """
    from app.platform.integrations.feishu.notification import send_user_card

    try:
        return await send_user_card(open_id, card=card)
    except Exception as exc:  # noqa: BLE001
        logger.warning("发送飞书消息异常: %s", exc)
        return False


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
                    f"您有新的投票任务（{applicant_name} 的申报），您的匿名评审人编号为 **{judge_code}**。\n"
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
