"""标准计量器具 service 层功能测试（从业务契约角度）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.meter import repository as repo
from app.modules.meter import service
from app.modules.meter.schemas import (
    InstrumentCreate,
    InstrumentFilter,
    InstrumentUpdate,
)
from tests.modules.meter.conftest import create_instrument


class TestComputeStatus:
    def test_in_use_with_past_due_becomes_overdue(self) -> None:
        """在用 + 下次检定已过期 → 显示"超期"。"""
        assert service.compute_status("在用", date.today() - timedelta(days=1)) == "超期"

    def test_manual_overdue_with_future_date_recovers_to_in_use(self) -> None:
        """手动超期 + 下次检定未过期 → 自动恢复"在用"。"""
        assert service.compute_status("超期", date.today() + timedelta(days=1)) == "在用"

    def test_manual_overdue_without_date_recovers_to_in_use(self) -> None:
        """手动超期 + 无下次检定日期 → 自动恢复"在用"。"""
        assert service.compute_status("超期", None) == "在用"

    def test_stopped_never_changes(self) -> None:
        """"停用"永不因日期变为超期。"""
        assert service.compute_status("停用", date.today() - timedelta(days=30)) == "停用"

    def test_other_statuses_passthrough(self) -> None:
        """其他状态原样返回。"""
        assert service.compute_status(None, None) is None
        assert service.compute_status("报废", None) == "报废"


class TestAutoCalcNextCalibrationDate:
    def test_calculates_when_next_missing(self) -> None:
        """给定检定日期+周期且未提供下次日期时，自动计算（+周期月-1天）。"""
        item: dict[str, Any] = {
            "calibration_date": date(2026, 1, 31),
            "calibration_cycle_months": 12,
        }
        service._auto_calc_next_calibration_date(item)
        assert item["next_calibration_date"] == date(2027, 1, 30)

    def test_does_not_override_explicit_next_date(self) -> None:
        """用户手动填写的下次检定日期不应被覆盖。"""
        explicit = date(2030, 6, 1)
        item: dict[str, Any] = {
            "calibration_date": date(2026, 1, 31),
            "calibration_cycle_months": 12,
            "next_calibration_date": explicit,
        }
        service._auto_calc_next_calibration_date(item)
        assert item["next_calibration_date"] == explicit

    def test_skips_when_inputs_missing(self) -> None:
        """缺少检定日期或周期时不计算。"""
        for item in (
            {"calibration_cycle_months": 12},
            {"calibration_date": date(2026, 1, 31)},
            {},
        ):
            service._auto_calc_next_calibration_date(item)
            assert "next_calibration_date" not in item


class TestCreateInstrument:
    async def test_create_sets_sort_order(self, db_session: AsyncSession) -> None:
        """新记录 sort_order 应接在当前最大值之后。"""
        first = await create_instrument(db_session)
        data = InstrumentCreate(
            asset_number=f"NEW-{uuid4().hex[:8]}", instrument_name="新压力表"
        )
        created = await service.create_instrument(db_session, data)
        assert created.sort_order > first.sort_order

    async def test_create_auto_calculates_next_date(self, db_session: AsyncSession) -> None:
        """创建时应自动计算下次检定日期。"""
        data = InstrumentCreate(
            asset_number=f"NEW-{uuid4().hex[:8]}",
            instrument_name="新压力表",
            calibration_date=date(2026, 1, 31),
            calibration_cycle_months=12,
        )
        created = await service.create_instrument(db_session, data)
        assert created.next_calibration_date == date(2027, 1, 30)

    async def test_duplicate_asset_number_rejected(self, db_session: AsyncSession) -> None:
        """资产编号重复应抛 DuplicateException。"""
        existing = await create_instrument(db_session)
        data = InstrumentCreate(
            asset_number=existing.asset_number or "", instrument_name="另一块表"
        )
        with pytest.raises(DuplicateException):
            await service.create_instrument(db_session, data)

    async def test_soft_deleted_asset_number_reusable(self, db_session: AsyncSession) -> None:
        """软删除场景：删除后可用同一资产编号重新添加。"""
        existing = await create_instrument(db_session)
        await service.delete_instrument(db_session, existing.id)

        data = InstrumentCreate(
            asset_number=existing.asset_number or "", instrument_name="重新添加"
        )
        created = await service.create_instrument(db_session, data)
        assert created.asset_number == existing.asset_number


class TestGetAndList:
    async def test_get_missing_raises_not_found(self, db_session: AsyncSession) -> None:
        """查询不存在的器具应抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await service.get_instrument(db_session, uuid4())

    async def test_list_returns_records_and_total(self, db_session: AsyncSession) -> None:
        """列表应返回记录与总数（按唯一部门隔离存量数据）。"""
        dept = f"TEST-LIST-{uuid4().hex[:8]}"
        await create_instrument(db_session, department=dept)
        await create_instrument(db_session, department=dept)
        records, total = await service.list_instruments(
            db_session, InstrumentFilter(department=dept)
        )
        assert total == 2
        assert len(records) == 2

    async def test_list_respects_page_size(self, db_session: AsyncSession) -> None:
        """分页应限制返回条数但不影响总数。"""
        dept = f"TEST-PAGE-{uuid4().hex[:8]}"
        for _ in range(5):
            await create_instrument(db_session, department=dept)
        records, total = await service.list_instruments(
            db_session, InstrumentFilter(department=dept, page=1, page_size=2)
        )
        assert total == 5
        assert len(records) == 2


class TestUpdateInstrument:
    async def test_update_missing_raises_not_found(self, db_session: AsyncSession) -> None:
        """更新不存在的器具应抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await service.update_instrument(db_session, uuid4(), InstrumentUpdate())

    async def test_update_changes_field(self, db_session: AsyncSession) -> None:
        """更新应生效到指定字段。"""
        record = await create_instrument(db_session)
        updated = await service.update_instrument(
            db_session, record.id, InstrumentUpdate(location="二车间")
        )
        assert updated.location == "二车间"

    async def test_update_asset_number_conflict_rejected(self, db_session: AsyncSession) -> None:
        """改成他人已用的资产编号应抛 DuplicateException。"""
        a = await create_instrument(db_session)
        b = await create_instrument(db_session)
        with pytest.raises(DuplicateException):
            await service.update_instrument(
                db_session, b.id, InstrumentUpdate(asset_number=a.asset_number)
            )

    async def test_update_recalculates_next_date_when_omitted(self, db_session: AsyncSession) -> None:
        """更新检定日期/周期但未提供下次日期时应重新计算。"""
        record = await create_instrument(db_session, calibration_date=date(2026, 1, 1))
        updated = await service.update_instrument(
            db_session,
            record.id,
            InstrumentUpdate(calibration_date=date(2026, 2, 1), calibration_cycle_months=6),
        )
        assert updated.calibration_date == date(2026, 2, 1)
        assert updated.next_calibration_date == date(2026, 7, 31)

    async def test_update_keeps_explicit_next_date(self, db_session: AsyncSession) -> None:
        """显式提供的下次检定日期应保留。"""
        record = await create_instrument(db_session)
        keep = date(2030, 12, 31)
        updated = await service.update_instrument(
            db_session,
            record.id,
            InstrumentUpdate(calibration_date=date(2026, 2, 1), next_calibration_date=keep),
        )
        assert updated.next_calibration_date == keep


class TestDeleteInstrument:
    async def test_delete_missing_raises_not_found(self, db_session: AsyncSession) -> None:
        """删除不存在的器具应抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await service.delete_instrument(db_session, uuid4())

    async def test_delete_soft_removes(self, db_session: AsyncSession) -> None:
        """删除后详情不可见（软删除）。"""
        record = await create_instrument(db_session)
        await service.delete_instrument(db_session, record.id)
        with pytest.raises(NotFoundException):
            await service.get_instrument(db_session, record.id)

    async def test_batch_delete_returns_count(self, db_session: AsyncSession) -> None:
        """批量删除返回实际删除数（忽略不存在的 ID）。"""
        a = await create_instrument(db_session)
        b = await create_instrument(db_session)
        assert await service.batch_delete_instruments(db_session, [a.id, b.id, uuid4()]) == 2


class TestBatchCreate:
    async def test_batch_create_mixed_outcomes(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """批量创建：重复编号与空名称跳过，正常记录创建成功。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        existing = await create_instrument(db_session)
        items: list[dict[str, Any]] = [
            {"asset_number": existing.asset_number, "instrument_name": "重复编号"},
            {"instrument_name": ""},  # 名称为空
            {"asset_number": f"OK-{uuid4().hex[:8]}", "instrument_name": "正常记录"},
        ]
        result = await service.batch_create_instruments(db_session, items)
        assert result["total"] == 3
        assert result["created"] == 1
        assert result["skipped"] == 2
        statuses = {r["index"]: r["status"] for r in result["results"]}
        assert statuses == {0: "skipped", 1: "skipped", 2: "created"}

    async def test_batch_create_sort_order_continues(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """批量创建的序号应接在已有记录之后。"""
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        # 先用 service 正常创建一条，再批量创建：序号应接在它后面
        first = await service.create_instrument(
            db_session,
            InstrumentCreate(asset_number=f"B0-{uuid4().hex[:8]}", instrument_name="前置记录"),
        )
        result = await service.batch_create_instruments(
            db_session,
            [{"asset_number": f"B-{uuid4().hex[:8]}", "instrument_name": "后续记录"}],
        )
        assert result["created"] == 1
        row = result["results"][0]
        assert row["id"]
        created = await repo.get_instrument_by_id(db_session, UUID(row["id"]))
        assert created is not None
        assert created.sort_order == first.sort_order + 1


class TestGetAllIds:
    async def test_returns_all_ids_for_filter(self, db_session: AsyncSession) -> None:
        """全选 ID 应返回筛选条件下所有记录 ID。"""
        dept = f"TEST-IDS-{uuid4().hex[:8]}"
        a = await create_instrument(db_session, department=dept)
        b = await create_instrument(db_session, department=dept)
        ids = await service.get_all_instrument_ids(
            db_session, InstrumentFilter(department=dept)
        )
        assert set(ids) == {a.id, b.id}

    async def test_respects_asset_number_filter(self, db_session: AsyncSession) -> None:
        """全选 ID 应遵循资产编号筛选。"""
        a = await create_instrument(db_session)
        await create_instrument(db_session)
        ids = await service.get_all_instrument_ids(
            db_session, InstrumentFilter(asset_number=a.asset_number)
        )
        assert ids == [a.id]


class TestDepartmentsAndFilterOptions:
    async def test_departments_from_departments_table(self, db_session: AsyncSession) -> None:
        """部门列表只返回 instrument 来源的部门。"""
        from tests.modules.meter.conftest import create_department

        inst_dept = f"TEST-INST-{uuid4().hex[:8]}"
        det_dept = f"TEST-DET-{uuid4().hex[:8]}"
        await create_department(db_session, source="instrument", name=inst_dept)
        await create_department(db_session, source="gas_detector", name=det_dept)
        names = await service.get_instrument_departments(db_session)
        assert inst_dept in names
        assert det_dept not in names

    async def test_filter_options_include_dynamic_overdue(self, db_session: AsyncSession) -> None:
        """筛选选项必须包含动态状态"超期"且排第一。"""
        await create_instrument(db_session, status="在用")
        options = await service.get_instrument_filter_options(db_session)
        assert "超期" in options["status"]
        assert options["status"][0] == "超期"


class TestListFilters:
    async def test_asset_number_multi_select(self, db_session: AsyncSession) -> None:
        """资产编号支持逗号多选（IN 查询）。"""
        a = await create_instrument(db_session)
        b = await create_instrument(db_session)
        await create_instrument(db_session)
        records, _ = await service.list_instruments(
            db_session,
            InstrumentFilter(asset_number=f"{a.asset_number},{b.asset_number}"),
        )
        assert {r.id for r in records} == {a.id, b.id}

    async def test_keyword_search(self, db_session: AsyncSession) -> None:
        """keyword 模糊搜索应命中目标记录。"""
        marker = uuid4().hex[:12]
        target = await create_instrument(db_session, instrument_name=f"特制真空表-{marker}")
        await create_instrument(db_session)
        records, total = await service.list_instruments(
            db_session, InstrumentFilter(keyword=marker)
        )
        assert total == 1
        assert records[0].id == target.id
