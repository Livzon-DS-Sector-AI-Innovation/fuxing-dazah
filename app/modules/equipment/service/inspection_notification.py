"""巡检通知服务 — 构建并发送飞书巡检通知。

当巡检任务开始时，向指派的巡检人员（DM）和设备部群聊发送通知卡片，
包含任务编号、日期、设备/路线、检查项目等信息。
"""

import logging
import uuid
from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.equipment import repository as repo
from app.modules.equipment.models.inspection import InspectionTask
from app.platform.integrations.feishu.message import send_group_card
from app.platform.integrations.feishu.notification import send_user_card

if TYPE_CHECKING:
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.work_order import WorkOrder

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
    if task.route and task.route.locations_rel:
        eq_ids: list[uuid.UUID] = []
        for loc in task.route.locations_rel:
            for eq in (loc.equipments or []):
                eq_ids.append(eq.equipment_id)
        if eq_ids:
            name_map = await repo.get_equipment_names_by_ids(db, eq_ids)
            for eid in eq_ids:
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
    # 线路巡检：从 route → locations → equipment → templates 链获取
    # 设备巡检：从 task.template_ids JSON 列表获取
    template_id_set: set[uuid.UUID] = set()

    if task.route_id:
        from sqlalchemy import select as sa_select

        from app.modules.equipment.models.inspection_route_location import (
            RouteEquipmentTemplate,
            RouteLocation,
            RouteLocationEquipment,
        )

        loc_stmt = sa_select(RouteLocation).where(
            RouteLocation.route_id == task.route_id,
            RouteLocation.is_deleted == False,  # noqa: E712
        )
        locs = (await db.execute(loc_stmt)).scalars().all()
        for loc in locs:
            eq_stmt = sa_select(RouteLocationEquipment).where(
                RouteLocationEquipment.route_location_id == loc.id,
                RouteLocationEquipment.is_deleted == False,  # noqa: E712
            )
            eqs = (await db.execute(eq_stmt)).scalars().all()
            for eq in eqs:
                tpl_stmt = sa_select(RouteEquipmentTemplate).where(
                    RouteEquipmentTemplate.route_equipment_id == eq.id,
                    RouteEquipmentTemplate.is_deleted == False,  # noqa: E712
                )
                tpls = (await db.execute(tpl_stmt)).scalars().all()
                for tpl in tpls:
                    template_id_set.add(tpl.template_id)
    elif task.equipment_templates:
        # 新方式：从设备-模板映射聚合所有唯一模板
        for tpl_ids in task.equipment_templates.values():
            for t in tpl_ids:
                tid = uuid.UUID(t) if isinstance(t, str) else t
                template_id_set.add(tid)
    elif task.template_ids:
        # 兼容旧数据
        for t in task.template_ids:
            tid = uuid.UUID(t) if isinstance(t, str) else t
            template_id_set.add(tid)

    all_items: list[dict] = []
    seen: set[str] = set()
    for tid in template_id_set:
        template = await repo.get_inspection_template_by_id(db, tid)
        if template and template.items:
            for item in template.items:
                if item.item_name not in seen:
                    seen.add(item.item_name)
                    all_items.append({
                        "item_name": item.item_name,
                        "expected_result": item.expected_result,
                        "sort_order": item.sort_order,
                    })
    return all_items


def _build_card_content(
    task: InspectionTask,
    equipment_names: list[str],
    items: list[dict],
    locations_info: list[dict] | None = None,
) -> str:
    """构建飞书卡片 markdown 正文。

    Args:
        locations_info: 线路巡检的地点信息列表，每项:
            {location_name, sort_order, equipment: [{name, equipment_no}]}
    """
    plan_type = task.plan_type or "设备巡检"
    lines = [
        f"**任务编号：**{task.task_no}",
        f"**巡检时间：**{_format_date(task.planned_time)}",
        f"**巡检类型：**{plan_type}",
    ]

    # 设备/路线信息
    if plan_type == "线路巡检" and task.route:
        lines.append(f"**巡检路线：**{task.route.name}")

        # 按地点展示路线层级
        if locations_info:
            total_equipment = sum(len(loc.get("equipment", [])) for loc in locations_info)
            lines.append("")
            lines.append("---")
            lines.append(f"**📍 巡检路线（共 {len(locations_info)} 个地点 · {total_equipment} 台设备）**")
            lines.append("")
            for i, loc in enumerate(locations_info):
                eq_list = loc.get("equipment", [])
                eq_names = "、".join(e["name"] for e in eq_list[:3])
                if len(eq_list) > 3:
                    eq_names += f" 等 {len(eq_list)} 台"
                lines.append(f"**第 {i + 1} 站：{loc['location_name']}**")
                lines.append(f"  ↳ {eq_names}")
                lines.append("")
        elif equipment_names:
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
    lines.append("**📋 所有检查项目：**")
    lines.append("")

    if items:
        for item in items[:20]:
            expected = (
                f"（标准：{item['expected_result']}）"
                if item.get("expected_result")
                else ""
            )
            lines.append(f"• {item['item_name']}{expected}")
        if len(items) > 20:
            lines.append(f"> 还有 {len(items) - 20} 项，请在系统中查看")
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
        "status=%s, assignee=%s (feishu_user_id=%s), chat_id=%s",
        task.task_no,
        task.status,
        task.assignee.name if task.assignee else "N/A",
        task.assignee.feishu_user_id if task.assignee else "N/A",
        settings.FEISHU_EQUIPMENT_CHAT_ID or "(not set)",
    )

    try:
        # 收集数据
        equipment_names = await _collect_equipment_names(db, task)
        logger.info("  Collected %d equipment names", len(equipment_names))
        items = await _get_template_items(db, task)
        logger.info("  Collected %d template items", len(items))

        # 线路巡检：收集地点层级信息
        locations_info: list[dict] | None = None
        if task.plan_type == "线路巡检" and task.route and task.route.locations_rel:
            locations_info = []
            for loc in sorted(task.route.locations_rel, key=lambda x: x.sort_order):
                eq_list: list[dict] = []
                for eq in sorted((loc.equipments or []), key=lambda x: x.sort_order):
                    if eq.equipment and not eq.equipment.is_deleted:
                        eq_list.append({
                            "name": eq.equipment.name,
                            "equipment_no": eq.equipment.equipment_no or "",
                        })
                locations_info.append({
                    "location_name": loc.location.name if loc.location else "未知地点",
                    "sort_order": loc.sort_order,
                    "equipment": eq_list,
                })

        title = f"【设备】🔍 巡检任务 — {task.task_no}"
        content = _build_card_content(task, equipment_names, items, locations_info)

        # 1) DM 通知巡检人员
        if task.assignee and task.assignee.feishu_user_id:
            logger.info(
                "  Sending DM to feishu_user_id=%s (name=%s)...",
                task.assignee.feishu_user_id,
                task.assignee.name,
            )
            dm_ok = await send_user_card(
                open_id=task.assignee.feishu_user_id,
                title=title,
                content=content,
                receive_id_type="user_id",
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
                "assignee=%s, feishu_user_id=%s",
                task.task_no,
                task.assignee.name if task.assignee else "None",
                task.assignee.feishu_user_id if task.assignee else "N/A",
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


async def send_work_order_notification(
    work_order: "WorkOrder",
    equipment: "Equipment",
    task: InspectionTask | None = None,
    responsible_user_id: str | None = None,
) -> None:
    """向工单负责人发送飞书工单通知（巡检异常 / 计划维护通用）。

    非关键路径：发送失败只记日志，不影响主流程。

    Args:
        work_order: 新创建的工单
        equipment: 关联设备
        task: 来源巡检任务（计划维护工单时为 None）
        responsible_user_id: 负责人的 feishu_user_id（可为 None）
    """
    if not responsible_user_id:
        logger.info(
            "Skipping work order notification: no responsible person user_id "
            "(work_order_no=%s)",
            work_order.work_order_no,
        )
        return

    try:
        if task is not None:
            title = f"【设备】⚠️ 巡检异常工单 — {work_order.work_order_no}"
            lines = [
                f"**工单编号：**{work_order.work_order_no}",
                f"**设备名称：**{equipment.name}",
                f"**设备编号：**{equipment.equipment_no}",
                f"**优先级：**{work_order.priority}",
                f"**异常描述：**{work_order.fault_description or '-'}",
                f"**来源巡检：**{task.task_no}",
                "",
                "请及时处理该工单。",
            ]
        else:
            title = f"【设备】🔧 计划维护工单 — {work_order.work_order_no}"
            lines = [
                f"**工单编号：**{work_order.work_order_no}",
                f"**设备名称：**{equipment.name}",
                f"**设备编号：**{equipment.equipment_no}",
                f"**工单类型：**{work_order.order_type}",
                f"**优先级：**{work_order.priority}",
                f"**计划维护日期：**{work_order.planned_start_date or '-'}",
                "",
                "请及时处理该工单。",
            ]
        content = "\n".join(lines)

        ok = await send_user_card(
            open_id=responsible_user_id,
            title=title,
            content=content,
            receive_id_type="user_id",
        )
        if ok:
            logger.info(
                "✅ Work order notification sent to %s for %s",
                responsible_user_id,
                work_order.work_order_no,
            )
        else:
            logger.error(
                "❌ Failed to send work order notification for %s",
                work_order.work_order_no,
            )
    except Exception as e:
        logger.error(
            "❌ send_work_order_notification FAILED for %s: %s: %s",
            work_order.work_order_no,
            type(e).__name__,
            e,
        )

