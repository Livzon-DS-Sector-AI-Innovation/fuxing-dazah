"""equipment public_api 契约测试。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment, Location
from app.modules.equipment.public_api import get_equipment_briefs
from tests.modules.production.conftest import rand_code


async def test_empty_ids_returns_empty(db_session: AsyncSession) -> None:
    assert await get_equipment_briefs(db_session, []) == []


async def test_unknown_ids_are_omitted(db_session: AsyncSession) -> None:
    result = await get_equipment_briefs(db_session, [uuid.uuid4()])
    assert result == []


async def test_existing_equipment_returns_brief(db_session: AsyncSession) -> None:
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
