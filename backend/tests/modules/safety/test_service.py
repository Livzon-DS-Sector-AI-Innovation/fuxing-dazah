"""Safety module — service 层测试（安全检查/事故工作流/每日报备/职业危害监测 OEL）。

复用顶层 tests/conftest.py 的 db_session（真实库 + 回滚）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.schemas import (
    AccidentCreate,
    DailyRiskReportCreate,
    OhHazardMonitorCreate,
    SafetyCheckCreate,
)
from app.modules.safety.service import (
    DailyRiskReportService,
    OhHazardMonitorService,
    SafetyService,
)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestSafetyCheckService:
    async def test_create_and_workflow(self, db_session: AsyncSession) -> None:
        svc = SafetyService(db_session)
        item = await svc.create_check(
            SafetyCheckCreate(
                check_no=_uid("CHK"),
                check_date=datetime.now(),
            )
        )
        assert item.status == "draft"

        submitted = await svc.submit_check(item.id)
        assert submitted is not None and submitted.status == "submitted"

        # 已提交状态不能重复提交
        assert await svc.submit_check(item.id) is None

        reviewed = await svc.review_check(item.id, "qualified")
        assert reviewed is not None and reviewed.status == "reviewed"

        closed = await svc.close_check(item.id)
        assert closed is not None and closed.status == "closed"

    async def test_confirm_roles(self, db_session: AsyncSession) -> None:
        svc = SafetyService(db_session)
        item = await svc.create_check(
            SafetyCheckCreate(check_no=_uid("CHK"), check_date=datetime.now())
        )
        assert (await svc.confirm_check(item.id, "inspector")).inspector_confirmed is True
        assert (await svc.confirm_check(item.id, "safety_officer")).safety_officer_confirmed is True
        assert await svc.confirm_check(item.id, "unknown_role") is None


class TestAccidentService:
    async def test_full_capa_lifecycle(self, db_session: AsyncSession) -> None:
        svc = SafetyService(db_session)
        item = await svc.create_accident(
            AccidentCreate(
                accident_no=_uid("ACC"),
                accident_type="injury",
                happened_at=datetime.now(),
                description="中毒窒息事故测试",
                reported_at=datetime.now(),
            )
        )
        assert item.status == "reported"

        investigating = await svc.investigate_accident(item.id, None, "王五")
        assert investigating is not None and investigating.status == "investigating"

        investigated = await svc.resolve_accident(
            item.id,
            direct_cause="未佩戴呼吸器",
            root_cause="风险评估缺失",
            handling_measures="通风后进入",
            corrective_actions="修订作业规程",
        )
        assert investigated is not None and investigated.status == "investigated"

        capa = await svc.start_capa(
            item.id,
            datetime.now() + timedelta(days=14),
            "赵六",
        )
        assert capa is not None and capa.status == "capa_in_progress"

        closed = await svc.verify_capa(item.id, None, "审核人")
        assert closed is not None and closed.status == "closed"
        assert closed.corrective_action_status == "verified"

    async def test_state_transition_guard(self, db_session: AsyncSession) -> None:
        svc = SafetyService(db_session)
        item = await svc.create_accident(
            AccidentCreate(
                accident_no=_uid("ACC"),
                accident_type="near_miss",
                happened_at=datetime.now(),
                description="未遂事件测试",
                reported_at=datetime.now(),
            )
        )
        # reported 状态不允许直接 resolve / close
        assert await svc.resolve_accident(item.id, "a", "b", "c") is None
        assert await svc.close_accident(item.id) is None


class TestDailyRiskReportService:
    async def test_submit_approve_reject_workflow(self, db_session: AsyncSession) -> None:
        svc = DailyRiskReportService(db_session)
        item = await svc.create_report(
            DailyRiskReportCreate(
                report_no=_uid("DRR"),
                report_date=datetime.now(),
                operation_description="高处作业报备测试",
            )
        )
        assert item.status == "draft"

        submitted = await svc.submit_report(item.id)
        assert submitted is not None and submitted.status == "submitted"

        approved = await svc.approve_report(item.id)
        assert approved is not None and approved.status == "approved"
        assert approved.approved_at is not None

    async def test_reject_sets_reason(self, db_session: AsyncSession) -> None:
        svc = DailyRiskReportService(db_session)
        item = await svc.create_report(
            DailyRiskReportCreate(
                report_no=_uid("DRR"),
                report_date=datetime.now(),
                operation_description="动火作业报备测试",
            )
        )
        await svc.submit_report(item.id)
        rejected = await svc.reject_report(item.id, "措施不完整")
        assert rejected is not None and rejected.status == "rejected"
        assert rejected.rejection_reason == "措施不完整"

    async def test_workflow_guard(self, db_session: AsyncSession) -> None:
        svc = DailyRiskReportService(db_session)
        item = await svc.create_report(
            DailyRiskReportCreate(
                report_no=_uid("DRR"),
                report_date=datetime.now(),
                operation_description="draft 态不允许审批",
            )
        )
        assert await svc.approve_report(item.id) is None
        assert await svc.reject_report(item.id, "reason") is None


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
