"""产线字典与用户-产线绑定测试。

覆盖业务场景：
- 产线 CRUD：创建并列表；重复 name 拒绝；更新 name 唯一性；
  软删后可用同 name 重建
- 绑定：绑定成功并组装 line_name；重复绑定拒绝；
  解除后重新绑定成功；绑定不存在产线拒绝
- 删除产线：级联软删其名下活跃绑定，历史产出引用不受影响
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.production.schemas.line import LineCreate, LineUpdate
from app.modules.production.service import line_service


def _create(name: str = "一号产线") -> LineCreate:
    return LineCreate(name=name, remark="测试产线")


class TestLineCrud:
    async def test_create_and_list(self, db_session: AsyncSession) -> None:
        line = await line_service.create_line(db_session, _create(), None)
        assert line.name == "一号产线"

        items = await line_service.list_lines(db_session)
        assert any(ln.id == line.id for ln in items)

    async def test_duplicate_name_rejected(self, db_session: AsyncSession) -> None:
        await line_service.create_line(db_session, _create(), None)
        with pytest.raises(DuplicateException):
            await line_service.create_line(db_session, _create(), None)

    async def test_update_name_unique(self, db_session: AsyncSession) -> None:
        await line_service.create_line(db_session, _create(), None)
        other = await line_service.create_line(
            db_session, _create(name="二号产线"), None,
        )
        with pytest.raises(DuplicateException):
            await line_service.update_line(
                db_session, other.id, LineUpdate(name="一号产线"), None,
            )
        updated = await line_service.update_line(
            db_session, other.id, LineUpdate(name="二号产线新名"), None,
        )
        assert updated.name == "二号产线新名"

    async def test_delete_and_recreate_same_name(
        self, db_session: AsyncSession,
    ) -> None:
        line = await line_service.create_line(db_session, _create(), None)
        await line_service.delete_line(db_session, line.id, None)

        items = await line_service.list_lines(db_session)
        assert all(ln.id != line.id for ln in items)

        # 软删后同 name 可重建
        rebuilt = await line_service.create_line(db_session, _create(), None)
        assert rebuilt.id != line.id
        assert rebuilt.name == "一号产线"

    async def test_delete_missing_raises(self, db_session: AsyncSession) -> None:
        with pytest.raises(NotFoundException):
            await line_service.delete_line(db_session, uuid.uuid4(), None)


class TestLineAssignment:
    async def _create_line(self, db_session: AsyncSession) -> uuid.UUID:
        line = await line_service.create_line(db_session, _create(), None)
        return line.id

    async def test_bind_and_list_with_line_name(
        self, db_session: AsyncSession,
    ) -> None:
        line_id = await self._create_line(db_session)
        user_id = uuid.uuid4()
        binding = await line_service.bind_user_line(
            db_session, user_id=user_id, line_id=line_id, created_by=user_id,
        )
        assert binding.line_name == "一号产线"

        items = await line_service.list_line_assignments(db_session, line_id=line_id)
        assert any(b.id == binding.id for b in items)

        mine = await line_service.list_line_assignments(db_session, user_id=user_id)
        assert any(b.id == binding.id for b in mine)

    async def test_duplicate_bind_rejected(self, db_session: AsyncSession) -> None:
        line_id = await self._create_line(db_session)
        user_id = uuid.uuid4()
        await line_service.bind_user_line(
            db_session, user_id=user_id, line_id=line_id, created_by=user_id,
        )
        with pytest.raises(DuplicateException):
            await line_service.bind_user_line(
                db_session, user_id=user_id, line_id=line_id, created_by=user_id,
            )

    async def test_unbind_and_rebind(self, db_session: AsyncSession) -> None:
        line_id = await self._create_line(db_session)
        user_id = uuid.uuid4()
        binding = await line_service.bind_user_line(
            db_session, user_id=user_id, line_id=line_id, created_by=user_id,
        )
        await line_service.unbind_user_line(db_session, binding.id)

        items = await line_service.list_line_assignments(db_session, user_id=user_id)
        assert all(b.id != binding.id for b in items)

        # 软删旧绑定留着，重新绑定插新行
        rebind = await line_service.bind_user_line(
            db_session, user_id=user_id, line_id=line_id, created_by=user_id,
        )
        assert rebind.id != binding.id

    async def test_bind_missing_line_rejected(self, db_session: AsyncSession) -> None:
        with pytest.raises(NotFoundException):
            await line_service.bind_user_line(
                db_session, user_id=uuid.uuid4(), line_id=uuid.uuid4(),
                created_by=None,
            )

    async def test_unbind_missing_raises(self, db_session: AsyncSession) -> None:
        with pytest.raises(NotFoundException):
            await line_service.unbind_user_line(db_session, uuid.uuid4())

    async def test_delete_line_cascades_assignments(
        self, db_session: AsyncSession,
    ) -> None:
        """删除产线级联软删其名下活跃绑定。"""
        line_id = await self._create_line(db_session)
        user_id = uuid.uuid4()
        await line_service.bind_user_line(
            db_session, user_id=user_id, line_id=line_id, created_by=user_id,
        )
        await line_service.delete_line(db_session, line_id, None)

        mine = await line_service.list_line_assignments(db_session, user_id=user_id)
        assert mine == []

    async def test_get_user_line_ids(self, db_session: AsyncSession) -> None:
        line_id = await self._create_line(db_session)
        user_id = uuid.uuid4()
        await line_service.bind_user_line(
            db_session, user_id=user_id, line_id=line_id, created_by=user_id,
        )
        ids = await line_service.get_user_line_ids(db_session, user_id)
        assert ids == [line_id]
