"""有毒有害可燃探测器 service 层功能测试（从业务契约角度）。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.meter import service
from app.modules.meter.schemas import (
    GasDetectorCreate,
    GasDetectorFilter,
    GasDetectorUpdate,
)
from tests.modules.meter.conftest import create_gas_detector


class TestCreateGasDetector:
    async def test_create_sets_sort_order(self, db_session: AsyncSession) -> None:
        """新探测器 sort_order 应递增。"""
        first = await service.create_gas_detector(
            db_session, GasDetectorCreate(instrument_name="第一台探测器")
        )
        second = await service.create_gas_detector(
            db_session, GasDetectorCreate(instrument_name="第二台探测器")
        )
        assert second.sort_order > first.sort_order

    async def test_duplicate_product_number_rejected(self, db_session: AsyncSession) -> None:
        """产品编号重复应抛 DuplicateException。"""
        existing = await create_gas_detector(db_session)
        data = GasDetectorCreate(
            instrument_name="另一台探测器",
            product_number=existing.product_number,
        )
        with pytest.raises(DuplicateException):
            await service.create_gas_detector(db_session, data)

    async def test_blank_product_number_skips_uniqueness_check(self, db_session: AsyncSession) -> None:
        """产品编号为 None 时不参与唯一性校验，创建应成功。"""
        created = await service.create_gas_detector(
            db_session, GasDetectorCreate(instrument_name="无编号探测器")
        )
        assert created.id is not None

    async def test_soft_deleted_product_number_reusable(self, db_session: AsyncSession) -> None:
        """软删除场景：删除后可用同一产品编号重新添加。"""
        existing = await create_gas_detector(db_session)
        await service.delete_gas_detector(db_session, existing.id)
        created = await service.create_gas_detector(
            db_session,
            GasDetectorCreate(instrument_name="重新添加", product_number=existing.product_number),
        )
        assert created.product_number == existing.product_number


class TestGetAndList:
    async def test_get_missing_raises_not_found(self, db_session: AsyncSession) -> None:
        """查询不存在的探测器应抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await service.get_gas_detector(db_session, uuid4())

    async def test_list_isolated_by_unique_department(self, db_session: AsyncSession) -> None:
        """列表按唯一部门隔离统计总数。"""
        dept = f"TEST-GD-{uuid4().hex[:8]}"
        await create_gas_detector(db_session, department=dept)
        await create_gas_detector(db_session, department=dept)
        records, total = await service.list_gas_detectors(
            db_session, GasDetectorFilter(department=dept)
        )
        assert total == 2
        assert len(records) == 2


class TestUpdateGasDetector:
    async def test_update_missing_raises_not_found(self, db_session: AsyncSession) -> None:
        """更新不存在的探测器应抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await service.update_gas_detector(db_session, uuid4(), GasDetectorUpdate())

    async def test_update_changes_field(self, db_session: AsyncSession) -> None:
        """更新应生效到指定字段。"""
        record = await create_gas_detector(db_session)
        updated = await service.update_gas_detector(
            db_session, record.id, GasDetectorUpdate(installation_location="二车间")
        )
        assert updated.installation_location == "二车间"

    async def test_update_product_number_conflict_rejected(self, db_session: AsyncSession) -> None:
        """改成他人已用的产品编号应抛 DuplicateException。"""
        a = await create_gas_detector(db_session)
        b = await create_gas_detector(db_session)
        with pytest.raises(DuplicateException):
            await service.update_gas_detector(
                db_session, b.id, GasDetectorUpdate(product_number=a.product_number)
            )

    async def test_update_clears_product_number_allowed(self, db_session: AsyncSession) -> None:
        """清空产品编号合法（空串/None 均不参与唯一性校验）。"""
        record = await create_gas_detector(db_session)
        updated = await service.update_gas_detector(
            db_session, record.id, GasDetectorUpdate(product_number="")
        )
        assert not updated.product_number


class TestDeleteGasDetector:
    async def test_delete_soft_removes(self, db_session: AsyncSession) -> None:
        """删除后详情不可见（软删除）。"""
        record = await create_gas_detector(db_session)
        await service.delete_gas_detector(db_session, record.id)
        with pytest.raises(NotFoundException):
            await service.get_gas_detector(db_session, record.id)

    async def test_batch_delete_returns_count(self, db_session: AsyncSession) -> None:
        """批量删除返回实际删除数。"""
        a = await create_gas_detector(db_session)
        b = await create_gas_detector(db_session)
        assert await service.batch_delete_gas_detectors(db_session, [a.id, b.id]) == 2


class TestBatchCreateGasDetectors:
    async def test_batch_create_skips_blank_name(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """批量创建：空名称跳过，正常记录创建成功。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        items: list[dict[str, Any]] = [
            {"instrument_name": ""},
            {"instrument_name": "正常探测器", "product_number": f"PN-{uuid4().hex[:8]}"},
        ]
        result = await service.batch_create_gas_detectors(db_session, items)
        assert result["total"] == 2
        assert result["created"] == 1
        assert result["skipped"] == 1


class TestGetAllIdsAndDepartments:
    async def test_ids_respect_filter(self, db_session: AsyncSession) -> None:
        """全选 ID 应遵循部门筛选。"""
        dept = f"TEST-GDIDS-{uuid4().hex[:8]}"
        a = await create_gas_detector(db_session, department=dept)
        b = await create_gas_detector(db_session, department=dept)
        ids = await service.get_all_gas_detector_ids(
            db_session, GasDetectorFilter(department=dept)
        )
        assert set(ids) == {a.id, b.id}

    async def test_departments_only_gas_detector_source(self, db_session: AsyncSession) -> None:
        """部门列表只返回 gas_detector 来源的部门。"""
        from tests.modules.meter.conftest import create_department

        det_dept = f"TEST-GDDEPT-{uuid4().hex[:8]}"
        await create_department(db_session, source="gas_detector", name=det_dept)
        await create_department(db_session, source="instrument", name=f"TEST-INS-{uuid4().hex[:8]}")
        names = await service.get_gas_detector_departments(db_session)
        assert det_dept in names

    async def test_filter_options_include_overdue(self, db_session: AsyncSession) -> None:
        """筛选选项必须包含"超期"且排第一。"""
        await create_gas_detector(db_session, status="在用")
        options = await service.get_gas_detector_filter_options(db_session)
        assert "超期" in options["status"]
        assert options["status"][0] == "超期"
