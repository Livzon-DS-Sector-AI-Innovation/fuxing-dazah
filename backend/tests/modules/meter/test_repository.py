"""meter repository 层查询语义测试（从筛选/统计契约角度）。

注意：dev 库存在大量存量数据，凡支持 department 过滤的查询都用唯一部门隔离；
不支持隔离的查询（overview、due_for_calibration）用"前后增量/成员判定"断言。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter import repository as repo
from tests.modules.meter.conftest import (
    create_department,
    create_gas_detector,
    create_instrument,
    create_report,
)


class TestUtils:
    def test_parse_multi(self) -> None:
        """逗号分隔的筛选值应拆分为去空白列表；空值返回 None。"""
        assert repo._parse_multi("a, b ,c") == ["a", "b", "c"]
        assert repo._parse_multi("") is None
        assert repo._parse_multi(None) is None

    def test_coerce_date_fields(self) -> None:
        """update 字典中的日期字符串应转为 date，兼容 asyncpg。"""
        updates: dict[str, Any] = {"calibration_date": "2026-08-01", "location": "x"}
        repo._coerce_date_fields(updates)
        assert updates["calibration_date"] == date(2026, 8, 1)
        assert updates["location"] == "x"  # 非日期字段不动


class TestListInstrumentsFilters:
    async def test_multi_select_in_query(self, db_session: AsyncSession) -> None:
        """同字段多值筛选（逗号分隔）应命中任一值。"""
        dept = f"TEST-REPO-{uuid4().hex[:8]}"
        a = await create_instrument(db_session, department=dept, location="一车间")
        b = await create_instrument(db_session, department=dept, location="二车间")
        await create_instrument(db_session, department=dept, location="三车间")
        records, _ = await repo.list_instruments(
            db_session, department=dept, location="一车间,二车间", page_size=200
        )
        assert {r.id for r in records} == {a.id, b.id}

    async def test_status_overdue_dynamic(self, db_session: AsyncSession) -> None:
        """筛选"超期"应命中：DB 在用/超期且下次检定已过期的记录。"""
        dept = f"TEST-REPO-{uuid4().hex[:8]}"
        hit1 = await create_instrument(
            db_session,
            department=dept,
            status="在用",
            next_calibration_date=date.today() - timedelta(days=1),
        )
        hit2 = await create_instrument(
            db_session,
            department=dept,
            status="超期",
            next_calibration_date=date.today() - timedelta(days=1),
        )
        await create_instrument(
            db_session,
            department=dept,
            status="停用",
            next_calibration_date=date.today() - timedelta(days=1),
        )
        await create_instrument(
            db_session,
            department=dept,
            status="在用",
            next_calibration_date=date.today() + timedelta(days=10),
        )
        records, _ = await repo.list_instruments(
            db_session, department=dept, status="超期", page_size=200
        )
        assert {r.id for r in records} == {hit1.id, hit2.id}

    async def test_status_in_use_dynamic(self, db_session: AsyncSession) -> None:
        """筛选"在用"应命中：手动超期但未过期的记录（自动恢复语义）。"""
        dept = f"TEST-REPO-{uuid4().hex[:8]}"
        hit = await create_instrument(
            db_session,
            department=dept,
            status="超期",
            next_calibration_date=date.today() + timedelta(days=10),
        )
        records, _ = await repo.list_instruments(
            db_session, department=dept, status="在用", page_size=200
        )
        assert hit.id in {r.id for r in records}

    async def test_date_range_filters(self, db_session: AsyncSession) -> None:
        """下次检定日期区间过滤（before/after 闭区间）。"""
        dept = f"TEST-REPO-{uuid4().hex[:8]}"
        inside = await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=10)
        )
        await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=60)
        )
        records, _ = await repo.list_instruments(
            db_session,
            department=dept,
            next_calibration_after=date.today(),
            next_calibration_before=date.today() + timedelta(days=30),
            page_size=200,
        )
        assert [r.id for r in records] == [inside.id]

    async def test_keyword_matches_multiple_columns(self, db_session: AsyncSession) -> None:
        """keyword 应同时匹配资产编号/名称/型号/编号/地点。"""
        marker = uuid4().hex[:8]
        by_name = await create_instrument(db_session, instrument_name=f"名称{marker}")
        by_asset = await create_instrument(db_session, asset_number=f"ZC{marker}")
        records, _ = await repo.list_instruments(db_session, keyword=marker, page_size=200)
        ids = {r.id for r in records}
        assert by_name.id in ids and by_asset.id in ids

    async def test_has_report_filter(self, db_session: AsyncSession) -> None:
        """has_report 应按是否存在未删除报告过滤。"""
        dept = f"TEST-REPO-{uuid4().hex[:8]}"
        with_report = await create_instrument(db_session, department=dept)
        without_report = await create_instrument(db_session, department=dept)
        await create_report(db_session, instrument_id=with_report.id)

        records, _ = await repo.list_instruments(
            db_session, department=dept, has_report=True, page_size=200
        )
        assert with_report.id in {r.id for r in records}
        assert without_report.id not in {r.id for r in records}

        records, _ = await repo.list_instruments(
            db_session, department=dept, has_report=False, page_size=200
        )
        assert without_report.id in {r.id for r in records}
        assert with_report.id not in {r.id for r in records}

    async def test_pagination_and_ordering(self, db_session: AsyncSession) -> None:
        """分页按 sort_order 升序、返回总数。"""
        dept = f"TEST-REPO-{uuid4().hex[:8]}"
        first = await create_instrument(db_session, department=dept, sort_order=1)
        second = await create_instrument(db_session, department=dept, sort_order=2)
        records, total = await repo.list_instruments(
            db_session, department=dept, page=1, page_size=1
        )
        assert total == 2
        assert [r.id for r in records] == [first.id]
        records, _ = await repo.list_instruments(
            db_session, department=dept, page=2, page_size=1
        )
        assert [r.id for r in records] == [second.id]


class TestGetAllInstrumentIds:
    async def test_respects_filters(self, db_session: AsyncSession) -> None:
        """全选 ID 查询应与列表查询共用同一套筛选规则。"""
        dept = f"TEST-REPO-{uuid4().hex[:8]}"
        a = await create_instrument(db_session, department=dept, status="停用")
        b = await create_instrument(db_session, department=dept, status="停用")
        await create_instrument(db_session, department=dept, status="在用")
        ids = await repo.get_all_instrument_ids(db_session, department=dept, status="停用")
        assert set(ids) == {a.id, b.id}


class TestGasDetectorList:
    async def test_status_and_has_report(self, db_session: AsyncSession) -> None:
        """探测器筛选同器具：动态状态 + 报告存在性。"""
        dept = f"TEST-REPO-{uuid4().hex[:8]}"
        det = await create_gas_detector(db_session, department=dept)
        await create_report(db_session, gas_detector_id=det.id)
        await create_gas_detector(db_session, department=dept)
        records, _ = await repo.list_gas_detectors(
            db_session, department=dept, has_report=True, page_size=200
        )
        assert [r.id for r in records] == [det.id]


class TestDueQueries:
    async def test_due_for_calibration_window(self, db_session: AsyncSession) -> None:
        """days_before=30：含今天到期，不含未来 60 天；已过期只在 days_before=0 时出现。"""
        overdue = await create_instrument(
            db_session, next_calibration_date=date.today() - timedelta(days=5)
        )
        within = await create_instrument(
            db_session, next_calibration_date=date.today() + timedelta(days=20)
        )
        far = await create_instrument(
            db_session, next_calibration_date=date.today() + timedelta(days=60)
        )
        window_ids = {
            r.id for r in await repo.list_instruments_due_for_calibration(db_session, days_before=30)
        }
        assert within.id in window_ids
        assert far.id not in window_ids
        assert overdue.id not in window_ids  # 未来窗口不含已过期

        zero_ids = {
            r.id for r in await repo.list_instruments_due_for_calibration(db_session, days_before=0)
        }
        assert overdue.id in zero_ids  # 0 = 截止今天，含全部已过期

    async def test_due_grouped_four_windows(self, db_session: AsyncSession) -> None:
        """4 窗口分组：due_today 含已过期；7d/30d/90d 各自区间且互不重叠。"""
        dept = f"TEST-DUE-{uuid4().hex[:8]}"
        overdue = await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() - timedelta(days=1)
        )
        in7 = await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=3)
        )
        in30 = await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=15)
        )
        in90 = await create_instrument(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=45)
        )
        grouped = await repo.list_instruments_due_grouped(db_session, dept)
        assert overdue.id in {r.id for r in grouped["due_today"]}
        assert in7.id in {r.id for r in grouped["due_7d"]}
        assert in30.id in {r.id for r in grouped["due_30d"]}
        assert in90.id in {r.id for r in grouped["due_90d"]}
        # 各组互不重叠
        assert overdue.id not in {r.id for r in grouped["due_7d"]}
        assert in7.id not in {r.id for r in grouped["due_30d"]}
        assert in30.id not in {r.id for r in grouped["due_90d"]}

    async def test_due_grouped_gas_detector(self, db_session: AsyncSession) -> None:
        """探测器同样支持 4 窗口分组。"""
        dept = f"TEST-DUE-{uuid4().hex[:8]}"
        det = await create_gas_detector(
            db_session, department=dept, next_calibration_date=date.today() + timedelta(days=3)
        )
        grouped = await repo.list_gas_detectors_due_grouped(db_session, dept)
        assert det.id in {r.id for r in grouped["due_7d"]}

    async def test_notifiable_departments_filters(self, db_session: AsyncSession) -> None:
        """开启提醒且有负责人的部门才会进入通知列表。"""
        name_a = f"TEST-ND-{uuid4().hex[:8]}"
        name_b = f"TEST-ND-{uuid4().hex[:8]}"
        enabled = await create_department(
            db_session, name=name_a, auto_notify_enabled=True,
            heads=[{"name": "张三", "feishu_open_id": "ou_1"}],
        )
        await create_department(db_session, name=name_b, auto_notify_enabled=False, heads=[{"name": "张三", "feishu_open_id": "ou_1"}])
        await create_department(
            db_session, auto_notify_enabled=True, heads=[]
        )
        depts = await repo.get_notifiable_departments(db_session)
        names = {d.name for d in depts}
        assert name_a in names
        assert name_b not in names  # 开关关闭
        assert enabled.name in names


class TestOverview:
    async def test_instrument_overview_buckets(self, db_session: AsyncSession) -> None:
        """总览各桶：总数/在用/超期/停用 + 4 个到期窗口，用前后增量断言。"""
        before = await repo.get_instrument_overview(db_session)

        dept = f"TEST-OV-{uuid4().hex[:8]}"
        await create_instrument(
            db_session,
            department=dept,
            status="停用",
            next_calibration_date=None,
        )
        await create_instrument(
            db_session,
            department=dept,
            status="在用",
            next_calibration_date=date.today() - timedelta(days=1),
        )
        await create_instrument(
            db_session,
            department=dept,
            status="在用",
            next_calibration_date=date.today() + timedelta(days=3),
        )

        after = await repo.get_instrument_overview(db_session)
        assert after["total"] == before["total"] + 3
        assert after["stopped"] == before["stopped"] + 1
        assert after["overdue"] == before["overdue"] + 1
        assert after["in_use"] == before["in_use"] + 1
        # 过期记录计入 due_today（含已过期），3 天后到期计入 due_7d
        assert after["due_today"] >= before["due_today"] + 1
        assert after["due_7d"] == before["due_7d"] + 1

    async def test_gas_detector_overview(self, db_session: AsyncSession) -> None:
        """探测器总览结构一致且计数正确。"""
        before = await repo.get_gas_detector_overview(db_session)
        await create_gas_detector(db_session, status="停用", next_calibration_date=None)
        after = await repo.get_gas_detector_overview(db_session)
        assert after["total"] == before["total"] + 1
        assert after["stopped"] == before["stopped"] + 1


class TestDateStatsRepo:
    async def test_flat_rows_aggregation(self, db_session: AsyncSession) -> None:
        """日期聚合返回扁平行并按日期降序。"""
        dept = f"TEST-DS-{uuid4().hex[:8]}"
        await create_instrument(
            db_session, department=dept, calibration_date=date(2026, 2, 10)
        )
        await create_instrument(
            db_session, department=dept, calibration_date=date(2026, 2, 10)
        )
        await create_instrument(
            db_session, department=dept, calibration_date=date(2026, 1, 5)
        )
        rows = await repo.get_instrument_date_stats(
            db_session, field="calibration_date", department=dept
        )
        assert rows[0] == {"year": 2026, "month": 2, "day": 10, "count": 2}
        assert rows[1] == {"year": 2026, "month": 1, "day": 5, "count": 1}

    async def test_invalid_field_rejected(self, db_session: AsyncSession) -> None:
        """不支持的统计字段应抛 ValueError。"""
        with pytest.raises(ValueError):
            await repo.get_instrument_date_stats(db_session, field="created_at")


class TestReportsRepo:
    async def test_find_existing_certificate_nos_only_undeleted(self, db_session: AsyncSession) -> None:
        """证书编号查重只统计未删除报告。"""
        inst = await create_instrument(db_session)
        live = await create_report(db_session, instrument_id=inst.id, certificate_no="CN-LIVE")
        deleted = await create_report(db_session, instrument_id=inst.id, certificate_no="CN-DEL")
        await repo.soft_delete_report(db_session, deleted.id)

        existing = await repo.find_existing_certificate_nos(db_session, ["CN-LIVE", "CN-DEL"])
        assert existing == {"CN-LIVE"}
        assert live.id is not None  # 存活报告未被误删

    async def test_search_by_name_fuzzy(self, db_session: AsyncSession) -> None:
        """名称模糊搜索返回候选（限条数）。"""
        marker = uuid4().hex[:8]
        await create_instrument(db_session, instrument_name=f"压力表{marker}")
        hits = await repo.search_instruments_by_name(db_session, marker)
        assert len(hits) == 1

    async def test_find_by_name_and_serial_exact(self, db_session: AsyncSession) -> None:
        """名称模糊 + 编号精确匹配。"""
        marker = uuid4().hex[:8]
        target = await create_instrument(
            db_session, instrument_name=f"压力表{marker}", serial_number="SN-EXACT"
        )
        await create_instrument(
            db_session, instrument_name=f"压力表{marker}", serial_number="SN-OTHER"
        )
        found = await repo.find_instrument_by_name_and_serial(db_session, marker, "SN-EXACT")
        assert found is not None and found.id == target.id

    async def test_find_gas_detector_by_name_and_product(self, db_session: AsyncSession) -> None:
        """探测器名称模糊 + 产品编号精确匹配。"""
        marker = uuid4().hex[:8]
        target = await create_gas_detector(
            db_session, instrument_name=f"探测器{marker}", product_number="PN-EXACT"
        )
        found = await repo.find_gas_detector_by_name_and_product(db_session, marker, "PN-EXACT")
        assert found is not None and found.id == target.id


class TestDepartmentsRepo:
    async def test_sync_departments_clear_and_reinsert(self, db_session: AsyncSession) -> None:
        """sync 写入新部门集合并返回新增数。"""
        name_new = f"TEST-SYNC-{uuid4().hex[:8]}"
        added = await repo.sync_departments(db_session, "instrument", {name_new})
        assert added == 1
        dept = await repo.get_department_by_source_and_name(db_session, "instrument", name_new)
        assert dept is not None

    async def test_sync_restores_soft_deleted(self, db_session: AsyncSession) -> None:
        """sync 遇到已软删除的同名部门应恢复而不是报错。"""
        name = f"TEST-SYNC-{uuid4().hex[:8]}"
        dept = await create_department(db_session, source="instrument", name=name)
        await repo.soft_delete_department(db_session, dept.id)

        added = await repo.sync_departments(db_session, "instrument", {name})
        assert added == 1
        restored = await repo.get_department_by_source_and_name(db_session, "instrument", name)
        assert restored is not None
        assert restored.is_deleted is False

    async def test_rename_department_in_records_by_source(self, db_session: AsyncSession) -> None:
        """改名联动只作用于对应 source 的表。"""
        old = f"TEST-OLD-{uuid4().hex[:8]}"
        new = f"TEST-NEW-{uuid4().hex[:8]}"
        inst = await create_instrument(db_session, department=old)
        det = await create_gas_detector(db_session, department=old)

        await repo.rename_department_in_records(db_session, old, new, "instrument")

        inst_after = await repo.get_instrument_by_id(db_session, inst.id)
        det_after = await repo.get_gas_detector_by_id(db_session, det.id)
        assert inst_after is not None and inst_after.department == new
        assert det_after is not None and det_after.department == old

    async def test_count_records_by_department(self, db_session: AsyncSession) -> None:
        """部门使用量分别统计两张表。"""
        name = f"TEST-CNT-{uuid4().hex[:8]}"
        await create_instrument(db_session, department=name)
        await create_instrument(db_session, department=name)
        await create_gas_detector(db_session, department=name)
        counts = await repo.count_records_by_department(db_session, name)
        assert counts == {"instrument_count": 2, "gas_detector_count": 1}


class TestSettingsRepo:
    async def test_get_or_create_defaults(self, db_session: AsyncSession) -> None:
        """设置不存在时自动创建默认行。"""
        settings = await repo.get_or_create_meter_settings(db_session)
        assert settings.id is not None

    async def test_update_reflects(self, db_session: AsyncSession) -> None:
        """更新提醒时间后重查可见。"""
        from datetime import time

        await repo.get_or_create_meter_settings(db_session)
        updated = await repo.update_meter_settings(db_session, time(8, 15))
        assert updated.notify_time == time(8, 15)
