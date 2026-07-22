"""巡检照片 AI 分析 & 手动提交解析 — 业务流程编排。"""

import json
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.equipment.service.ai.client import AIAnalysisError, QwenClient
from app.modules.equipment.service.ai.prompts import (
    MANUAL_SUBMIT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_manual_submit_user_prompt,
    build_user_prompt,
)
from app.modules.equipment.service.inspection import (
    _get_task,
    get_inspection_items,
)


async def analyze_inspection_photo(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    image_base64: str,
    image_mime_type: str,
) -> list[dict[str, Any]]:
    """对巡检照片进行 AI 分析，返回每个检查项的分析结果。

    支持线路巡检（路线→地点→设备→模板链）和设备巡检（多模板合并）。

    Args:
        db: 数据库会话
        task_id: 巡检任务 ID
        equipment_id: 当前设备 ID
        image_base64: 图片的 base64 编码
        image_mime_type: 图片 MIME 类型

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

    # 2. 获取检查模板项（支持多模板合并）
    items, _ = await get_inspection_items(db, task, equipment_id)
    if not items:
        raise AppException(message="该设备没有关联检查项，请先在系统中配置")

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
    #    若 AI 返回数量不足，缺失项自动补"跳过"
    results: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        ai_item = ai_items[i] if i < len(ai_items) else {}
        result_value = ai_item.get("result", "跳过")
        if result_value not in ("正常", "异常", "跳过"):
            result_value = "跳过"
        remark = ai_item.get("remark") or None
        if i >= len(ai_items) and not remark:
            remark = "AI 未返回该检查项结果"

        results.append({
            "template_item_id": str(item.id),
            "item_name": item.item_name,
            "expected_result": item.expected_result,
            "result": result_value,
            "actual_value": ai_item.get("actual_value") or None,
            "remark": remark,
        })

    return results


async def parse_manual_submission(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    user_text: str,
    equipment_name: str = "",
) -> list[dict[str, Any]]:
    """使用 AI 解析巡检人员发送的非结构化手动提交文本。

    Args:
        db: 数据库会话
        task_id: 巡检任务 ID
        equipment_id: 当前设备 ID
        user_text: 巡检人员发送的自由文本
        equipment_name: 当前设备名称（帮助 AI 理解上下文）

    Returns:
        解析后的检查项结果列表，格式同 analyze_inspection_photo
    """
    task = await _get_task(db, task_id)
    if task.status != "执行中":
        raise AppException(message="任务未在执行中状态，不能提交检查结果")

    # 获取检查模板项
    items, _ = await get_inspection_items(db, task, equipment_id)
    if not items:
        raise AppException(message="该设备没有关联检查项，请先在系统中配置")

    items_list = [
        {
            "template_item_id": str(item.id),
            "item_name": item.item_name,
            "expected_result": item.expected_result or "",
        }
        for item in items
    ]

    client = QwenClient()
    try:
        user_prompt = build_manual_submit_user_prompt(
            items_list, user_text, equipment_name
        )
        raw_response = await client.parse_correction(
            system_prompt=MANUAL_SUBMIT_SYSTEM_PROMPT,
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

    # 解析 AI 响应
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        raise AIAnalysisError("AI 返回结果不是有效 JSON", raw_response) from None

    ai_items = parsed.get("items", [])
    if not isinstance(ai_items, list) or len(ai_items) == 0:
        raise AIAnalysisError("AI 未能解析出有效的检查结果", raw_response)

    # 映射回模板检查项
    item_map = {item["template_item_id"]: item for item in items_list}
    results: list[dict[str, Any]] = []
    for ai_item in ai_items:
        tid = ai_item.get("template_item_id", "")
        item_info = item_map.get(tid, {})
        result_value = ai_item.get("result", "正常")
        if result_value not in ("正常", "异常", "跳过"):
            result_value = "正常"

        results.append({
            "template_item_id": tid,
            "item_name": item_info.get("item_name", ai_item.get("item_name", "")),
            "expected_result": item_info.get("expected_result", ""),
            "result": result_value,
            "actual_value": ai_item.get("actual_value") or None,
            "remark": ai_item.get("remark") or None,
        })

    return results


# ═══════════ 内部辅助 ═══════════


async def get_inspection_items_for_session(
    db: AsyncSession, task_id: uuid.UUID, equipment_id: uuid.UUID
) -> list[dict[str, Any]]:
    """获取检查项列表（供飞书会话使用），返回轻量 dict 列表。"""
    task = await _get_task(db, task_id)
    items, _ = await get_inspection_items(db, task, equipment_id)
    return [
        {
            "template_item_id": str(item.id),
            "item_name": item.item_name,
            "expected_result": item.expected_result or "",
            "sort_order": item.sort_order,
        }
        for item in items
    ]
