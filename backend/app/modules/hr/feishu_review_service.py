"""飞书审核消息推送服务"""

import json
import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def _get_client():
    import lark_oapi as lark
    settings = get_settings()
    return (
        lark.Client.builder()
        .app_id(settings.FEISHU_APP_ID)
        .app_secret(settings.FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )


async def _get_token(client: Any) -> str:
    import lark_oapi as lark
    from lark_oapi.api.auth.v3 import InternalTenantAccessTokenRequest, InternalTenantAccessTokenRequestBody
    settings = get_settings()
    req = InternalTenantAccessTokenRequest.builder().request_body(
        InternalTenantAccessTokenRequestBody.builder()
        .app_id(settings.FEISHU_APP_ID)
        .app_secret(settings.FEISHU_APP_SECRET)
        .build()
    ).build()
    resp = await client.auth.v3.tenant_access_token.ainternal(req)
    if not resp.success():
        raise RuntimeError(f"获取token失败: {resp.code} {resp.msg}")
    if resp.raw and resp.raw.content:
        return json.loads(resp.raw.content.decode("utf-8")).get("tenant_access_token", "")
    raise RuntimeError("空token响应")


async def _lookup_open_id(name: str) -> str | None:
    """通过姓名查找飞书open_id"""
    try:
        import lark_oapi as lark
        from lark_oapi.api.contact.v3 import BatchGetIdUserRequest, BatchGetIdUserRequestBody, UserContactInfo
        client = await _get_client()
        token = await _get_token(client)
        req = BatchGetIdUserRequest.builder().request_body(
            BatchGetIdUserRequestBody.builder()
            .include_resigned(False)
            .user_id_type("open_id")
            .mobiles([])
            .emails([])
            .build()
        ).build()
        # 飞书批量查询ID API需要先有邮箱/手机，这里简化处理：
        # 直接用搜索API按姓名搜用户
        from lark_oapi.api.contact.v3 import SearchUserRequest
        search_req = SearchUserRequest.builder().query(name).page_size(1).build()
        resp = await client.contact.v3.user.asearch(search_req, lark.AccessTokenType.TENANT, token)
        if resp.success() and resp.data and resp.data.items:
            return resp.data.items[0].open_id
        logger.warning(f"未找到飞书用户: {name}")
        return None
    except Exception as e:
        logger.warning(f"查找open_id失败({name}): {e}")
        return None


async def _send_card(open_id: str, card: dict) -> bool:
    """发送飞书卡片消息给指定用户"""
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        client = await _get_client()
        token = await _get_token(client)
        req = CreateMessageRequest.builder().request_body(
            CreateMessageRequestBody.builder()
            .receive_id(open_id)
            .msg_type("interactive")
            .content(json.dumps(card))
            .build()
        ).build()
        resp = await client.im.v1.message.acreate(req, lark.AccessTokenType.TENANT, token)
        if not resp.success():
            logger.warning(f"发送飞书消息失败: {resp.code} {resp.msg}")
            return False
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
