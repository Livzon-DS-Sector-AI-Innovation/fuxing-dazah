"""Safety module — repository 层测试（安全检查/事故/每日报备/职业危害监测）。

复用顶层 tests/conftest.py 的 db_session（真实库 + 回滚）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
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
