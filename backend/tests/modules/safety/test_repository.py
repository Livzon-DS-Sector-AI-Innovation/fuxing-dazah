"""Safety module — repository 层测试（安全检查/事故/每日报备/职业危害监测）。

复用顶层 tests/conftest.py 的 db_session（真实库 + 回滚）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    Accident,
    DailyRiskReport,
    OhHazardMonitor,
    SafetyCheck,
)
from app.modules.safety.repository import SafetyRepository


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create_check(db: AsyncSession, **overrides) -> SafetyCheck:
    repo = SafetyRepository(db)
    item = await repo.create_check(
        {
            "check_no": _uid("CHK"),
            "check_type": "special",
            "check_date": datetime.now(),
            "department": overrides.pop("department", "EHS部"),
            "status": overrides.pop("status", "draft"),
            **overrides,
        }
    )
    await db.flush()
    return item


async def _create_accident(db: AsyncSession, **overrides) -> Accident:
    repo = SafetyRepository(db)
    item = await repo.create_accident(
        {
            "accident_no": _uid("ACC"),
            "accident_type": "fire",
            "accident_level": "serious",
            "happened_at": datetime.now(),
            "department": overrides.pop("department", "生产部"),
            "description": "仓库火灾测试",
            "reported_at": datetime.now(),
            **overrides,
        }
    )
    await db.flush()
    return item


class TestSafetyCheckRepository:
    async def test_get_checks_with_filters(self, db_session: AsyncSession) -> None:
        await _create_check(db_session, status="draft")
        await _create_check(db_session, status="submitted")
        await _create_check(db_session, department="特殊部门")

        repo = SafetyRepository(db_session)
        items, total = await repo.get_checks(status="submitted")
        assert total >= 1
        assert all(i.status == "submitted" for i in items)

        items, total = await repo.get_checks(department="特殊部门")
        assert total == 1

    async def test_soft_delete(self, db_session: AsyncSession) -> None:
        item = await _create_check(db_session)
        repo = SafetyRepository(db_session)

        assert await repo.delete_check(item.id) is True
        assert await repo.get_check_by_id(item.id) is None
        # 软删除后同编号可重建（部分唯一索引只约束未删除行）
        rebuilt = await repo.create_check({"check_no": item.check_no, "check_type": "daily", "check_date": datetime.now()})
        assert rebuilt.id != item.id

    async def test_update_check(self, db_session: AsyncSession) -> None:
        item = await _create_check(db_session)
        repo = SafetyRepository(db_session)
        updated = await repo.update_check(item.id, {"result": "qualified", "status": "reviewed"})
        assert updated is not None
        assert updated.result == "qualified"
        assert updated.status == "reviewed"


class TestAccidentRepository:
    async def test_filters_and_keyword(self, db_session: AsyncSession) -> None:
        await _create_accident(db_session, status="reported")
        target = await _create_accident(db_session, department="仓储部", status="closed")

        repo = SafetyRepository(db_session)
        items, total = await repo.get_accidents(status="closed")
        assert total >= 1
        assert any(i.id == target.id for i in items)

        items, total = await repo.get_accidents(keyword="仓库火灾")
        assert total >= 1

        date_from = datetime.now() - timedelta(days=1)
        items, total = await repo.get_accidents(date_from=date_from)
        assert total >= 1

    async def test_update_two_step_refresh(self, db_session: AsyncSession) -> None:
        item = await _create_accident(db_session)
        repo = SafetyRepository(db_session)
        updated = await repo.update_accident(item.id, {"status": "investigating"})
        assert updated is not None
        assert updated.status == "investigating"


class TestDailyRiskReportRepository:
    async def test_report_date_filter(self, db_session: AsyncSession) -> None:
        repo = SafetyRepository(db_session)
        report = await repo.create_daily_risk_report(
            {
                "report_no": _uid("DRR"),
                "report_date": datetime.now(),
                "department": "EHS部",
                "operation_description": "受限空间作业测试",
                "status": "submitted",
            }
        )
        await db_session.flush()

        items, total = await repo.get_daily_risk_reports(report_date=report.report_date)
        assert total >= 1
        assert any(i.id == report.id for i in items)

        _, empty_total = await repo.get_daily_risk_reports(
            report_date=datetime.now() - timedelta(days=3650)
        )
        assert empty_total == 0


class TestOhHazardMonitorRepository:
    async def test_get_by_no_and_filters(self, db_session: AsyncSession) -> None:
        repo = SafetyRepository(db_session)
        monitor = await repo.create_hazard_monitor(
            {
                "monitor_no": _uid("OHM"),
                "workplace": "污水站",
                "detection_type": "commissioned",
            }
        )
        await db_session.flush()

        found = await repo.get_hazard_monitor_by_no(monitor.monitor_no)
        assert found is not None
        assert found.id == monitor.id

        items, total = await repo.get_hazard_monitors(detection_type="commissioned")
        assert total >= 1

        items, _ = await repo.get_hazard_monitors(keyword="污水")
        assert any(i.id == monitor.id for i in items)
