"""Safety module — service 层测试（安全检查/事故工作流/每日报备/职业危害监测 OEL）。

复用顶层 tests/conftest.py 的 db_session（真实库 + 回滚）。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.schemas import (
    OhHazardMonitorCreate,
)
from app.modules.safety.service import (
    OhHazardMonitorService,
)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestOhHazardMonitorService:
    async def test_oel_compliance_auto_calculation(self, db_session: AsyncSession) -> None:
        svc = OhHazardMonitorService(db_session)
        item = await svc.create_monitor(
            OhHazardMonitorCreate(
                monitor_no=_uid("OHM"),
                workplace="车间一",
                detection_type="regular",
                detection_results=[
                    {"factor_name": "噪声", "detection_value": 90, "unit": "dB(A)", "oel_limit": 85},
                    {"factor_name": "CO", "detection_value": 24, "unit": "mg/m³", "oel_limit": 30},
                    {"factor_name": "照度", "detection_value": 0, "unit": "lx", "oel_limit": 0},
                ],
            )
        )
        started = await svc.start_monitoring(item.id)
        assert started is not None and started.status == "in_progress"

        completed = await svc.complete_monitoring(item.id)
        assert completed is not None and completed.status == "completed"
        results = {r["factor_name"]: r for r in completed.detection_results}
        # 90/85 > 1.0 → exceeding；24/30 = 0.8 → marginal；无限值 → compliant
        assert results["噪声"]["compliance_status"] == "exceeding"
        assert results["CO"]["compliance_status"] == "marginal"
        assert results["照度"]["compliance_status"] == "compliant"
        # 超标自动生成异常处置记录
        assert len(completed.abnormality_records) == 1
        assert "噪声" in completed.abnormality_records[0]["abnormality_desc"]

    async def test_verify_and_guard(self, db_session: AsyncSession) -> None:
        svc = OhHazardMonitorService(db_session)
        item = await svc.create_monitor(
            OhHazardMonitorCreate(monitor_no=_uid("OHM"), workplace="车间二", detection_type="regular")
        )
        # draft 态不允许验证
        assert await svc.verify_monitoring(item.id, "李四", "备注") is None

        await svc.start_monitoring(item.id)
        await svc.complete_monitoring(item.id)
        verified = await svc.verify_monitoring(item.id, "李四", "同意归档")
        assert verified is not None and verified.status == "verified"
        assert verified.verifier_name == "李四"
        assert "同意归档" in (verified.notes or "")
