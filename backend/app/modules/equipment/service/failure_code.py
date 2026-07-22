"""Failure code service layer: business logic for failure symptom / cause / action."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models import FailureAction, FailureCause, FailureSymptom
from app.modules.equipment.schemas import FailureCodeCreate, FailureCodeUpdate

FailureCodeModel = FailureSymptom | FailureCause | FailureAction


async def create_failure_code(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    data: FailureCodeCreate,
) -> FailureCodeModel:
    """创建故障代码"""
    if await repo.exists_failure_code_by_code(db, model_class, data.code):
        raise DuplicateException("故障代码", data.code)
    return await repo.create_failure_code(db, model_class, data.model_dump())


async def get_failure_code_by_id(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    code_id: uuid.UUID,
) -> FailureCodeModel:
    """获取故障代码"""
    result = await repo.get_failure_code_by_id(db, model_class, code_id)
    if not result:
        raise NotFoundException("故障代码", str(code_id))
    return result


async def get_failure_codes(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
) -> list[FailureCodeModel]:
    """获取故障代码列表"""
    return await repo.get_failure_codes(db, model_class)


async def update_failure_code(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    code_id: uuid.UUID,
    data: FailureCodeUpdate,
) -> FailureCodeModel:
    """更新故障代码"""
    await get_failure_code_by_id(db, model_class, code_id)
    if data.code is not None and await repo.exists_failure_code_by_code(
        db, model_class, data.code, exclude_id=code_id
    ):
        raise DuplicateException("故障代码", data.code)
    result = await repo.update_failure_code(
        db, model_class, code_id, data.model_dump(exclude_unset=True)
    )
    if not result:
        raise NotFoundException("故障代码", str(code_id))
    return result


async def delete_failure_code(
    db: AsyncSession,
    model_class: type[FailureCodeModel],
    code_id: uuid.UUID,
) -> bool:
    """删除故障代码"""
    await get_failure_code_by_id(db, model_class, code_id)
    return await repo.delete_failure_code(db, model_class, code_id)
