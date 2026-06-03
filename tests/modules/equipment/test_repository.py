"""Tests for equipment repository layer."""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.repository import (
    create_equipment_category,
    get_equipment_categories,
    get_equipment_category_by_id,
)


@pytest.fixture
def sample_category_data() -> dict[str, Any]:
    return {
        "name": "反应釜",
        "code": "RF",
        "description": "反应设备",
    }


async def test_create_equipment_category(
    db_session: AsyncSession, sample_category_data: dict[str, Any]
) -> None:
    """测试创建设备分类"""
    category = await create_equipment_category(db_session, sample_category_data)
    assert category.name == "反应釜"
    assert category.code == "RF"
    assert category.id is not None


async def test_get_equipment_category_by_id(
    db_session: AsyncSession, sample_category_data: dict[str, Any]
) -> None:
    """测试根据ID获取设备分类"""
    category = await create_equipment_category(db_session, sample_category_data)
    result = await get_equipment_category_by_id(db_session, category.id)
    assert result is not None
    assert result.name == "反应釜"


async def test_get_equipment_categories(db_session: AsyncSession) -> None:
    """测试获取设备分类列表"""
    # 创建多个分类
    await create_equipment_category(db_session, {"name": "反应釜", "code": "RF"})
    await create_equipment_category(db_session, {"name": "离心机", "code": "LXJ"})

    categories = await get_equipment_categories(db_session)
    assert len(categories) >= 2
