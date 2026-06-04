"""Inspection template service: business logic for templates."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models import InspectionRecord, InspectionTemplate
from app.modules.equipment.models.work_order import WorkOrder
from app.modules.equipment.schemas import (
    InspectionCompleteRequest,
    InspectionTemplateCreate,
    InspectionTemplateItemCreate,
    InspectionTemplateItemUpdate,
    InspectionTemplateUpdate,
)


async def create_inspection_template(
    db: AsyncSession,
    data: InspectionTemplateCreate,
) -> InspectionTemplate:
    """创建巡检模板"""
    template_data = data.model_dump(exclude={"items"})
    items_data = [item.model_dump() for item in data.items] if data.items else None
    return await repo.create_inspection_template(db, template_data, items_data)


async def get_inspection_template_by_id(
    db: AsyncSession,
    template_id: uuid.UUID,
) -> InspectionTemplate:
    """获取巡检模板"""
    template = await repo.get_inspection_template_by_id(db, template_id)
    if not template:
        raise NotFoundException("巡检模板", str(template_id))
    return template


async def get_inspection_templates(
    db: AsyncSession,
    equipment_category_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionTemplate], int]:
    """获取巡检模板列表"""
    return await repo.get_inspection_templates(
        db,
        equipment_category_id=equipment_category_id,
        is_active=is_active,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


async def update_inspection_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    data: InspectionTemplateUpdate,
) -> InspectionTemplate:
    """更新巡检模板"""
    await get_inspection_template_by_id(db, template_id)
    update_data = data.model_dump(exclude_unset=True)
    result = await repo.update_inspection_template(db, template_id, update_data)
    if not result:
        raise NotFoundException("巡检模板", str(template_id))
    return result


async def delete_inspection_template(
    db: AsyncSession,
    template_id: uuid.UUID,
) -> bool:
    """删除巡检模板"""
    await get_inspection_template_by_id(db, template_id)
    return await repo.delete_inspection_template(db, template_id)


async def add_template_item(
    db: AsyncSession,
    template_id: uuid.UUID,
    data: InspectionTemplateItemCreate,
) -> None:
    """向模板添加检查项"""
    await get_inspection_template_by_id(db, template_id)
    item_data = data.model_dump()
    item_data["template_id"] = template_id
    await repo.create_template_item(db, item_data)


async def update_template_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    data: InspectionTemplateItemUpdate,
) -> None:
    """更新检查项"""
    update_data = data.model_dump(exclude_unset=True)
    result = await repo.update_template_item(db, item_id, update_data)
    if not result:
        raise NotFoundException("检查项", str(item_id))


async def delete_template_item(
    db: AsyncSession,
    item_id: uuid.UUID,
) -> bool:
    """删除检查项"""
    return await repo.delete_template_item(db, item_id)


async def complete_inspection(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    data: InspectionCompleteRequest,
) -> WorkOrder:
    """提交巡检结果"""
    from app.modules.equipment.models.work_order import WorkOrder as WorkOrderModel

    # 获取工单
    result = await db.execute(
        select(WorkOrderModel).where(
            WorkOrderModel.id == work_order_id,
            WorkOrderModel.is_deleted == False,  # noqa: E712
        )
    )
    wo = result.scalar_one_or_none()
    if not wo:
        raise NotFoundException("工单", str(work_order_id))

    if wo.order_type != "巡检":
        raise AppException(message="只有巡检工单才能提交巡检结果")

    # 创建巡检记录
    has_abnormal = False
    for record_item in data.records:
        if record_item.result == "异常":
            has_abnormal = True

        inspection_record = InspectionRecord(
            work_order_id=work_order_id,
            template_item_id=record_item.template_item_id,
            result=record_item.result,
            actual_value=record_item.actual_value,
            remark=record_item.remark,
        )
        db.add(inspection_record)

    # 计算巡检结果
    wo.check_result = "异常" if has_abnormal else "正常"
    await db.flush()
    await db.refresh(wo)
    return wo
