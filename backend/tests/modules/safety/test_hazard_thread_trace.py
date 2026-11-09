"""P2-2 G1/G2 —— ①②⑤/P2-1 写回 Thread 留痕（writeback_trace）测试。

形态与 audit_trail 同构：开关关=零旁挂零行为；开=仅增 agent_triggers 留痕行
（thread_key=bitable:hazard:<record_id>，按记录聚合 ①②③⑤ 全历史的数据面）。
DB 级测试走 _test_session_factory + purge；钩子接线用 capture 桩不触 DB。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.safety.service.hazard_direct import writeback_trace
from app.platform.superagent.models import AgentSource, AgentTrigger
from tests.conftest import _test_session_factory


@pytest_asyncio.fixture(autouse=True)
async def _purge_trace_rows():
    yield
    from app.platform.superagent.models import (
        AgentTask,
        AgentTaskSubscription,
    )
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        rows = (
            await s.execute(
                select(AgentTrigger).where(
                    AgentTrigger.external_id.like("writeback:%")
                )
            )
        ).scalars().all()
        for r in rows:
            await s.delete(r)
        srcs = (
            await s.execute(
                select(AgentSource).where(
                    AgentSource.name == writeback_trace.TRACE_SOURCE_NAME
                )
            )
        ).scalars().all()
        for r in srcs:
            await s.delete(r)
        for task in (
            await s.execute(
                select(AgentTask).where(
                    AgentTask.short_name.like("hz-thread-test%")
                )
            )
        ).scalars().all():
            await s.execute(
                AgentTaskSubscription.__table__.delete().where(
                    AgentTaskSubscription.task_id == task.id
                )
            )
            await s.delete(task)
        await s.commit()


def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED", "true")


def _off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED", raising=False)


async def _rows(session: Any) -> list[AgentTrigger]:
    return (
        (
            await session.execute(
                select(AgentTrigger).where(
                    AgentTrigger.external_id.like("writeback:%")
                )
            )
        )
        .scalars()
        .all()
    )


# ═══════════════════════════════════════════════════════════════
# record_writeback 核心
# ═══════════════════════════════════════════════════════════════


class TestRecordWriteback:
    async def test_switch_off_zero_write(self, db_session, monkeypatch):
        _off(monkeypatch)
        ok = await writeback_trace.record_writeback(
            session=db_session,
            writer=writeback_trace.WRITER_AI_ANALYSIS,
            record_id="recT1",
            fields=["隐患分类（AI）"],
            applied=True,
        )
        assert ok is False
        assert await _rows(db_session) == []

    async def test_switch_on_stores_trigger_row(self, db_session, monkeypatch):
        _on(monkeypatch)
        ok = await writeback_trace.record_writeback(
            session=db_session,
            writer=writeback_trace.WRITER_AI_ANALYSIS,
            record_id="recT1",
            fields=["隐患分类（AI）", "隐患级别（AI）"],
            applied=True,
            hazard_no="YJ-2026-001",
        )
        assert ok is True
        rows = await _rows(db_session)
        assert len(rows) == 1
        row = rows[0]
        assert row.thread_key == "bitable:hazard:recT1"
        assert row.human is False
        assert row.actor == {"id": "ai_analysis", "type": "ai_pipeline"}
        assert row.payload["writer"] == "ai_analysis"
        assert row.payload["record_id"] == "recT1"
        assert row.payload["hazard_no"] == "YJ-2026-001"
        assert row.payload["fields"] == ["隐患分类（AI）", "隐患级别（AI）"]
        assert row.payload["channel"] == {"kind": "bitable", "record_id": "recT1"}
        steps = row.disposition or []
        assert any(s.get("step") == "stored" for s in steps)
        assert any(s.get("step") == "applied" for s in steps)

    async def test_failed_writeback_marks_failed(self, db_session, monkeypatch):
        _on(monkeypatch)
        ok = await writeback_trace.record_writeback(
            session=db_session,
            writer=writeback_trace.WRITER_AI_ANALYSIS,
            record_id="recT2",
            fields=["隐患分类（AI）"],
            applied=False,
            note="WriteConflictError",
        )
        assert ok is True
        row = (await _rows(db_session))[0]
        assert any(s.get("step") == "failed" for s in row.disposition or [])

    async def test_fields_dict_becomes_sorted_names(self, db_session, monkeypatch):
        _on(monkeypatch)
        await writeback_trace.record_writeback(
            session=db_session,
            writer=writeback_trace.WRITER_SCORING,
            record_id="recT3",
            fields={"评分结果": 12.0, "评分说明": "H｜说明"},
            applied=True,
        )
        row = (await _rows(db_session))[0]
        assert row.payload["fields"] == ["评分结果", "评分说明"]

    async def test_each_call_is_distinct_event(self, db_session, monkeypatch):
        _on(monkeypatch)
        for _ in range(2):
            await writeback_trace.record_writeback(
                session=db_session,
                writer=writeback_trace.WRITER_REVIEW,
                record_id="recT4",
                fields=["AI初审结果"],
                applied=True,
            )
        assert len(await _rows(db_session)) == 2

    async def test_same_draft_replay_is_duplicate_no_new_row(
        self, db_session, monkeypatch
    ):
        """幂等兜底：同 (source_id, external_id) 重放 → duplicate 不新增行。"""
        _on(monkeypatch)

        async def _one() -> bool:
            return await writeback_trace.record_writeback(
                session=db_session,
                writer=writeback_trace.WRITER_AI_ANALYSIS,
                record_id="recT6",
                fields=["隐患分类（AI）"],
                applied=True,
            )

        assert await _one() is True
        rows_first = await _rows(db_session)
        assert len(rows_first) == 1
        # 直接复用同 draft 的 external_id 重放（模拟水位重扫/断线重推）
        from app.platform.superagent.ingest import ingest_draft
        from app.platform.superagent.sources import TriggerDraft

        source_row = (
            await db_session.execute(
                select(AgentSource).where(
                    AgentSource.name == writeback_trace.TRACE_SOURCE_NAME
                )
            )
        ).scalar_one()
        replay = TriggerDraft(
            external_id=rows_first[0].external_id,
            thread_key=rows_first[0].thread_key,
            actor={"id": "ai_analysis", "type": "ai_pipeline"},
            human=False,
            addressed=False,
            payload={"record_id": "recT6"},
        )
        outcome, trigger = await ingest_draft(db_session, source_row, replay)
        assert outcome == "duplicate"
        assert trigger.id == rows_first[0].id
        assert len(await _rows(db_session)) == 1

    async def test_self_managed_session_persists(self, monkeypatch):
        """P0 回归钉：session=None 自管短会话路径必须真落库（曾漏 commit）。"""
        _on(monkeypatch)
        # autouse 桩把 async_session_factory 换成 Noop：本用例恢复真实工厂
        import app.core.database as core_db

        monkeypatch.setattr(core_db, "async_session_factory", _test_session_factory)
        ok = await writeback_trace.record_writeback(
            writer=writeback_trace.WRITER_AI_ANALYSIS,
            record_id="recT7",
            fields=["隐患分类（AI）"],
            applied=True,
        )
        assert ok is True
        async with _test_session_factory() as s:
            rows = (
                await s.execute(
                    select(AgentTrigger).where(
                        AgentTrigger.external_id.like("writeback:%")
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].thread_key == "bitable:hazard:recT7"

    async def test_trace_failure_never_raises(self, db_session, monkeypatch):
        """留痕链路自身异常必须吞掉（绝不拖垮业务写回）。"""
        _on(monkeypatch)

        class _BoomSession:
            async def execute(self, *a, **k):
                raise ConnectionError("db down")

        ok = await writeback_trace.record_writeback(
            session=_BoomSession(),
            writer=writeback_trace.WRITER_AI_ANALYSIS,
            record_id="recT5",
            fields=["隐患分类（AI）"],
            applied=True,
        )
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# 钩子接线（capture 桩，不触 DB）
# ═══════════════════════════════════════════════════════════════


class _Capture:
    """record_writeback 捕获桩：记录调用并返回成功。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> bool:
        self.calls.append(kwargs)
        return True


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    monkeypatch.setattr(writeback_trace, "record_writeback", cap)
    return cap


class _FakeBClient:
    """Bitable 客户端假件：get_record/update_record 可编程。"""

    def __init__(
        self,
        *,
        current: dict[str, Any] | None = None,
        write_ok: bool = True,
    ) -> None:
        self.current = current
        self.write_ok = write_ok
        self.update_calls: list[tuple[str, dict[str, Any]]] = []

    async def get_record(self, record_id: str) -> dict[str, Any]:
        return dict(self.current or {})

    async def update_record(self, record_id: str, fields: dict[str, Any]) -> bool:
        self.update_calls.append((record_id, dict(fields)))
        return self.write_ok


class TestAiAnalysisHook:
    """①主链 write_ai_analysis 钩子：成功→applied；CAS 冲突→failed+re-raise。"""

    async def test_success_traces_applied(self, capture: _Capture):
        from app.modules.safety.service.hazard_direct import bitable_repo

        client = _FakeBClient()
        ok = await bitable_repo.write_ai_analysis(
            client,
            "recH1",
            hazard_no="YJ-2026-001",
            output={"hazard_type": "设备缺陷", "key_defect": "防护栏缺失"},
        )
        assert ok is True
        assert len(capture.calls) == 1
        call = capture.calls[0]
        assert call["writer"] == writeback_trace.WRITER_AI_ANALYSIS
        assert call["record_id"] == "recH1"
        assert call["applied"] is True
        assert call["hazard_no"] == "YJ-2026-001"
        assert "隐患分类（AI）" in call["fields"]
        assert "隐患描述（AI）" in call["fields"]

    async def test_cas_conflict_traces_failed_and_reraises(
        self, capture: _Capture
    ):
        from app.modules.safety.service.hazard_direct import bitable_repo
        from app.modules.safety.service.hazard_direct.bitable_repo import (
            WriteConflictError,
        )

        client = _FakeBClient(
            current={"隐患描述（AI）": "已被人工改写"}
        )
        with pytest.raises(WriteConflictError):
            await bitable_repo.write_ai_analysis(
                client,
                "recH2",
                hazard_no=None,
                output={"key_defect": "防护栏缺失"},
                snapshot_fields={"隐患描述（AI）": ""},
            )
        assert len(capture.calls) == 1
        assert capture.calls[0]["applied"] is False
        assert capture.calls[0]["record_id"] == "recH2"

    async def test_nothing_to_write_no_trace(self, capture: _Capture):
        from app.modules.safety.service.hazard_direct import bitable_repo

        ok = await bitable_repo.write_ai_analysis(
            _FakeBClient(), "recH3", hazard_no=None, output={}
        )
        assert ok is False
        assert capture.calls == []


class _ExFakeReader:
    def __init__(self, fields: dict[str, Any] | None = None) -> None:
        self.fields = fields or {}

    async def get_fields(self, record_id: str) -> dict[str, Any] | None:
        return self.fields.get(record_id)

    async def defect_images(self, record_id: str) -> list[str]:
        return []


class _ExFakeWriter:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok

    async def update_record(self, record_id: str, fields: dict[str, Any]) -> bool:
        return self.ok


class _NoopAuditFactory:
    """审计会话桩：记录调用、绝不触真实 DB（防测试真写 dev 库）。"""

    def __call__(self) -> _NoopAuditFactory:
        return self

    async def __aenter__(self) -> _NoopAuditFactory:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def add(self, row: object) -> None:
        pass

    async def commit(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _stub_audit_session(monkeypatch: pytest.MonkeyPatch) -> _NoopAuditFactory:
    import app.core.database as core_db

    factory = _NoopAuditFactory()
    monkeypatch.setattr(core_db, "async_session_factory", factory)
    return factory


def _ex_report(**overrides: Any):
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        EvidenceSnippet,
        ExceptionReviewReport,
        ProposedAction,
        ReviewConclusion,
        ReviewSource,
    )

    kwargs: dict[str, Any] = dict(
        record_id="recW1",
        exception_label="basis_missing",
        review_source=ReviewSource.DEAD_LETTER,
        evidence=[
            EvidenceSnippet(
                doc_name="消防法",
                source_article="第10条",
                quote="应设置防护栏杆。",
                chunk_id="chunk-1",
            )
        ],
        ai_conclusion=ReviewConclusion(
            classification="unsafe_condition",
            hazard_level="general",
            major_hazard_basis="《消防法》第10条：'应设置防护栏杆'",
            rectification_suggestion="补装防护栏杆",
        ),
        proposed_action=ProposedAction.ADOPT_AI,
        rescued=True,
        observed_at=datetime(2026, 11, 9, 8, 0),
        ai_snapshot={
            "隐患级别（AI）": None,
            "隐患分类（AI）": None,
            "隐患类别（AI）": None,
            "隐患描述（AI）": None,
            "隐患判定依据（AI）": None,
            "整改建议（AI）": None,
        },
    )
    kwargs.update(overrides)
    return ExceptionReviewReport(**kwargs)


class TestExceptionWritebackHook:
    """P2-1 execute_writeback 终态钩子：success→applied；冲突/失败→failed；

    gate_blocked=判据性拦截零写入→零留痕。
    """

    async def _run(self, report, *, reader=None, writer=None):
        from app.modules.safety.service.hazard_direct.exception_writeback import (
            WritebackDeps,
            execute_writeback,
        )
        from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis

        return await execute_writeback(
            report,
            deps=WritebackDeps(
                reader=reader or _ExFakeReader({"recW1": {}}),
                writer=writer or _ExFakeWriter(),
                redis=FakeRedis(),
            ),
        )

    async def test_success_traces_applied(self, capture: _Capture):
        outcome = await self._run(_ex_report())
        assert outcome.status == "success"
        assert len(capture.calls) == 1
        call = capture.calls[0]
        assert call["writer"] == writeback_trace.WRITER_EXCEPTION_REVIEW
        assert call["record_id"] == "recW1"
        assert call["applied"] is True

    async def test_gate_blocked_no_trace(self, capture: _Capture):
        from app.modules.safety.service.hazard_direct.exception_reviewer import (
            ReviewConclusion,
        )

        report = _ex_report(
            ai_conclusion=ReviewConclusion(
                classification="unsafe_condition",
                hazard_level="general",
                major_hazard_basis="",
                rectification_suggestion="补装防护栏杆",
            )
        )
        outcome = await self._run(report)
        assert outcome.status == "gate_blocked"
        assert capture.calls == []

    async def test_cas_conflict_traces_failed(self, capture: _Capture):
        reader = _ExFakeReader(
            {"recW1": {"隐患级别（AI）": "重大隐患"}}
        )
        outcome = await self._run(_ex_report(), reader=reader)
        assert outcome.status == "cas_conflict"
        assert len(capture.calls) == 1
        assert capture.calls[0]["applied"] is False


class TestReviewScoringHooks:
    """②write_review / ⑤write_scoring 钩子（C2）。"""

    async def test_review_success_traces_applied(self, capture: _Capture):
        from app.modules.safety.service.hazard_direct import bitable_repo

        ok = await bitable_repo.write_review(
            _FakeBClient(), "recR1", conclusion="已通过", summary="复核说明"
        )
        assert ok is True
        assert len(capture.calls) == 1
        call = capture.calls[0]
        assert call["writer"] == writeback_trace.WRITER_REVIEW
        assert call["record_id"] == "recR1"
        assert call["applied"] is True
        assert call["fields"] == ["AI初审结果", "AI初审说明"]

    async def test_review_write_failed_traces_failed(self, capture: _Capture):
        from app.modules.safety.service.hazard_direct import bitable_repo

        ok = await bitable_repo.write_review(
            _FakeBClient(write_ok=False), "recR2", conclusion="已通过", summary="x"
        )
        assert ok is False
        assert capture.calls[0]["applied"] is False

    async def test_scoring_success_traces_applied(self, capture: _Capture):
        from app.modules.safety.service.hazard_direct import bitable_repo

        ok = await bitable_repo.write_scoring(
            _FakeBClient(), "recS1", total=12.34, note="H｜低风险｜说明"
        )
        assert ok is True
        assert capture.calls[0]["writer"] == writeback_trace.WRITER_SCORING
        assert capture.calls[0]["applied"] is True
        assert capture.calls[0]["fields"] == ["评分结果", "评分说明"]

    async def test_scoring_cas_conflict_traces_failed(self, capture: _Capture):
        from app.modules.safety.service.hazard_direct import bitable_repo
        from app.modules.safety.service.hazard_direct.bitable_repo import (
            WriteConflictError,
        )

        client = _FakeBClient(current={"评分结果": 9.9})
        with pytest.raises(WriteConflictError):
            await bitable_repo.write_scoring(
                client,
                "recS2",
                total=42.0,
                note="M｜说明",
                snapshot_fields={"评分结果": ""},
            )
        assert capture.calls[0]["applied"] is False


# ═══════════════════════════════════════════════════════════════
# REST 查询端点（C2：thread_key 过滤 + history 聚合）
# ═══════════════════════════════════════════════════════════════


class TestThreadEndpoints:
    async def test_triggers_thread_key_filter(self, client, db_session, monkeypatch):
        _on(monkeypatch)
        await writeback_trace.record_writeback(
            session=db_session,
            writer=writeback_trace.WRITER_AI_ANALYSIS,
            record_id="recE1",
            fields=["隐患分类（AI）"],
            applied=True,
        )
        await writeback_trace.record_writeback(
            session=db_session,
            writer=writeback_trace.WRITER_REVIEW,
            record_id="recE2",
            fields=["AI初审结果"],
            applied=True,
        )
        await db_session.commit()  # client 与 db_session 跨连接，须 commit

        resp = await client.get(
            "/api/v1/platform/superagent/triggers",
            params={"thread_key": "bitable:hazard:recE1"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["thread_key"] == "bitable:hazard:recE1"
        assert data[0]["payload"]["writer"] == "ai_analysis"

    async def test_thread_history_aggregates(self, client, db_session, monkeypatch):
        from app.platform.superagent.models import (
            AgentTask,
            AgentTaskSubscription,
        )

        _on(monkeypatch)
        await writeback_trace.record_writeback(
            session=db_session,
            writer=writeback_trace.WRITER_AI_ANALYSIS,
            record_id="recE1",
            fields=["隐患分类（AI）"],
            applied=True,
        )
        task = AgentTask(
            short_name="hz-thread-test:recE1",
            title="危险源辨识 recE1",
            executor="hazard_id_script",
            mandate={"policy_version": "seed"},
            stage_facts={
                "latest_report": "waiting",
                "reports": [{"kind": "waiting", "script": 2}],
            },
        )
        db_session.add(task)
        await db_session.flush()
        db_session.add(
            AgentTaskSubscription(
                task_id=task.id, thread_key="bitable:hazard:recE1"
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/v1/platform/superagent/threads/bitable:hazard:recE1/history"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["thread"]["thread_key"] == "bitable:hazard:recE1"
        assert len(data["triggers"]) == 1
        assert data["triggers"][0]["payload"]["writer"] == "ai_analysis"
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["executor"] == "hazard_id_script"
        assert data["tasks"][0]["stage_facts"]["latest_report"] == "waiting"

    async def test_thread_history_unknown_404(self, client):
        resp = await client.get(
            "/api/v1/platform/superagent/threads/bitable:hazard:nope/history"
        )
        assert resp.status_code == 404

