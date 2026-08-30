"""部门管理 service 层功能测试（从业务契约角度）。"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.meter import repository as repo
from app.modules.meter import service
from app.modules.meter.schemas import DepartmentCreate, DepartmentUpdate
from tests.modules.meter.conftest import (
    create_department,
    create_gas_detector,
    create_instrument,
)


def _heads() -> list[dict[str, str]]:
    return [{"name": "张三", "feishu_open_id": "ou_zhangsan"}]


class TestCreateDepartment:
    async def test_blank_name_rejected(self, db_session: AsyncSession) -> None:
        """空白部门名应抛 ValueError。"""
        with pytest.raises(ValueError):
            await service.create_department(
                db_session, DepartmentCreate(source="instrument", name="   ")
            )

    async def test_duplicate_same_source_rejected(self, db_session: AsyncSession) -> None:
        """同一 source 下重名应抛 DuplicateException。"""
        name = f"TEST-DEPT-{uuid4().hex[:8]}"
        await create_department(db_session, source="instrument", name=name)
        with pytest.raises(DuplicateException):
            await service.create_department(
                db_session, DepartmentCreate(source="instrument", name=name)
            )

    async def test_same_name_different_source_allowed(self, db_session: AsyncSession) -> None:
        """不同 source 下同名部门允许共存。"""
        name = f"TEST-DEPT-{uuid4().hex[:8]}"
        await create_department(db_session, source="instrument", name=name)
        created = await service.create_department(
            db_session, DepartmentCreate(source="gas_detector", name=name)
        )
        assert created.source == "gas_detector"

    async def test_name_stripped(self, db_session: AsyncSession) -> None:
        """部门名应去除首尾空白。"""
        name = f"TEST-DEPT-{uuid4().hex[:8]}"
        created = await service.create_department(
            db_session, DepartmentCreate(source="instrument", name=f"  {name}  ")
        )
        assert created.name == name


class TestListDepartments:
    async def test_record_count_by_source(self, db_session: AsyncSession) -> None:
        """record_count 按 source 只统计对应表的使用量。"""
        dept_name = f"TEST-DEPT-{uuid4().hex[:8]}"
        await create_department(db_session, source="instrument", name=dept_name)
        await create_instrument(db_session, department=dept_name)
        await create_instrument(db_session, department=dept_name)
        await create_gas_detector(db_session, department=dept_name)

        items = await service.list_departments(db_session, source="instrument")
        target = [d for d in items if d["name"] == dept_name]
        assert len(target) == 1
        assert target[0]["record_count"] == 2  # 只统计器具表，不含探测器


class TestUpdateDepartment:
    async def test_missing_raises_not_found(self, db_session: AsyncSession) -> None:
        """更新不存在的部门应抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await service.update_department(
                db_session, uuid4(), DepartmentUpdate(name="新部门")
            )

    async def test_rename_cascades_to_records(self, db_session: AsyncSession) -> None:
        """instrument 部门改名应联动器具表、不影响探测器表。"""
        old_name = f"TEST-OLD-{uuid4().hex[:8]}"
        new_name = f"TEST-NEW-{uuid4().hex[:8]}"
        dept = await create_department(db_session, source="instrument", name=old_name)
        inst = await create_instrument(db_session, department=old_name)
        det = await create_gas_detector(db_session, department=old_name)

        await service.update_department(db_session, dept.id, DepartmentUpdate(name=new_name))

        inst_after = await repo.get_instrument_by_id(db_session, inst.id)
        det_after = await repo.get_gas_detector_by_id(db_session, det.id)
        assert inst_after is not None and inst_after.department == new_name
        assert det_after is not None and det_after.department == old_name

    async def test_rename_cascades_gas_detector_records(self, db_session: AsyncSession) -> None:
        """gas_detector 部门改名应联动探测器表。"""
        old_name = f"TEST-OLD-{uuid4().hex[:8]}"
        new_name = f"TEST-NEW-{uuid4().hex[:8]}"
        dept = await create_department(db_session, source="gas_detector", name=old_name)
        det = await create_gas_detector(db_session, department=old_name)

        await service.update_department(db_session, dept.id, DepartmentUpdate(name=new_name))

        det_after = await repo.get_gas_detector_by_id(db_session, det.id)
        assert det_after is not None and det_after.department == new_name

    async def test_rename_conflict_rejected(self, db_session: AsyncSession) -> None:
        """改成同 source 已有名称应抛 DuplicateException。"""
        a_name = f"TEST-A-{uuid4().hex[:8]}"
        b_name = f"TEST-B-{uuid4().hex[:8]}"
        dept = await create_department(db_session, source="instrument", name=a_name)
        await create_department(db_session, source="instrument", name=b_name)
        with pytest.raises(DuplicateException):
            await service.update_department(db_session, dept.id, DepartmentUpdate(name=b_name))

    async def test_update_heads_and_auto_notify(self, db_session: AsyncSession) -> None:
        """负责人与提醒开关可更新。"""
        dept = await create_department(db_session)
        updated = await service.update_department(
            db_session,
            dept.id,
            DepartmentUpdate(name=dept.name, heads=_heads(), auto_notify_enabled=True),
        )
        assert cast(Any, updated.heads) == _heads()
        assert updated.auto_notify_enabled is True


class TestDeleteDepartment:
    async def test_delete_with_records_rejected(self, db_session: AsyncSession) -> None:
        """仍有记录使用的部门不可删除。"""
        dept_name = f"TEST-DEPT-{uuid4().hex[:8]}"
        dept = await create_department(db_session, source="instrument", name=dept_name)
        await create_instrument(db_session, department=dept_name)
        with pytest.raises(DuplicateException):
            await service.delete_department(db_session, dept.id)

    async def test_delete_without_records_succeeds(self, db_session: AsyncSession) -> None:
        """无记录使用的部门可删除（软删除）。"""
        dept = await create_department(db_session)
        await service.delete_department(db_session, dept.id)
        assert await repo.get_department_by_id(db_session, dept.id) is None


class TestPersonnelCandidates:
    async def test_returns_identity_users(self, db_session: AsyncSession) -> None:
        """候选人列表应来自 identity.users 未删除用户。"""
        from app.platform.identity.models import User

        marker = uuid4().hex[:8]
        db_session.add(
            User(name=f"候选人{marker}", feishu_open_id=f"ou_{marker}", department="质量部")
        )
        await db_session.flush()
        candidates = await service.get_personnel_candidates(db_session)
        names = [c["name"] for c in candidates]
        assert f"候选人{marker}" in names
