"""巡检通知服务 — 构建并发送飞书巡检通知。

当巡检任务开始时，向指派的巡检人员（DM）和设备部群聊发送通知卡片，
包含任务编号、日期、设备/路线、检查项目等信息。
"""

import logging
import uuid
from datetime import date as date_type
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.equipment import repository as repo
from app.modules.equipment.models.inspection import InspectionTask
from app.platform.integrations.feishu.message import send_group_card
from app.platform.integrations.feishu.notification import send_user_card

logger = logging.getLogger(__name__)
settings = get_settings()


def _format_date(d: date_type | datetime | None) -> str:
    """将 date/datetime 格式化为中文日期字符串"""
    return d.strftime("%Y年%m月%d日") if d else "-"


async def _collect_equipment_names(
    db: AsyncSession, task: InspectionTask
) -> list[str]:
    """收集任务关联的所有设备名称"""
    names: list[str] = []

    # 线路巡检：从路线关联获取设备名
    if task.route and task.route.equipments_rel:
        ids = [re_.equipment_id for re_ in task.route.equipments_rel]
        if ids:
            name_map = await repo.get_equipment_names_by_ids(db, ids)
            for eid in ids:
                if eid in name_map:
                    names.append(name_map[eid])
    # 多设备模式
    elif task.equipment_ids:
        id_list = [
            uid if isinstance(uid, uuid.UUID) else uuid.UUID(uid)
            for uid in (task.equipment_ids or [])
        ]
        if id_list:
            name_map = await repo.get_equipment_names_by_ids(db, id_list)
            for eid in id_list:
                if eid in name_map:
                    names.append(name_map[eid])
    # 单设备模式
    elif task.equipment:
        names.append(task.equipment.name)

    return names


async def _get_template_items(
    db: AsyncSession, task: InspectionTask
) -> list[dict]:
    """获取模板检查项列表。

    优先使用已加载的 template.items 关系；若未加载则查询数据库。
    """
    # 尝试从已加载的关系获取
    if task.template:
        try:
            items = task.template.items
            if items is not None:
                return [
                    {
                        "item_name": item.item_name,
                        "expected_result": item.expected_result,
                        "sort_order": item.sort_order,
                    }
                    for item in items
                ]
        except Exception:
            pass

        # 关系未加载，从数据库查询模板（含 items）
        template = await repo.get_inspection_template_by_id(
            db, task.template_id
        )
        if template and template.items:
            return [
                {
                    "item_name": item.item_name,
                    "expected_result": item.expected_result,
                    "sort_order": item.sort_order,
                }
                for item in template.items
            ]

    return []


def _build_card_content(
    task: InspectionTask,
    equipment_names: list[str],
    items: list[dict],
) -> str:
    """构建飞书卡片 markdown 正文"""
    plan_type = task.plan_type or "设备巡检"
    lines = [
        f"**任务编号：**{task.task_no}",
        f"**巡检日期：**{_format_date(task.planned_date)}",
        f"**巡检类型：**{plan_type}",
    ]

    # 设备/路线信息
    if plan_type == "线路巡检" and task.route:
        lines.append(f"**巡检路线：**{task.route.name}")
        if equipment_names:
            lines.append(
                f"**涉及设备：**{'、'.join(equipment_names[:5])}"
                f"{f' 等{len(equipment_names)}台' if len(equipment_names) > 5 else ''}"
            )
    else:
        if equipment_names:
            lines.append(
                f"**巡检设备：**{'、'.join(equipment_names[:5])}"
                f"{f' 等{len(equipment_names)}台' if len(equipment_names) > 5 else ''}"
            )

    # 巡检人员
    if task.assignee:
        lines.append(f"**巡检人员：**{task.assignee.name}")

    # 检查项目
    lines.append("")
    lines.append("---")
    lines.append("**📋 检查项目：**")
    lines.append("")

    if items and equipment_names:
        for eq_name in equipment_names[:10]:  # 最多展示10台设备
            lines.append(f"**{eq_name}**")
            for item in items[:20]:  # 每台设备最多20项
                expected = (
                    f"（预期：{item['expected_result']}）"
                    if item.get("expected_result")
                    else ""
                )
                lines.append(f"• {item['item_name']}{expected}")
            lines.append("")
        if len(equipment_names) > 10:
            lines.append(f"> 还有 {len(equipment_names) - 10} 台设备，请在系统中查看")
    elif items:
        # 无设备名但有检查项（兜底）
        for item in items[:30]:
            expected = (
                f"（预期：{item['expected_result']}）"
                if item.get("expected_result")
                else ""
            )
            lines.append(f"• {item['item_name']}{expected}")
    else:
        lines.append("请在系统中查看检查项目详情")

    return "\n".join(lines)


async def send_inspection_start_notification(
    task: InspectionTask,
    db: AsyncSession,
) -> None:
    """发送巡检开始通知（DM + 群聊）。

    应在任务状态已更新为"执行中"后调用。通知发送失败不会影响主流程。

    Args:
        task: InspectionTask（需已加载 route/equipment/template/assignee 关系）
        db: 数据库会话
    """
    logger.info(
        "▶ send_inspection_start_notification called: task_no=%s, "
        "status=%s, assignee=%s (feishu_open_id=%s), chat_id=%s",
        task.task_no,
        task.status,
        task.assignee.name if task.assignee else "N/A",
        task.assignee.feishu_open_id if task.assignee else "N/A",
        settings.FEISHU_EQUIPMENT_CHAT_ID or "(not set)",
    )

    try:
        # 收集数据
        equipment_names = await _collect_equipment_names(db, task)
        logger.info("  Collected %d equipment names", len(equipment_names))
        items = await _get_template_items(db, task)
        logger.info("  Collected %d template items", len(items))

        title = f"🔍 巡检任务已开始 - {task.task_no}"
        content = _build_card_content(task, equipment_names, items)

        # 1) DM 通知巡检人员
        if task.assignee and task.assignee.feishu_open_id:
            logger.info(
                "  Sending DM to feishu_open_id=%s (name=%s)...",
                task.assignee.feishu_open_id,
                task.assignee.name,
            )
            dm_ok = await send_user_card(
                open_id=task.assignee.feishu_open_id,
                title=title,
                content=content,
            )
            if dm_ok:
                logger.info(
                    "  ✅ Inspection start DM sent to %s for task %s",
                    task.assignee.name, task.task_no,
                )
            else:
                logger.error(
                    "  ❌ Failed to send DM to %s for task %s",
                    task.assignee.name, task.task_no,
                )
        else:
            logger.warning(
                "  ⚠ Cannot send DM for task %s: "
                "assignee=%s, feishu_open_id=%s",
                task.task_no,
                task.assignee.name if task.assignee else "None",
                task.assignee.feishu_open_id if task.assignee else "N/A",
            )

        # 2) 群聊通知
        chat_id = settings.FEISHU_EQUIPMENT_CHAT_ID
        if chat_id:
            logger.info("  Sending group notification to chat_id=%s...", chat_id)
            group_ok = await send_group_card(chat_id, title, content)
            if group_ok:
                logger.info(
                    "  ✅ Inspection start group notification sent for task %s",
                    task.task_no,
                )
            else:
                logger.error(
                    "  ❌ Failed to send group notification for task %s",
                    task.task_no,
                )
        else:
            logger.info(
                "  ℹ FEISHU_EQUIPMENT_CHAT_ID not configured, "
                "skipping group notification for task %s",
                task.task_no,
            )

    except Exception as e:
        logger.error(
            "❌ send_inspection_start_notification FAILED for task %s: %s: %s",
            task.task_no, type(e).__name__, e,
        )
