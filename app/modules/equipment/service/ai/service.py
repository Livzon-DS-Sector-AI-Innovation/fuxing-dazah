"""巡检照片 AI 分析 — 业务流程编排。"""

import json
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment.models.inspection import InspectionTask
from app.modules.equipment.models.inspection_template import (
    InspectionTemplate,
    InspectionTemplateItem,
)
from app.modules.equipment.service.ai.client import AIAnalysisError, QwenClient
from app.modules.equipment.service.ai.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)


async def analyze_inspection_photo(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    image_base64: str,
    image_mime_type: str,
) -> list[dict]:
    """对巡检照片进行 AI 分析，返回每个检查项的分析结果。

    Args:
        db: 数据库会话
        task_id: 巡检任务 ID
        equipment_id: 设备 ID（用于检查任务状态归属）
        image_base64: 图片的 base64 编码（不含 data:xxx;base64, 前缀）
        image_mime_type: 图片 MIME 类型，如 image/jpeg

    Returns:
        检查项分析结果列表，每项包含:
        - template_item_id
        - item_name
        - expected_result
        - result (正常/异常/跳过)
        - actual_value
        - remark
    """
    # 1. 校验任务状态
    task = await _get_task(db, task_id)
    if task.status != "执行中":
        raise AppException(message="任务未在执行中状态，不能进行 AI 分析")

    # 2. 获取检查模板项
    items = await _get_template_items(db, task.template_id)
    if not items:
        raise AppException(message="该任务没有关联检查项")

    # 3. 构建提示词并调用 AI
    items_input = [
        {
            "item_name": item.item_name,
            "expected_result": item.expected_result,
        }
        for item in items
    ]
    user_prompt = build_user_prompt(items_input)

    client = QwenClient()
    try:
        raw_response = await client.analyze_image(
            image_base64=image_base64,
            image_mime_type=image_mime_type,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except AIAnalysisError:
        raise
    except httpx.RequestError as e:
        raise AppException(
            message=f"AI 服务连接失败: {str(e)}",
            status_code=502,
        ) from e
    finally:
        await client.close()

    # 4. 解析 AI 响应
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        raise AIAnalysisError("AI 返回结果不是有效 JSON", raw_response) from None

    ai_items = parsed.get("items", [])
    if not isinstance(ai_items, list) or len(ai_items) == 0:
        raise AIAnalysisError("AI 返回结果中没有有效的 items 数组", raw_response)

    # 5. 将 AI 结果按顺序映射到模板检查项
    results: list[dict] = []
    for i, item in enumerate(items):
        ai_item = ai_items[i] if i < len(ai_items) else {}
        result_value = ai_item.get("result", "跳过")
        if result_value not in ("正常", "异常", "跳过"):
            result_value = "跳过"

        results.append({
            "template_item_id": str(item.id),
            "item_name": item.item_name,
            "expected_result": item.expected_result,
            "result": result_value,
            "actual_value": ai_item.get("actual_value") or None,
            "remark": ai_item.get("remark") or None,
        })

    return results


async def _get_task(db: AsyncSession, task_id: uuid.UUID) -> InspectionTask:
    """获取巡检任务，不存在则抛 NotFoundException。"""
    result = await db.execute(
        select(InspectionTask)
        .options(selectinload(InspectionTask.template))
        .where(
            InspectionTask.id == task_id,
            InspectionTask.is_deleted == False,  # noqa: E712
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise NotFoundException("巡检任务", str(task_id))
    return task


async def _get_template_items(
    db: AsyncSession, template_id: uuid.UUID
) -> list[InspectionTemplateItem]:
    """获取模板的所有检查项，按 sort_order 排序。"""
    result = await db.execute(
        select(InspectionTemplate)
        .options(selectinload(InspectionTemplate.items))
        .where(
            InspectionTemplate.id == template_id,
            InspectionTemplate.is_deleted == False,  # noqa: E712
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise NotFoundException("检查模板", str(template_id))
    return sorted(template.items, key=lambda x: x.sort_order)
