"""Failure code repository: generic CRUD for failure symptom / cause / action."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import FailureAction, FailureCause, FailureSymptom

FailureCodeModel = FailureSymptom | FailureCause | FailureAction


async def create_failure_code(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    data: dict[str, Any],
) -> FailureCodeModel:
    """创建故障代码"""
    instance = model_class(**data)
    db.add(instance)
    await db.flush()
    return instance


async def get_failure_code_by_id(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    code_id: uuid.UUID,
) -> FailureCodeModel | None:
    """根据ID获取故障代码"""
    result = await db.execute(
        select(model_class).where(
            model_class.id == code_id,
            model_class.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()  # type: ignore[return-value]


async def get_failure_codes(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
) -> list[FailureCodeModel]:
    """获取故障代码列表"""
    result = await db.execute(
        select(model_class)
        .where(model_class.is_deleted == False)  # noqa: E712
        .order_by(model_class.sort_order, model_class.code)
    )
    return list(result.scalars().all())  # type: ignore[arg-type]


async def exists_failure_code_by_code(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    code: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """检查故障代码是否已存在"""
    query = select(model_class.id).where(
        model_class.code == code,
        model_class.is_deleted == False,  # noqa: E712
    )
    if exclude_id:
        query = query.where(model_class.id != exclude_id)
    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def update_failure_code(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    code_id: uuid.UUID,
    data: dict[str, Any],
) -> FailureCodeModel | None:
    """更新故障代码"""
    instance = await get_failure_code_by_id(db, model_class, code_id)
    if not instance:
        return None
    for key, value in data.items():
        setattr(instance, key, value)
    await db.flush()
    await db.refresh(instance)
    return instance


async def delete_failure_code(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    code_id: uuid.UUID,
) -> bool:
    """删除故障代码（软删除）"""
    instance = await get_failure_code_by_id(db, model_class, code_id)
    if not instance:
        return False
    instance.is_deleted = True
    await db.flush()
    return True
