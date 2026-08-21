"""飞书审核消息推送服务"""

import json
import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def _get_feishu_token() -> str:
    """通过 HTTP 直接获取 tenant_access_token（不依赖 lark_oapi 版本）"""
    import httpx
    settings = get_settings()
    resp = httpx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": settings.FEISHU_APP_ID, "app_secret": settings.FEISHU_APP_SECRET},
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("tenant_access_token", "")
    if not token:
        raise RuntimeError("获取飞书token失败: " + json.dumps(data))
    return token


async def _lookup_open_id(name: str) -> str | None:
    """通过姓名查找飞书open_id（仅查 identity.users，系统登录过的用户）"""
    try:
        from sqlalchemy import text
        from app.core.database import async_session_factory
        async with async_session_factory() as db:
            r = await db.execute(
                text("SELECT feishu_open_id FROM identity.users WHERE name = :name AND is_deleted = false LIMIT 1"),
                {"name": name},
            )
            row = r.fetchone()
            if row and row[0]:
                return row[0]
        logger.warning(f"未找到系统用户: {name}（未登录过系统，无法推送）")
        return None
    except Exception as e:
        logger.warning(f"查找open_id失败({name}): {e}")
        return None


async def _send_card(open_id: str, card: dict) -> bool:
    """发送飞书卡片消息给指定用户（纯 HTTP，不依赖 lark_oapi 版本）"""
    try:
        import httpx
        token = await _get_feishu_token()
        resp = httpx.post(
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
    except Exception as e:
        logger.warning(f"发送飞书消息异常: {e}")
        return False


async def send_review_card(review, candidate, jd, push_note: str | None) -> bool:
    """发送审核卡片给用人部门负责人"""
    reviewer_name = review.reviewer
    if not reviewer_name:
        logger.warning("未设置审核人，跳过发送")
        return False

    open_id = await _lookup_open_id(reviewer_name)
    if not open_id:
        logger.warning(f"无法找到审核人{reviewer_name}的飞书open_id，跳过发送")
        return False

    # 构造简历摘要
    info_lines = [f"**{candidate.name}**"]
    if candidate.education:
        info_lines.append(f"{candidate.education}")
    if candidate.school:
        info_lines.append(f"{candidate.school}")
    if candidate.major:
        info_lines.append(f"{candidate.major}")
    if candidate.work_years is not None:
        info_lines.append(f"{candidate.work_years}年工作经验")
    if candidate.current_company:
        info_lines.append(f"现就职：{candidate.current_company}")

    md_content = "\n".join(info_lines)
    if push_note:
        md_content += f"\n\n> HR备注：{push_note}"

    jd_name = jd.position_name if jd else candidate.position or "未知岗位"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 候选人推送 — {jd_name}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": md_content},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看详情并审核"},
                        "type": "primary",
                        "url": f"{_get_base_url()}/hr/recruitment/{candidate.id}",
                    }
                ],
            },
        ],
    }

    return await _send_card(open_id, card)


async def send_decision_notification(review, candidate, decision: str, comment: str | None) -> bool:
    """通知HR审核结果"""
    hr_name = review.pushed_by
    if not hr_name:
        return False

    open_id = await _lookup_open_id(hr_name)
    if not open_id:
        return False

    cname = candidate.name if candidate else "候选人"
    emoji = "✅" if decision == "已同意" else "❌"
    status_text = "已同意面试" if decision == "已同意" else "不通过"

    md_content = f"**{cname}** 的审核结果：{emoji} {status_text}"
    if comment:
        md_content += f"\n\n审核意见：{comment}"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📢 审核结果 — {cname}"},
            "template": "green" if decision == "已同意" else "red",
        },
        "elements": [
            {"tag": "markdown", "content": md_content},
        ],
    }

    return await _send_card(open_id, card)


def _get_base_url() -> str:
    """获取系统前端地址"""
    settings = get_settings()
    return getattr(settings, "APP_BASE_URL", "http://localhost:3000")
