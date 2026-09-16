"""equipment 模块 public_api 契约测试。

覆盖业务场景：
- 空 ID 列表返回空
- 不存在的设备 ID 被静默省略
- 存在的设备返回 EquipmentBrief（id + equipment_no + name）
"""

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment, Location
from app.modules.equipment.public_api import get_equipment_briefs
from tests.modules.production.conftest import rand_code


async def test_empty_ids_returns_empty(db_session: AsyncSession) -> None:
    """传入空 ID 列表时返回空数组。"""
    assert await get_equipment_briefs(db_session, []) == []


async def test_unknown_ids_are_omitted(db_session: AsyncSession) -> None:
    """不存在的设备 ID 不报错，结果中不出现。"""
    result = await get_equipment_briefs(db_session, [uuid.uuid4()])
    assert result == []


async def test_existing_equipment_returns_brief(db_session: AsyncSession) -> None:
    """已存在的设备返回正确的 EquipmentBrief。"""
    location = Location(name="测试车间", code=rand_code("LOC"))
    db_session.add(location)
    await db_session.flush()
    equipment = Equipment(
        equipment_no=rand_code("EQ"),
        name="测试反应釜",
        location_id=location.id,
    )
    db_session.add(equipment)
    await db_session.flush()

    briefs = await get_equipment_briefs(db_session, [equipment.id])
    assert len(briefs) == 1
    assert briefs[0].id == equipment.id
    assert briefs[0].equipment_no == equipment.equipment_no
    assert briefs[0].name == equipment.name


async def test_production_options_use_shared_reference_scope(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生产选择器调用 production 模块引用接口，并保留共享来源标记。"""
    equipment_id = uuid.uuid4()
    calls: list[tuple[object, ...]] = []

    async def list_refs(
        db: AsyncSession,
        user: object,
        target_module: str,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[object], int]:
        calls.append((user, target_module, keyword, page, page_size))
        return [
            SimpleNamespace(
                id=equipment_id,
                equipment_no="EQ-SHARED",
                name="共享设备",
                status="完好",
                is_active=True,
                source="shared",
            )
        ], 1

    monkeypatch.setattr(
        "app.modules.equipment.public_api.list_equipment_references",
        list_refs,
    )
    response = await client.get(
        "/api/v1/production/equipment-options",
        params={"keyword": "共享", "page": 2, "page_size": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["source"] == "shared"
    assert body["data"][0]["equipment_no"] == "EQ-SHARED"
    assert calls and calls[0][1:] == ("production", "共享", 2, 10)


async def test_production_briefs_do_not_use_unscoped_equipment_query(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """按 ID 回显必须调用带用户和目标模块的引用接口。"""
    equipment_id = uuid.uuid4()
    calls: list[tuple[object, ...]] = []

    async def get_refs(
        db: AsyncSession,
        user: object,
        target_module: str,
        ids: list[uuid.UUID],
    ) -> list[object]:
        calls.append((user, target_module, ids))
        return []

    monkeypatch.setattr(
        "app.modules.equipment.public_api.get_equipment_references_by_ids",
        get_refs,
    )
    response = await client.get(
        "/api/v1/production/equipment-briefs",
        params=[("ids", str(equipment_id))],
    )
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert calls and calls[0][1:] == ("production", [equipment_id])
