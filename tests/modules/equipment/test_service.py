"""Tests for equipment service layer."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.equipment.schemas import (
    EquipmentCategoryCreate,
    EquipmentCategoryUpdate,
)
from app.modules.equipment.service import (
    create_equipment_category,
    delete_equipment_category,
    generate_equipment_no,
    get_equipment_category_by_id,
    update_equipment_category,
)


@pytest.fixture
def sample_category_data() -> EquipmentCategoryCreate:
    return EquipmentCategoryCreate(
        name="反应釜",
        code="RF",
        description="反应设备",
    )


async def test_create_equipment_category_success(
    db_session: AsyncSession, sample_category_data: EquipmentCategoryCreate
) -> None:
    """测试成功创建设备分类"""
    category = await create_equipment_category(db_session, sample_category_data)
    assert category.name == "反应釜"
    assert category.code == "RF"


async def test_create_equipment_category_duplicate_code(
    db_session: AsyncSession, sample_category_data: EquipmentCategoryCreate
) -> None:
    """测试创建重复编码的设备分类"""
    await create_equipment_category(db_session, sample_category_data)
    with pytest.raises(DuplicateException):
        await create_equipment_category(db_session, sample_category_data)


async def test_get_equipment_category_not_found(db_session: AsyncSession) -> None:
    """测试获取不存在的设备分类"""
    with pytest.raises(NotFoundException):
        await get_equipment_category_by_id(db_session, uuid.uuid4())


async def test_update_equipment_category_success(
    db_session: AsyncSession, sample_category_data: EquipmentCategoryCreate
) -> None:
    """测试成功更新设备分类"""
    category = await create_equipment_category(db_session, sample_category_data)
    updated = await update_equipment_category(
        db_session,
        category.id,
        EquipmentCategoryUpdate(name="大型反应釜"),
    )
    assert updated.name == "大型反应釜"


async def test_delete_equipment_category_success(
    db_session: AsyncSession, sample_category_data: EquipmentCategoryCreate
) -> None:
    """测试成功删除设备分类"""
    category = await create_equipment_category(db_session, sample_category_data)
    result = await delete_equipment_category(db_session, category.id)
    assert result is True


async def test_generate_equipment_no(
    db_session: AsyncSession, sample_category_data: EquipmentCategoryCreate
) -> None:
    """测试生成设备编号"""
    category = await create_equipment_category(db_session, sample_category_data)
    equipment_no = await generate_equipment_no(db_session, category.code)
    assert equipment_no == "EQ-RF-0001"
