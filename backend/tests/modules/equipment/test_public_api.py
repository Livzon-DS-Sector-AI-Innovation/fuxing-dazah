"""equipment public_api 跨模块契约测试。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment, Location
from app.modules.equipment.public_api import list_equipments_for_user
from app.platform.identity.models import User


def _uid() -> str:
    return uuid.uuid4().hex[:8].upper()


async def test_list_equipments_for_user(db_session: AsyncSession) -> None:
    """带用户 ctx 查询设备列表：能按关键字查到刚建的设备，返回摘要和总数。"""
    user = User(name="跨模块调用者", employee_no=f"EMP-{_uid()}")
    db_session.add(user)
    location = Location(name="测试车间", code=f"LOC-{_uid()}")
    db_session.add(location)
    await db_session.flush()
    equipment = Equipment(
        equipment_no=f"EQ-PUB-{_uid()}",
        name="公共接口测试设备",
        location_id=location.id,
    )
    db_session.add(equipment)
    await db_session.flush()

    briefs, total = await list_equipments_for_user(
        db_session, user, keyword=equipment.equipment_no
    )
    assert total == 1
    assert briefs[0].id == equipment.id
    assert briefs[0].equipment_no == equipment.equipment_no
    assert briefs[0].name == equipment.name
