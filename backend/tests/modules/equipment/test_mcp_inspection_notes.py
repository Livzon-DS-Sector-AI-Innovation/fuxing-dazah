"""MCP 巡检现场说明测试 — add_inspection_note 与进度回显。

补记说明的价值在于"提交检查前就能记下、之后能回查"。进度工具必须
在待检设备下也显示说明，否则机器人无法向工人确认「你说的我记了」。
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.mcp_tools import inspection as mcp_inspection
from app.modules.equipment.models.equipment import Equipment
from app.modules.equipment.models.inspection import InspectionTask
from app.modules.equipment.repository.inspection import (
    get_notes_by_task_and_equipment,
)
from app.platform.identity.models import User
from tests.modules.equipment.test_inspection import (
    department as _department,
)
from tests.modules.equipment.test_inspection import (
    equipment_with_dept as _equipment_with_dept,
)
from tests.modules.equipment.test_inspection import (
    inspection_task as _inspection_task,
)
from tests.modules.equipment.test_inspection import inspector as _inspector
from tests.modules.equipment.test_inspection import leader as _leader
from tests.modules.equipment.test_inspection import location as _location
from tests.modules.equipment.test_inspection import (
    template_with_items as _template_with_items,
)

# pytest 按 fixture 定义名发现；别名 import 后再绑回原名，避免同名重定义报错。
department = _department
equipment_with_dept = _equipment_with_dept
inspection_task = _inspection_task
inspector = _inspector
leader = _leader
location = _location
template_with_items = _template_with_items


@pytest.fixture
async def mcp_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    """把工具内部的 get_db() 指到测试 session，commit 降级为 flush。"""
    monkeypatch.setattr(mcp_inspection, "get_db", lambda: db_session)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    return db_session


def _text(result: object) -> str:
    return "".join(getattr(b, "text", "") for b in result.content)  # type: ignore[attr-defined]


async def test_pending_device_note_visible_in_progress(
    mcp_db: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    inspector: User,
) -> None:
    """待检设备的现场说明也要出现在进度输出里。"""
    note_text = "地面有油渍，疑似法兰渗漏"
    result = await mcp_inspection.add_inspection_note(
        task_no=inspection_task.task_no,
        equipment=str(equipment_with_dept.id),
        content=note_text,
        operator_id=str(inspector.id),
    )
    assert not result.is_error

    progress = await mcp_inspection.get_inspection_task_progress(
        task_no=inspection_task.task_no,
        operator_id=str(inspector.id),
    )
    text = _text(progress)
    assert "待检设备：" in text
    assert note_text in text
    assert progress.structured_content is not None
    assert progress.structured_content["pending_count"] == 1


async def test_add_note_rejects_blank_content(
    mcp_db: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    inspector: User,
) -> None:
    """空白说明不落库，工具返回错误。"""
    result = await mcp_inspection.add_inspection_note(
        task_no=inspection_task.task_no,
        equipment=str(equipment_with_dept.id),
        content="   ",
        operator_id=str(inspector.id),
    )
    assert result.is_error


async def test_add_note_retry_is_idempotent(
    mcp_db: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    inspector: User,
) -> None:
    """工具超时后原样重试同一条说明，不应重复落库。"""
    kwargs = {
        "task_no": inspection_task.task_no,
        "equipment": str(equipment_with_dept.id),
        "content": "地面有油渍，疑似法兰渗漏",
        "operator_id": str(inspector.id),
    }
    first = await mcp_inspection.add_inspection_note(**kwargs)
    second = await mcp_inspection.add_inspection_note(**kwargs)
    assert not first.is_error
    assert not second.is_error
    assert first.structured_content is not None
    assert second.structured_content is not None
    assert second.structured_content["note_id"] == first.structured_content["note_id"]

    notes = await get_notes_by_task_and_equipment(
        mcp_db, inspection_task.id, equipment_with_dept.id
    )
    assert len(notes) == 1
