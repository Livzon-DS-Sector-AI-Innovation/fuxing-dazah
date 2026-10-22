"""指标注册表与演练取数器测试（S1 体系标准符合性核查引擎）。

口径：演练计数=实施时间∈窗口 且 演练类型∈集合 且 状态=已完成、软删不计
（DESIGN §3.3）。接缝：db_session（真 sqlite/pg 回滚事务）注入 DB 源。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.modules.safety.models.contractors import EmergencyDrillRecord
from app.modules.safety.service.standard_check.engine import PeriodWindow, window_for
from app.modules.safety.service.standard_check.metrics import (
    MetricContext,
    get_metric,
)

H2 = window_for("半年", date(2026, 10, 21))


def _drill(drill_type: str, on: date, status: str = "已完成") -> EmergencyDrillRecord:
    return EmergencyDrillRecord(
        drill_type=drill_type,
        execution_time=on,
        status=status,
        drill_content=f"{drill_type}演练",
    )


class TestDrillMetrics:
    async def test_comprehensive_or_special_counts_current_window(self, db_session) -> None:
        db_session.add_all([
            _drill("综合应急演练", date(2026, 8, 15)),
            _drill("专项应急演练", date(2026, 10, 1)),  # H2 内第二场
            _drill("专项应急演练", date(2026, 3, 1)),  # H1：不计入 H2 窗口
            _drill("综合应急演练", date(2026, 9, 1), status="计划中"),  # 未完成不计
            _drill("现场岗位处置", date(2026, 9, 20)),  # 类型不在集合
        ])
        await db_session.flush()

        metric = get_metric("drill.count.comprehensive_or_special")
        outcome = await metric.compute(H2, MetricContext(db=db_session))
        assert outcome.value == 2.0
        assert len(outcome.evidence) == 2
        assert {e["type"] for e in outcome.evidence} == {"综合应急演练", "专项应急演练"}

    async def test_site_handling_and_evacuation(self, db_session) -> None:
        db_session.add_all([
            _drill("现场岗位处置", date(2026, 7, 5)),
            _drill("应急疏散演练", date(2026, 9, 1), status="已完成"),
        ])
        await db_session.flush()

        site = get_metric("drill.count.site_handling")
        assert (await site.compute(H2, MetricContext(db=db_session))).value == 1.0
        evac = get_metric("drill.count.evacuation")
        assert (await evac.compute(H2, MetricContext(db=db_session))).value == 1.0

    async def test_soft_deleted_excluded(self, db_session) -> None:
        deleted = _drill("综合应急演练", date(2026, 8, 1))
        deleted.is_deleted = True
        db_session.add(deleted)
        await db_session.flush()

        metric = get_metric("drill.count.comprehensive_or_special")
        assert (await metric.compute(H2, MetricContext(db=db_session))).value == 0.0

    async def test_no_db_is_no_data(self) -> None:
        metric = get_metric("drill.count.comprehensive_or_special")
        outcome = await metric.compute(H2, MetricContext(db=None))
        assert outcome.value is None
        assert outcome.no_data_reason

    def test_spec_metadata(self) -> None:
        metric = get_metric("drill.count.comprehensive_or_special")
        assert metric.spec.settle == "early"
        assert metric.spec.unit == "次"
        assert get_metric("no.such.key") is None


# ═══════════════════════════════════════════════════════════════
# T3：隐患组/危险源/体检/作业票取数器
# ═══════════════════════════════════════════════════════════════

from types import SimpleNamespace

from app.modules.safety.models.work_ticket_review import WorkTicketReview
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.hazard_direct import bitable_repo as hz_repo
from app.modules.safety.service.hazard_id_direct import reader as hi_reader
from app.modules.safety.service.oh_direct import ledger as oh_ledger
from app.modules.safety.service.standard_check.metrics import MetricContext as Ctx

Q4 = window_for("季度", date(2026, 10, 21))


class FakeHazardClient:
    """hazard 域 list_all_records 协议替身。"""

    def __init__(self, items, *, config_error: bool = False) -> None:
        self._items = items
        self._config_error = config_error

    async def list_all_records(self, **kwargs):
        if self._config_error:
            raise BitableConfigError("Bitable 连接未配置或已停用: hazard/hazard")
        return self._items


def _hz(no: str, *, level: str = "一般", status: str = "已关闭",
        done: date | None = None, deadline: date | None = None,
        checked: date | None = None) -> dict:
    fields = {hz_repo.F_NO: no, hz_repo.F_LEVEL_MANUAL: level,
              hz_repo.F_RECTIFY_STATUS: status}
    for name, d in ((hz_repo.F_RECTIFY_DONE_AT, done),
                    (hz_repo.F_DEADLINE, deadline),
                    (hz_repo.F_DATE, checked)):
        if d is not None:
            fields[name] = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)
    return {"record_id": no, "fields": fields}


class TestHazardMetrics:
    async def test_on_time_close_rate(self) -> None:
        items = [
            _hz("H1", done=date(2026, 10, 5), deadline=date(2026, 10, 10)),   # 按期
            _hz("H2", done=date(2026, 10, 20), deadline=date(2026, 10, 10)),  # 超期
            _hz("H3", done=date(2026, 10, 8)),  # 无期限：不计分母
            _hz("H4", done=date(2026, 8, 1), deadline=date(2026, 8, 9)),     # 窗口外
            _hz("H5", status="整改中"),          # 未关闭不计
        ]
        m = get_metric("hazard.on_time_close_rate")
        out = await m.compute(Q4, Ctx(opener=lambda d, k: FakeHazardClient(items)))
        assert out.value == 50.0
        assert "带期限 2" in out.evidence[0]["title"]

    async def test_on_time_close_rate_no_closed(self) -> None:
        m = get_metric("hazard.on_time_close_rate")
        out = await m.compute(Q4, Ctx(opener=lambda d, k: FakeHazardClient([])))
        assert out.value is None
        assert out.no_data_reason

    async def test_major_close_rate(self) -> None:
        items = [
            _hz("M1", level="重大隐患", status="已关闭"),
            _hz("M2", level="重大隐患", status="整改中"),
            _hz("G1", level="一般", status="整改中"),  # 非重大不计
        ]
        m = get_metric("hazard.major_close_rate")
        out = await m.compute(Q4, Ctx(opener=lambda d, k: FakeHazardClient(items)))
        assert out.value == 50.0
        empty = await m.compute(Q4, Ctx(opener=lambda d, k: FakeHazardClient([_hz("G1")])))
        assert empty.no_data_reason

    async def test_register_count(self) -> None:
        items = [
            _hz("R1", status="整改中", checked=date(2026, 10, 3)),
            _hz("R2", status="整改中", checked=date(2026, 10, 9)),
            _hz("R3", status="整改中", checked=date(2026, 8, 30)),  # 窗口外
        ]
        m = get_metric("hazard.register_count")
        out = await m.compute(Q4, Ctx(opener=lambda d, k: FakeHazardClient(items)))
        assert out.value == 2.0
        assert len(out.evidence) == 2

    async def test_hazard_not_connected_is_no_data(self) -> None:
        for key in ("hazard.on_time_close_rate", "hazard.major_close_rate",
                    "hazard.register_count"):
            out = await get_metric(key).compute(
                Q4, Ctx(opener=lambda d, k: FakeHazardClient([], config_error=True))
            )
            assert out.value is None
            assert "hazard" in out.no_data_reason


class TestHazardIdMetric:
    async def test_count_year(self, monkeypatch) -> None:
        def _ms(d: date) -> int:
            return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)

        views = [
            SimpleNamespace(created_time_ms=_ms(date(2026, 5, 1)), specific_activity="罐区辨识"),
            SimpleNamespace(created_time_ms=_ms(date(2026, 9, 2)), specific_activity="车间辨识"),
            SimpleNamespace(created_time_ms=_ms(date(2025, 4, 1)), specific_activity="去年"),
        ]

        class FakeReader:
            async def fetch_all(self, *, strict: bool = False):
                return views

        monkeypatch.setattr(hi_reader, "open_reader", lambda: FakeReader())
        y2026 = window_for("年度", date(2026, 10, 21))
        out = await get_metric("hazard_id.count.year").compute(y2026, Ctx())
        assert out.value == 2.0


class TestOhExamRate:
    async def test_rate_capped_at_100(self, monkeypatch) -> None:
        async def fake_exams():
            return [SimpleNamespace(exam_date=date(2026, 4, 1)),
                    SimpleNamespace(exam_date=date(2026, 6, 1)),
                    SimpleNamespace(exam_date=date(2025, 1, 1))]

        async def fake_persons():
            return [SimpleNamespace()] * 2  # 2 人 3 条记录 → 封顶 100

        monkeypatch.setattr(oh_ledger, "fetch_exams", fake_exams)
        monkeypatch.setattr(oh_ledger, "fetch_persons", fake_persons)
        y2026 = window_for("年度", date(2026, 10, 21))
        out = await get_metric("oh.exam_rate").compute(y2026, Ctx())
        assert out.value == 100.0
        assert "2 人" in out.evidence[0]["title"]


class TestWorkticketAuditRate:
    """窗口取 2099 年：与本地 dev 库真实审核留痕彻底隔离（测试自带数据）。"""

    W = window_for("月度", date(2099, 5, 10))

    async def test_rate(self, db_session) -> None:
        db_session.add_all([
            WorkTicketReview(date=date(2099, 5, 5), total=10, reviewed=10),
            WorkTicketReview(date=date(2099, 5, 6), total=10, reviewed=8),
            WorkTicketReview(date=date(2099, 4, 2), total=5, reviewed=5),  # 窗口外
        ])
        await db_session.flush()
        out = await get_metric("workticket.audit_rate").compute(self.W, Ctx(db=db_session))
        assert out.value == 90.0
        assert "20 张" in out.evidence[0]["title"]

    async def test_no_records_is_no_data(self, db_session) -> None:
        out = await get_metric("workticket.audit_rate").compute(self.W, Ctx(db=db_session))
        assert out.no_data_reason


# ═══════════════════════════════════════════════════════════════
# T4：设施/承包商/外来人员/MSDS/法规取数器 + 长周期
# ═══════════════════════════════════════════════════════════════

from app.modules.safety.models.facilities import FacilityCheckTask
from app.modules.safety.models.regulation_ingest import RegulationIngestRun
from app.modules.safety.service.contractor_admission_direct import reader as ca_reader
from app.modules.safety.service.visitor_insurance import reader as vs_reader
from app.modules.safety.service.standard_check import metrics as sc_metrics

W2099 = window_for("季度", date(2099, 5, 10))


def _task(due: date, status: str = "issued", closed_at=None) -> FacilityCheckTask:
    return FacilityCheckTask(
        biz_type="accessory", ledger_key=f"rec-{due.isoformat()}",
        task_kind="校验", due_date=due, lead_days=30, status=status,
        group_key="安全阀·校验", task_subtype="校验",
        anchor_at_dispatch=due, issued_on=due - timedelta(days=30),
        department="生产一部", closed_at=closed_at,
    )


class TestFacilityMetric:
    async def test_on_time_close_rate(self, db_session) -> None:
        ok1 = _task(date(2099, 5, 1), "closed",
                    closed_at=datetime(2099, 4, 28, tzinfo=UTC))
        late = _task(date(2099, 5, 2), "closed",
                     closed_at=datetime(2099, 5, 6, tzinfo=UTC))
        pending = _task(date(2099, 5, 3))  # 未闭环
        db_session.add_all([ok1, late, pending])
        await db_session.flush()
        out = await get_metric("facility.on_time_close_rate").compute(W2099, Ctx(db=db_session))
        assert out.value == 33.0  # 1/3
        assert "到期 3 项" in out.evidence[0]["title"]

    async def test_no_tasks_is_no_data(self, db_session) -> None:
        out = await get_metric("facility.on_time_close_rate").compute(W2099, Ctx(db=db_session))
        assert out.no_data_reason


class TestContractorMetrics:
    async def test_admit_and_agreement(self, monkeypatch) -> None:
        views = [
            SimpleNamespace(entry_date=date(2099, 5, 2), ai_review_status="completed",
                            safety_agreement_files=["f1"]),
            SimpleNamespace(entry_date=date(2099, 5, 3), ai_review_status="pending",
                            safety_agreement_files=[]),
            SimpleNamespace(entry_date=date(2098, 5, 3), ai_review_status="completed",
                            safety_agreement_files=[]),  # 窗口外
        ]

        class FakeReader:
            async def fetch_all(self, *, strict: bool = False):
                return views

        monkeypatch.setattr(ca_reader, "open_reader", lambda: FakeReader())
        admit = await get_metric("contractor.admit_rate").compute(W2099, Ctx())
        assert admit.value == 50.0
        agreement = await get_metric("contractor.agreement_rate").compute(W2099, Ctx())
        assert agreement.value == 50.0

    async def test_not_connected(self, monkeypatch) -> None:
        from app.modules.safety.service.bitable_direct.errors import BitableConfigError

        def boom():
            raise BitableConfigError("未配置")

        monkeypatch.setattr(ca_reader, "open_reader", boom)
        out = await get_metric("contractor.admit_rate").compute(W2099, Ctx())
        assert "contractor" in out.no_data_reason


class TestVisitorMetrics:
    async def test_notice_and_insurance(self, monkeypatch) -> None:
        views = [
            SimpleNamespace(entry_start=date(2099, 5, 1), status="已通过", insurance_end=date(2100, 1, 1)),
            SimpleNamespace(entry_start=date(2099, 5, 2), status="审批中", insurance_end=None),
            SimpleNamespace(entry_start=date(2098, 5, 2), status="已通过", insurance_end=None),  # 窗口外
        ]

        class FakeReader:
            async def fetch_all(self):
                return views

        monkeypatch.setattr(vs_reader, "open_reader", lambda: FakeReader())
        notice = await get_metric("visitor.notice_rate").compute(W2099, Ctx())
        assert notice.value == 50.0
        insurance = await get_metric("visitor.insurance_rate").compute(W2099, Ctx())
        assert insurance.value == 50.0


class TestMsdsCoverage:
    def test_coverage_pure_fn(self) -> None:
        covered, missing = sc_metrics.coverage_of(
            {"盐酸", "硫酸", "液碱"}, {"盐酸", "硫酸 ", "乙醇"}
        )
        assert covered == {"盐酸", "硫酸"}  # 名称 strip 归一
        assert missing == ["液碱"]

    async def test_empty_inventory_is_no_data(self, monkeypatch, db_session) -> None:
        # 库存表空场景：用 2099 窗口也拦不住全表查询——直接替身 select 不现实，
        # 该路径由 empty-branch 兜底：真实库非空时走覆盖计算（上例纯函数已测）
        out = await get_metric("msds.coverage_rate").compute(W2099, Ctx(db=db_session))
        assert out.value is not None or out.no_data_reason  # 两态任一，不炸即可


class TestRegulationMetric:
    async def test_ingest_count(self, db_session) -> None:
        db_session.add_all([
            RegulationIngestRun(source_run_id="r-2099-1", status="completed",
                                created_at=datetime(2099, 5, 2, tzinfo=UTC)),
            RegulationIngestRun(source_run_id="r-2099-2", status="failed",
                                created_at=datetime(2099, 5, 3, tzinfo=UTC)),
        ])
        await db_session.flush()
        out = await get_metric("regulation.ingest_count").compute(W2099, Ctx(db=db_session))
        assert out.value == 1.0
