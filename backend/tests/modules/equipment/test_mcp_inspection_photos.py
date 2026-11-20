"""MCP 工具 submit_inspection_photos 批量上传的事务语义测试。

背景 bug（已修）：阶段 3 循环里单张失败时 db.rollback() 会把同批前面已保存
（未提交）的照片一并回滚，success_count 却已计入，工具返回"成功上传 N 张"
与实际落库数不符。修复后用行级 SAVEPOINT（begin_nested），单张失败只回滚
本张。三个场景：全部成功 / 部分失败 / 全部失败。
"""

import base64
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.mcp_tools import inspection as mcp_inspection
from app.modules.equipment.models.equipment import Equipment
from app.modules.equipment.models.inspection import InspectionPhoto, InspectionTask
from app.modules.equipment.service import inspection as svc
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
from tests.modules.equipment.test_inspection import (
    inspector as _inspector,
)
from tests.modules.equipment.test_inspection import (
    leader as _leader,
)
from tests.modules.equipment.test_inspection import (
    location as _location,
)
from tests.modules.equipment.test_inspection import (
    template_with_items as _template_with_items,
)

# 复用 test_inspection.py 的 fixture 链（任务/设备/用户/模板）。别名 import
# 后重绑回原名：pytest 按 fixture 定义名照常发现，同时避免参数名与 import
# 同名被 ruff 判 F811 重定义。
department = _department
equipment_with_dept = _equipment_with_dept
inspection_task = _inspection_task
inspector = _inspector
leader = _leader
location = _location
template_with_items = _template_with_items


def _png_b64() -> str:
    """构造一张能通过魔数/大小校验的最小 PNG（无需真实解码）。"""
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()


@pytest.fixture
async def mcp_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[AsyncSession]:
    """把工具内部的 get_db() 指到测试 session。

    - 工具末尾的 db.commit() 降级为 flush：数据留在事务里，由 db_session
      fixture 的 rollback 兜底清理，避免真提交污染共享测试库；
    - 本地存储目录指到 tmp_path，避免写真文件到仓库 uploads/。
    """
    monkeypatch.setattr(mcp_inspection, "get_db", lambda: db_session)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    monkeypatch.setattr(svc, "_UPLOAD_DIR", str(tmp_path))
    return db_session


async def _photos_of(db: AsyncSession, task_id: uuid.UUID) -> list[InspectionPhoto]:
    result = await db.execute(
        select(InspectionPhoto).where(InspectionPhoto.task_id == task_id)
    )
    return list(result.scalars().all())


async def test_all_success_persists_every_photo(
    mcp_db: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    inspector: User,
) -> None:
    """全部合法时 3 张都落库，计数与实际一致。"""
    result = await mcp_inspection.submit_inspection_photos(
        task_no=inspection_task.task_no,
        equipment=str(equipment_with_dept.id),
        operator_id=str(inspector.id),
        images=[_png_b64() for _ in range(3)],
    )

    assert not result.is_error
    assert result.structured_content["photo_count"] == 3
    assert result.structured_content["failed_count"] == 0
    assert len(await _photos_of(mcp_db, inspection_task.id)) == 3


async def test_partial_failure_keeps_saved_rows(
    mcp_db: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    inspector: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第 2 张失败只回滚本张：第 1、3 张必须仍在库中，计数为 2 成功 1 失败。

    修复前 db.rollback() 会把第 1 张一并回滚（库里只剩 1 行），
    而 success_count 虚报 2。
    """
    original = mcp_inspection.save_photo_from_base64
    calls = 0

    async def flaky_save(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("模拟存储故障")
        return await original(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(mcp_inspection, "save_photo_from_base64", flaky_save)

    result = await mcp_inspection.submit_inspection_photos(
        task_no=inspection_task.task_no,
        equipment=str(equipment_with_dept.id),
        operator_id=str(inspector.id),
        images=[_png_b64() for _ in range(3)],
    )

    assert not result.is_error  # 部分成功不算整体失败
    assert result.structured_content["photo_count"] == 2
    assert result.structured_content["failed_count"] == 1
    assert result.structured_content["failed_details"][0]["index"] == 2

    photos = await _photos_of(mcp_db, inspection_task.id)
    assert len(photos) == 2  # 第 1、3 张保留


async def test_all_failure_reports_error_and_persists_nothing(
    mcp_db: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    inspector: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全部失败时 is_error=True、计数为 0，库里不残留任何行。"""

    async def broken_save(*args: object, **kwargs: object) -> object:
        raise RuntimeError("模拟存储故障")

    monkeypatch.setattr(mcp_inspection, "save_photo_from_base64", broken_save)

    result = await mcp_inspection.submit_inspection_photos(
        task_no=inspection_task.task_no,
        equipment=str(equipment_with_dept.id),
        operator_id=str(inspector.id),
        images=[_png_b64() for _ in range(2)],
    )

    assert result.is_error
    assert result.structured_content["photo_count"] == 0
    assert result.structured_content["failed_count"] == 2
    assert await _photos_of(mcp_db, inspection_task.id) == []
