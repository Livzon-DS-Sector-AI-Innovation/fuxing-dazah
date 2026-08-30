"""职称评审飞书通知卡片（v3）。

- 评委待投票提醒卡：附匿名评审人编号，提示登录内网系统投票
open_id 优先取 identity.users（SSO 全局应用域，与发送应用一致），
兜底 hr.employees.feishu_open_id（可能为其他应用域，仅作最后手段）。
消息发送统一走平台集成 app/platform/integrations/feishu/notification.py。
"""

import logging
from typing import Any

from sqlalchemy import text

from app.core.database import async_session_factory

logger = logging.getLogger(__name__)


async def _lookup_open_id(name: str) -> str | None:
    """按姓名查 open_id：优先 identity.users（SSO 全局应用域，与发送应用一致），
    兜底 hr.employees（可能为其他应用域，仅最后手段）。

    同名多人且 open_id 不一致时返回 None（无法唯一定位，宁可不发也不发错人）。
    """
    try:
        async with async_session_factory() as db:
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
            # 兜底：未登录过内网的员工（identity 无记录）用员工档案的 open_id
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
                logger.warning(
                    "用户 %s 仅命中员工档案 open_id（可能非全局应用域，存在跨应用风险）", name
                )
                return str(rows[0][0])
            if len(rows) > 1:
                logger.warning("按姓名查到 %d 个 open_id（员工档案），无法唯一定位，跳过: %s", len(rows), name)
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
