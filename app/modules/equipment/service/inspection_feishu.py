"""巡检飞书交互服务 — 处理从飞书接收的巡检照片。

接收飞书图片消息 → 下载 → AI 分析 → 保存照片 → 回复结果卡片。
"""

import base64
import logging
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.modules.equipment.models.inspection import InspectionPhoto, InspectionTask
from app.platform.integrations.feishu.notification import send_user_card

logger = logging.getLogger(__name__)
settings = get_settings()

_UPLOAD_DIR = "uploads/inspection"
os.makedirs(_UPLOAD_DIR, exist_ok=True)


async def process_feishu_image(
    *,
    open_id: str,
    message_id: str,
    image_key: str,
    chat_id: str,
    chat_type: str,
) -> None:
    """处理从飞书收到的巡检照片。

    流程：查用户 → 查任务 → 下载图片 → AI 分析 → 保存照片 → 回复结果。
    """
    if not open_id:
        logger.warning("消息缺少 sender open_id，忽略")
        return

    async with async_session_factory() as db:
        # 1. 根据 open_id 查找用户
        user = await _find_user_by_open_id(db, open_id)
        if not user:
            await _reply_text(open_id, "未找到您的系统账号，请先在系统中完成飞书绑定。")
            return

        # 2. 查找该用户正在执行的巡检任务
        task = await _find_active_task(db, user.id)
        if not task:
            await _reply_text(
                open_id, "当前没有执行中的巡检任务。\n请先在系统中开始巡检。"
            )
            return

        # 3. 确定设备 ID
        equipment_id = _resolve_equipment_id(task)
        if not equipment_id:
            await _reply_text(open_id, "巡检任务未关联设备，请在系统中检查任务配置。")
            return

        # 4. 下载图片
        image_bytes, mime_type = await _download_image(message_id, image_key)
        if not image_bytes:
            await _reply_text(open_id, "图片下载失败，请重新发送。")
            return

        # 5. 保存照片
        photo = await _save_photo(db, task.id, equipment_id, image_bytes)
        logger.info("巡检照片已保存: task=%s, photo=%s", task.task_no, photo.id)

        # 6. AI 分析
        try:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            from app.modules.equipment.service.ai.service import (
                analyze_inspection_photo,
            )

            results = await analyze_inspection_photo(
                db=db,
                task_id=task.id,
                equipment_id=equipment_id,
                image_base64=image_b64,
                image_mime_type=mime_type or "image/jpeg",
            )
        except Exception as e:
            logger.exception("AI 分析失败: task=%s", task.task_no)
            await _reply_text(
                open_id, f"AI 分析失败：{e}\n照片已保存，请在系统中手动录入检查结果。"
            )
            return

        # 7. 发送结果卡片
        await _send_result_card(open_id, task, results)


async def _find_user_by_open_id(
    db: AsyncSession, open_id: str
) -> Any | None:
    """根据飞书 open_id 查找系统用户。"""
    from app.platform.identity.models import User

    result = await db.execute(
        select(User).where(
            User.feishu_open_id == open_id,
            User.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def _find_active_task(
    db: AsyncSession, user_id: uuid.UUID
) -> InspectionTask | None:
    """查找用户正在执行的最新巡检任务。"""
    result = await db.execute(
        select(InspectionTask)
        .options(
            selectinload(InspectionTask.equipment),
            selectinload(InspectionTask.template),
        )
        .where(
            InspectionTask.assigned_to == user_id,
            InspectionTask.status == "执行中",
            InspectionTask.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionTask.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _resolve_equipment_id(task: InspectionTask) -> uuid.UUID | None:
    """从巡检任务中确定设备 ID。"""
    # 单设备模式
    if task.equipment_id:
        return task.equipment_id
    # 多设备模式：取第一个
    if task.equipment_ids:
        first_id = task.equipment_ids[0]
        if isinstance(first_id, str):
            return uuid.UUID(first_id)
        return first_id
    return None


async def _download_image(
    message_id: str, image_key: str
) -> tuple[bytes | None, str | None]:
    """从飞书下载消息中的图片。

    Returns:
        (图片字节数据, MIME类型)，失败返回 (None, None)
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1.model.get_message_resource_request import (
        GetMessageResourceRequest,
    )

    client = (
        lark.Client.builder()
        .app_id(settings.FEISHU_APP_ID)
        .app_secret(settings.FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )

    req = (
        GetMessageResourceRequest.builder()
        .message_id(message_id)
        .file_key(image_key)
        .type("image")
        .build()
    )

    try:
        resp = await client.im.v1.message_resource.aget(req)
        if resp.code == 0 and resp.file:
            image_bytes = resp.file.read()
            logger.info(
                "图片下载成功: message_id=%s, size=%d bytes",
                message_id, len(image_bytes),
            )
            # 飞书图片默认 JPEG
            return image_bytes, "image/jpeg"
        else:
            logger.error(
                "图片下载失败: code=%s, msg=%s", resp.code, resp.msg
            )
            return None, None
    except Exception:
        logger.exception(
            "图片下载异常: message_id=%s, image_key=%s",
            message_id, image_key,
        )
        return None, None


async def _save_photo(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    image_bytes: bytes,
) -> InspectionPhoto:
    """保存巡检照片到文件和数据库。"""
    filename = f"{uuid.uuid4()}_feishu.jpg"
    file_path = os.path.normpath(os.path.join(_UPLOAD_DIR, filename))

    with open(file_path, "wb") as f:
        f.write(image_bytes)

    photo = InspectionPhoto(
        task_id=task_id,
        equipment_id=equipment_id,
        file_name=filename,
        file_path=file_path,
        file_size=len(image_bytes),
    )
    db.add(photo)
    await db.commit()

    # eager re-fetch to avoid MissingGreenlet
    result = await db.execute(
        select(InspectionPhoto).where(InspectionPhoto.id == photo.id)
    )
    return result.scalar_one()


async def _send_result_card(
    open_id: str,
    task: InspectionTask,
    results: list[dict],
) -> None:
    """构建并发送 AI 分析结果卡片。"""
    # 统计结果
    normal_count = sum(1 for r in results if r["result"] == "正常")
    abnormal_count = sum(1 for r in results if r["result"] == "异常")
    skip_count = sum(1 for r in results if r["result"] == "跳过")

    # 构建设备名
    equipment_name = task.equipment.name if task.equipment else "未知设备"

    # 构建结果列表
    lines = [
        f"**任务：**{task.task_no}",
        f"**设备：**{equipment_name}",
        "",
        "---",
        "**📋 AI 分析结果：**",
        "",
    ]

    for r in results:
        if r["result"] == "正常":
            icon = "✅"
        elif r["result"] == "异常":
            icon = "⚠️"
        else:
            icon = "⏭️"
        value = f" → {r['actual_value']}" if r.get("actual_value") else ""
        remark = f"（{r['remark']}）" if r.get("remark") else ""
        lines.append(f"{icon} **{r['item_name']}**：{r['result']}{value}{remark}")

    lines.append("")
    lines.append("---")
    lines.append(
        f"**汇总：** ✅ 正常 {normal_count} 项 | "
        f"⚠️ 异常 {abnormal_count} 项 | "
        f"⏭️ 跳过 {skip_count} 项"
    )
    lines.append("")
    lines.append("> 照片已保存，请在系统中确认或修改检查结果后提交。")

    content = "\n".join(lines)

    await send_user_card(
        open_id=open_id,
        title=f"🔍 巡检AI分析 - {equipment_name}",
        content=content,
    )


async def _reply_text(open_id: str, text: str) -> None:
    """发送纯文本提示卡片。"""
    await send_user_card(
        open_id=open_id,
        title="💬 巡检助手",
        content=text,
    )


