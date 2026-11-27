"""MCP 巡检提交：all_done 判定与异常工单检查项名称。"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.mcp_tools import inspection as mcp_inspection
from app.modules.equipment.models.equipment import Equipment
from app.modules.equipment.models.inspection import InspectionTask
from app.modules.equipment.models.inspection_template import InspectionTemplate
from app.modules.equipment.repository.work_order import (
    get_pending_work_orders_by_inspection_task,
)
from app.platform.identity.models import User
from tests.modules.equipment.test_inspection import (
    _get_template_items,
)
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


async def test_submit_inspection_reports_all_done_for_last_device(
    mcp_db: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    inspector: User,
) -> None:
    """单设备任务提交后应返回 all_done=true，不能再提示还有待检设备。"""
    items = await _get_template_items(mcp_db, template_with_items.id)
    result = await mcp_inspection.submit_inspection(
        task_no=inspection_task.task_no,
        equipment=equipment_with_dept.equipment_no,
        operator_id=str(inspector.id),
        check_items=[
            {
                "item_name": items[0].item_name,
                "template_item_id": str(items[0].id),
                "result": "正常",
            },
            {
                "item_name": items[1].item_name,
                "template_item_id": str(items[1].id),
                "result": "正常",
            },
        ],
    )
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["all_done"] is True
    assert "还有待检设备" not in _text(result)


async def test_submit_inspection_anomaly_uses_item_name(
    mcp_db: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    inspector: User,
) -> None:
    """MCP 提交的异常工单描述应含检查项名称，而不是「未知检查项」。"""
    items = await _get_template_items(mcp_db, template_with_items.id)
    result = await mcp_inspection.submit_inspection(
        task_no=inspection_task.task_no,
        equipment=equipment_with_dept.equipment_no,
        operator_id=str(inspector.id),
        check_items=[
            {
                "item_name": items[0].item_name,
                "template_item_id": str(items[0].id),
                "result": "异常",
                "remark": "温度超标",
            },
            {
                "item_name": items[1].item_name,
                "template_item_id": str(items[1].id),
                "result": "正常",
            },
        ],
    )
    assert not result.is_error

    pending = await get_pending_work_orders_by_inspection_task(
        mcp_db, inspection_task.id
    )
    assert len(pending) == 1
    description = pending[0].fault_description or ""
    assert "温度检查" in description
    assert "未知检查项" not in description
