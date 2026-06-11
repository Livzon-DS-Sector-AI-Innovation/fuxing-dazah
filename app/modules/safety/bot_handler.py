"""安全模块机器人指令处理。

交互流程：
1. 私聊发送图片 → 机器人缓存图片 → 返回卡片表单
2. 群聊 @机器人 登记 → 返回卡片表单
3. 用户填写表单提交 → card.action.trigger → 创建隐患 + AI 识别
4. @机器人 查询 [编号] → 查询状态
"""

import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.feishu.notification import send_user_card
from app.modules.safety.models import HazardReport

logger = logging.getLogger(__name__)

settings = get_settings()

# UUID 已在 card value 中转为字符串，notification 层 _json_dumps 兜底

# 临时缓存：open_id → {"image_path": str, "sender_name": str}
_pending: dict[str, dict[str, str]] = {}


# ── 检查类别选项 ──
INSPECTION_CATEGORIES = [
    {"text": "日常检查", "value": "日常检查"},
    {"text": "专项检查", "value": "专项检查"},
    {"text": "季节性检查", "value": "季节性检查"},
    {"text": "节假日检查", "value": "节假日检查"},
    {"text": "综合性检查", "value": "综合性检查"},
    {"text": "事故类比排查", "value": "事故类比排查"},
    {"text": "外部检查", "value": "外部检查"},
]


async def _download_message_resource(message_id: str, file_key: str, resource_type: str) -> bytes:
    """下载消息中的资源文件。"""
    import httpx

    from app.modules.safety.feishu.client import get_safety_feishu_client as get_client
    from app.modules.safety.feishu.client import get_safety_tenant_token as get_token

    client = await get_client()
    token = await get_token(client)

    url = (
        f"https://open.feishu.cn/open-apis/im/v1/messages"
        f"/{message_id}/resources/{file_key}?type={resource_type}"
    )

    async with httpx.AsyncClient(timeout=30) as http_client:
        resp = await http_client.get(url, headers={"Authorization": f"Bearer {token}"})
        logger.info("下载消息资源: status=%s len=%d", resp.status_code, len(resp.content))
        if resp.status_code == 200:
            return resp.content
        logger.error("下载消息资源失败: status=%s body=%s", resp.status_code, resp.text[:200])
    return b""


async def _save_uploaded_image(image_data: bytes, hazard_id: str) -> str:
    """保存上传的图片到本地。"""
    import os
    upload_dir = os.path.join("uploads", "safety", "hazard")
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"hazard_{hazard_id}_{int(datetime.now().timestamp())}.jpg"
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "wb") as f:
        f.write(image_data)
    return file_path.replace("\\", "/")


async def _get_db_session() -> AsyncSession:
    """获取数据库会话。"""
    from app.core.database import async_session_factory
    return async_session_factory()


async def _create_hazard_full(
    description: str,
    location: str,
    department: str,
    inspection_category: str,
    discovered_by_name: str,
    image_path: str | None,
) -> HazardReport | None:
    """创建隐患并上传图片、触发 AI 流程。"""
    from app.modules.safety.schemas import HazardReportCreate
    from app.modules.safety.service import SafetyService

    session = await _get_db_session()
    try:
        service = SafetyService(session)

        data = HazardReportCreate(
            inspection_category=inspection_category or "日常检查",
            location=location or "未知",
            department=department or "未知",
            description=description or "待AI填写",
            discovered_by_name=discovered_by_name or "飞书用户",
        )

        item = await service.create_hazard(data)
        await session.commit()

        # 上传图片 + 触发 AI
        if image_path and item:
            item = await service.upload_hazard_photo(item.id, "feishu_bot.jpg", image_path)
            await session.commit()

            if item:
                item = await service.run_hazard_ai_script(item.id, 1)
                if item and not item.ai_error_message:
                    item = await service.run_hazard_ai_script(item.id, 2)
                await session.commit()

        logger.info("机器人创建隐患成功: hazard_no=%s", item.hazard_no if item else "?")
        return item

    except Exception:
        logger.exception("机器人创建隐患失败")
        await session.rollback()
        return None
    finally:
        await session.close()


def _build_form_card(image_saved: bool) -> dict:
    """构建隐患登记表单卡片。"""
    elements = []

    if image_saved:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "📷 **照片已接收**\n请填写以下信息后提交："},
        })
        elements.append({"tag": "hr"})

    # 表单（字段 + 提交按钮都在 form 内部，按钮不带 name 以免被当作表单字段）
    elements.append({
        "tag": "form",
        "name": "hazard_form",
        "elements": [
            {
                "tag": "select_static",
                "name": "inspection_category",
                "placeholder": {"tag": "plain_text", "content": "请选择检查类别"},
                "options": [
                    {"text": {"tag": "plain_text", "content": opt["text"]}, "value": opt["value"]}
                    for opt in INSPECTION_CATEGORIES
                ],
            },
            {
                "tag": "input",
                "name": "location",
                "label": {"tag": "plain_text", "content": "地点/部位"},
                "placeholder": {"tag": "plain_text", "content": "如：合成车间A区"},
            },
            {
                "tag": "input",
                "name": "department",
                "label": {"tag": "plain_text", "content": "责任部门"},
                "placeholder": {"tag": "plain_text", "content": "如：生产部"},
            },
            {
                "tag": "input",
                "name": "description",
                "label": {"tag": "plain_text", "content": "隐患描述（可选）"},
                "placeholder": {"tag": "plain_text", "content": "简要描述隐患情况"},
            },
            # 提交按钮：action_type="form_submit" 是关键，标识为表单提交按钮
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✅ 提交登记"},
                "type": "primary",
                "action_type": "form_submit",
                "name": "submit_btn",
                "value": {"action": "submit_hazard"},
                "confirm": {
                    "title": {"tag": "plain_text", "content": "确认提交"},
                    "text": {"tag": "plain_text", "content": "确认提交此隐患登记？"},
                },
            },
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📋 隐患登记"},
            "template": "orange",
        },
        "elements": elements,
    }


async def _send_form_card(open_id: str, image_saved: bool) -> None:
    """发送隐患登记表单卡片。"""
    card = _build_form_card(image_saved)
    card_json = json.dumps(card, ensure_ascii=False)

    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    from app.modules.safety.feishu.client import (
        get_safety_feishu_client,
        get_safety_tenant_token,
    )

    client = await get_safety_feishu_client()
    token = await get_safety_tenant_token(client)

    req = (
        CreateMessageRequest.builder()
        .receive_id_type("open_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(open_id)
            .msg_type("interactive")
            .content(card_json)
            .build()
        )
        .build()
    )
    req.headers["Authorization"] = f"Bearer {token}"
    resp = await client.im.v1.message.acreate(req)
    if resp.success():
        logger.info("发送表单卡片: success=True")
    else:
        logger.error("发送表单卡片失败: code=%s msg=%s status_code=%s",
                     resp.code, resp.msg, getattr(resp, 'status_code', 'N/A'))


# ═══════════════════════════════════════════════
# 事件处理器
# ═══════════════════════════════════════════════

@on_event("im.message.receive_v1")
async def handle_bot_message(event: dict) -> None:
    """处理机器人收到的消息。"""
    message = event.get("message", {})
    sender = event.get("sender", {})
    sender_open_id = sender.get("sender_id", {}).get("open_id", "")
    chat_type = message.get("chat_type", "")

    if not sender_open_id:
        return

    # 获取发送者姓名（用于发现人）
    sender_name = sender.get("sender_id", {}).get("user_id", "")
    # 如果有 tenant_key，尝试获取更好的用户名
    tenant_key = sender.get("tenant_key", "")

    msg_type = message.get("message_type", "")
    logger.info("收到消息: type=%s chat=%s open_id=%s name=%s", msg_type, chat_type, sender_open_id, sender_name)

    # ── 图片消息（仅私聊）──
    if msg_type == "image":
        if chat_type == "group":
            await send_user_card(open_id=sender_open_id, title="📷 请私聊发送",
                                 content="请在机器人私聊窗口中发送隐患照片。\n💡 方式：点击机器人头像 → 发消息")
            return

        # 下载图片并缓存
        content_str = message.get("content", "{}")
        try:
            content = json.loads(content_str)
        except json.JSONDecodeError:
            content = {}
        image_key = content.get("image_key", "")
        message_id = message.get("message_id", "")

        if image_key and message_id:
            image_data = await _download_message_resource(message_id, image_key, "image")
            if image_data:
                # 保存到临时文件并缓存
                import os
                os.makedirs(os.path.join("uploads", "safety", "hazard", "tmp"), exist_ok=True)
                tmp_path = os.path.join("uploads", "safety", "hazard", "tmp",
                                        f"pending_{sender_open_id}_{int(datetime.now().timestamp())}.jpg")
                tmp_path = tmp_path.replace("\\", "/")
                with open(tmp_path, "wb") as f:
                    f.write(image_data)

                _pending[sender_open_id] = {
                    "image_path": tmp_path,
                    "sender_name": sender_name,
                }
                logger.info("图片已缓存: open_id=%s path=%s", sender_open_id, tmp_path)
                await _send_form_card(sender_open_id, image_saved=True)
                return

        # 下载失败
        await send_user_card(open_id=sender_open_id, title="❌ 下载失败",
                             content="无法下载图片，请重试。")
        return

    # ── 文本消息 ──
    if msg_type == "text":
        content_str = message.get("content", "{}")
        try:
            c = json.loads(content_str)
        except json.JSONDecodeError:
            c = {}
        text = c.get("text", "").strip()
        # 移除 @ 提及
        text = text.replace("@_user_1", "").replace("@_all", "").strip()

        logger.info("文本消息: open_id=%s text=%s chat=%s", sender_open_id, text, chat_type)

        # 指令：登记 / 上报 → 发送表单卡片
        if text in ("登记", "上报", "登记隐患", "上报隐患") or text.startswith("登记 ") or text.startswith("上报 "):
            # 如果有额外描述，存入 pending
            extra = text.replace("登记隐患", "").replace("登记", "").replace("上报隐患", "").replace("上报", "").strip()
            _pending[sender_open_id] = {
                "image_path": "",
                "sender_name": sender_name,
                "extra_desc": extra,
            }
            await _send_form_card(sender_open_id, image_saved=False)
            return

        # 指令：查询
        if text.startswith("查询") or text.startswith("状态"):
            keyword = text.replace("查询", "").replace("状态", "").strip()
            if keyword:
                await _handle_query(sender_open_id, keyword)
                return

        # 私聊中任意消息也发送表单
        if chat_type == "p2p" and text:
            _pending[sender_open_id] = {
                "image_path": "",
                "sender_name": sender_name,
                "extra_desc": text,
            }
            await _send_form_card(sender_open_id, image_saved=False)
            return

        # 群聊默认回复
        if chat_type == "group":
            await send_user_card(
                open_id=sender_open_id,
                title="🤖 安全助手",
                content=(
                    "**群聊指令（需 @机器人）：**\n"
                    "- **登记 / 上报** → 打开登记表单\n"
                    "- **查询 [编号]** → 查询状态\n\n"
                    "**📷 发送隐患照片：**\n"
                    "请在机器人**私聊窗口**发送图片"
                ),
            )


@on_event("card.action.trigger")
async def handle_card_action(event: dict) -> None:
    """处理卡片交互事件（表单提交）。"""
    logger.info("卡片事件: %s", json.dumps(event, ensure_ascii=False)[:500])

    action = event.get("action", {})
    action_value = action.get("value", {})
    form_values = action.get("form_value", {})
    open_id = event.get("operator", {}).get("open_id", "")

    if not open_id:
        # 尝试从其他路径获取
        open_id = event.get("open_id", "")

    if not open_id:
        logger.warning("卡片事件无法获取 open_id")
        return

    # 解析 action value（直接比对字符串）
    act_type = ""
    if isinstance(action_value, dict):
        act_type = action_value.get("action", "")
    elif isinstance(action_value, str):
        act_type = action_value

    if act_type == "approve_hazard":
        hazard_id = action_value.get("hazard_id", 0) if isinstance(action_value, dict) else 0
        open_message_id = event.get("context", {}).get("open_message_id", "")
        return await _handle_approve(open_id, hazard_id, open_message_id)

    if act_type != "submit_hazard":
        logger.info("卡片事件未识别的 action，忽略: act_type=%s", act_type)
        return

    # 从缓存获取图片路径和发送者信息
    pending = _pending.pop(open_id, {})
    image_path = pending.get("image_path", "")
    sender_name = pending.get("sender_name", "")
    extra_desc = pending.get("extra_desc", "")

    # 从表单取值
    inspection_category = form_values.get("inspection_category", "日常检查")
    location = form_values.get("location", "未知")
    department = form_values.get("department", "未知")
    description = form_values.get("description", "") or extra_desc or "飞书上报"

    logger.info("卡片提交: open_id=%s cat=%s loc=%s dept=%s desc=%s img=%s",
                 open_id, inspection_category, location, department, description, bool(image_path))

    # 创建隐患
    item = await _create_hazard_full(
        description=description,
        location=location,
        department=department,
        inspection_category=inspection_category,
        discovered_by_name=sender_name or f"飞书用户({open_id})",
        image_path=image_path or None,
    )

    if item:
        detail_url = f"{settings.FRONTEND_URL}/safety/hazard/{item.id}"

        # 状态文案：AI 完成后为"待审核确认"，异常为"AI分析异常"，其他为"已登记"
        if item.ai_error_message:
            status_text = "AI 分析异常"
        elif item.overall_status == "completed":
            status_text = "待审核确认"
        else:
            status_text = "已登记"

        await send_user_card(
            open_id=open_id,
            title="✅ 隐患登记成功",
            content=(
                f"**隐患编号：** {item.hazard_no}\n"
                f"**检查类别：** {inspection_category}\n"
                f"**地点/部位：** {location}\n"
                f"**责任部门：** {department}\n"
                f"**描述：** {item.description or description}\n"
                f"**状态：** {status_text}"
            ),
            elements=[{
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "📋 前往台账"},
                        "type": "default",
                        "url": detail_url,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 审核通过"},
                        "type": "primary",
                        "value": {"action": "approve_hazard", "hazard_id": str(item.id)},
                        "confirm": {
                            "title": {"tag": "plain_text", "content": "确认审核"},
                            "text": {"tag": "plain_text", "content": "确认审核通过？审核后隐患将正式进入整改流程。"},
                        },
                    },
                ],
            }],
        )
    else:
        await send_user_card(
            open_id=open_id,
            title="❌ 登记失败",
            content="隐患创建失败，请重试或手动登记。",
        )


async def _handle_approve(open_id: str, hazard_id: int, open_message_id: str = "") -> dict | None:
    """处理审核通过操作：将隐患从 AI 审核阶段转入整改流程，返回更新后的卡片（通过 WebSocket 响应）。"""
    if not hazard_id:
        logger.warning("审核通过缺少 hazard_id")
        await send_user_card(open_id=open_id, title="❌ 操作失败", content="缺少隐患 ID。")
        return None

    session = await _get_db_session()
    try:
        from app.modules.safety.service import SafetyService

        service = SafetyService(session)
        import uuid
        hazard_uuid = uuid.UUID(str(hazard_id)) if not isinstance(hazard_id, uuid.UUID) else hazard_id
        item = await service.review_hazard_ai_script(hazard_uuid, 0, "approved")
        await session.commit()

        if not item:
            await send_user_card(open_id=open_id, title="❌ 操作失败",
                                 content="隐患不存在或状态不允许审核。")
            return None

        logger.info("审核通过成功: hazard_id=%s hazard_no=%s open_id=%s",
                     hazard_id, item.hazard_no, open_id)

        detail_url = f"{settings.FRONTEND_URL}/safety/hazard/{item.id}"

        # 返回更新后的卡片 → 由 event_client 通过 WebSocket 响应帧发回飞书
        # 飞书 card.action.trigger 回调要求响应格式：{"card": {"type": "raw", "data": <card JSON>}}
        updated_card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "✅ 隐患登记成功"},
                "template": "orange",
            },
            "elements": [
                {"tag": "markdown", "content": (
                    f"**隐患编号：** {item.hazard_no}\n"
                    f"**检查类别：** {item.inspection_category or '-'}\n"
                    f"**地点/部位：** {item.location or '-'}\n"
                    f"**责任部门：** {item.department or '-'}\n"
                    f"**描述：** {item.description or '-'}\n"
                    f"**状态：** 已审核通过，进入整改流程"
                )},
                {"tag": "action", "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "📋 前往台账"},
                        "type": "default",
                        "url": detail_url,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 已审核通过"},
                        "type": "primary",
                        "disabled": True,
                    },
                ]},
            ],
        }
        return {
            "toast": {"type": "success", "content": "审核通过，隐患已进入整改流程"},
            "card": {"type": "raw", "data": updated_card},
        }

    except Exception:
        logger.exception("审核通过失败: hazard_id=%s", hazard_id)
        await session.rollback()
        await send_user_card(open_id=open_id, title="❌ 操作失败",
                             content="审核操作异常，请重试或在网页端操作。")
        return None
    finally:
        await session.close()


async def _handle_query(open_id: str, keyword: str) -> None:
    """处理查询指令。"""
    session = await _get_db_session()
    try:
        from sqlalchemy import select

        query = select(HazardReport).where(
            HazardReport.hazard_no.ilike(f"%{keyword}%"),
        ).order_by(HazardReport.created_at.desc()).limit(5)

        result = await session.execute(query)
        hazards = result.scalars().all()

        if not hazards:
            await send_user_card(open_id=open_id, title="🔍 查询结果",
                                 content=f"未找到匹配「{keyword}」的隐患记录。")
            return

        status_map = {
            "pending": "待整改", "in_progress": "整改中", "replied": "待复核",
            "level1_approved": "一级已通过", "level2_approved": "二级已通过",
            "rejected": "已驳回", "closed": "已关闭",
        }
        lines = []
        for h in hazards[:5]:
            s = status_map.get(h.rectification_status or "", h.rectification_status or "未知")
            lines.append(f"- **{h.hazard_no}** [{s}] {h.description[:30] or '-'}")

        await send_user_card(open_id=open_id, title=f"🔍 查询结果（{len(hazards)} 条）",
                             content="\n".join(lines))
    except Exception:
        logger.exception("查询隐患失败")
    finally:
        await session.close()
