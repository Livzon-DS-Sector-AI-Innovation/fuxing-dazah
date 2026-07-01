"""设备模块数据范围过滤与写操作归属校验。

三种过滤模式：
- department_id: 直接匹配 department_id 字段（设备台账）
- user_id: 匹配 created_by / reporter_id 等用户 ID 字段（工单、巡检、计划、备件）
- personnel_dept: 匹配人员表的 department 字符串路径（人员管理）
"""

from sqlalchemy import Select, false

from app.core.exceptions import ForbiddenException
from app.modules.equipment.deps import EquipmentAccessContext


def apply_equipment_scope(
    query: Select,
    ctx: EquipmentAccessContext,
    model_field,  # noqa: ANN001 - SQLAlchemy InstrumentedAttribute
    mode: str = "department_id",
) -> Select:
    """根据数据范围给查询添加 WHERE 条件。

    Args:
        query: SQLAlchemy Select 查询对象
        ctx: 设备模块访问上下文
        model_field: ORM 模型字段（如 Equipment.department_id）
        mode: 过滤模式 — "department_id" | "user_id" | "personnel_dept"

    Returns:
        添加了 WHERE 条件的 Select 查询对象
    """
    if ctx.is_unrestricted:
        return query

    if mode == "department_id":
        # 设备台账：按 department_id 过滤
        if ctx.visible_department_ids:
            return query.where(model_field.in_(ctx.visible_department_ids))
        return query.where(false())

    if mode == "user_id":
        # 工单/巡检/计划/备件：按 created_by / reporter_id 等 user_id 字段过滤
        if ctx.department_user_ids:
            return query.where(model_field.in_(ctx.department_user_ids))
        return query.where(model_field == ctx.user.id)

    if mode == "personnel_dept":
        # 人员管理：按 department 字符串路径过滤
        user_dept = ctx.user.department
        if not user_dept:
            return query.where(false())

        if ctx.data_scope == "self_only":
            return query.where(model_field == user_dept)
        if ctx.data_scope == "department":
            return query.where(model_field == user_dept)
        if ctx.data_scope == "department_and_children":
            return query.where(
                (model_field == user_dept) | model_field.like(f"{user_dept}/%")
            )

    return query


async def verify_write_ownership(
    ctx: EquipmentAccessContext,
    resource,  # noqa: ANN001 - ORM object
    field: str = "department_id",
    mode: str = "department_id",
) -> None:
    """写操作前校验当前用户是否有权修改该资源。

    - data_scope == "all" 时跳过检查（超管可操作任何资源）
    - 创建操作不调用此函数（新资源自动归属当前用户部门）

    Args:
        ctx: 设备模块访问上下文
        resource: ORM 对象
        field: 归属字段名（如 "department_id", "reporter_id", "created_by"）
        mode: 校验模式 — "department_id" | "user_id"

    Raises:
        ForbiddenException: 当用户无权操作该资源时
    """
    if ctx.is_unrestricted:
        return

    resource_value = getattr(resource, field, None)
    if resource_value is None:
        return  # 资源没有归属字段，放行

    if mode == "department_id":
        # 设备台账：检查 department_id 是否在可见部门列表中
        if (
            ctx.visible_department_ids
            and resource_value not in ctx.visible_department_ids
        ):
            raise ForbiddenException("无权操作其他部门的资源")
        if not ctx.visible_department_ids:
            raise ForbiddenException("无权操作其他部门的资源")

    elif mode == "user_id":
        # 工单/巡检/计划/备件：检查 user_id 是否在本部门用户列表中
        if ctx.department_user_ids and resource_value not in ctx.department_user_ids:
            raise ForbiddenException("无权操作其他部门的资源")
        if not ctx.department_user_ids and resource_value != ctx.user.id:
            raise ForbiddenException("无权操作其他部门的资源")
