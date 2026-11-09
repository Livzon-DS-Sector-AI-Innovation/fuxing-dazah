"""P2-2 G3 —— 危险源辨识 Executor 协议收编（Task/Report 留痕）测试。

一条辨识记录=一个 Task（thread=bitable:hazard_id:<record_id> / hazard_id:<hid>），
每步脚本执行按 Report 语义落 stage_facts；驱动仍在原入口（行为等价由既有
辨识测试原样绿保证）。开关关=零 DB 写零行为变化。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.platform.superagent.models import AgentTask, AgentTaskSubscription

EXECUTOR_NAME = "hazard_id_script"


@pytest_asyncio.fixture(autouse=True)
async def _purge_trace_tasks():
    yield
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        tasks = (
            await s.execute(
                select(AgentTask).where(AgentTask.executor == EXECUTOR_NAME)
            )
        ).scalars().all()
        for t in tasks:
            await s.execute(
                AgentTaskSubscription.__table__.delete().where(
                    AgentTaskSubscription.task_id == t.id
                )
            )
            await s.delete(t)
        await s.commit()


def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED", "true")


def _off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED", raising=False)


async def _tasks(session: Any) -> list[AgentTask]:
    return (
        (
            await session.execute(
                select(AgentTask).where(AgentTask.executor == EXECUTOR_NAME)
            )
        )
        .scalars()
        .all()
    )


# ═══════════════════════════════════════════════════════════════
# report_step（纯单元，脱管 ORM 实例）
# ═══════════════════════════════════════════════════════════════


def _detached_task() -> AgentTask:
    return AgentTask(
        short_name="hazard_id:t", title="t", executor=EXECUTOR_NAME, mandate={},
    )


class TestReportStep:
    def test_waiting_report_shape(self):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        task = _detached_task()
        superagent_trace.report_step(
            task,
            kind="waiting",
            note="脚本2执行完成",
            attention={"question": "请人工审核脚本2输出"},
            script=2,
            flow="bitable",
        )
        facts = task.stage_facts or {}
        assert facts["latest_report"] == "waiting"
        assert facts["latest_report_at"]
        assert facts["attention_pending"] is True
        assert facts["last_attention"] == {"question": "请人工审核脚本2输出"}
        assert len(facts["reports"]) == 1
        entry = facts["reports"][0]
        assert entry["kind"] == "waiting"
        assert entry["script"] == 2
        assert entry["flow"] == "bitable"
        assert entry["attention"]

    def test_reports_accumulate_and_end_task(self):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        task = _detached_task()
        superagent_trace.report_step(task, kind="waiting", script=2)
        superagent_trace.report_step(
            task, kind="ready", note="全流程完成", end_task=True
        )
        assert len(task.stage_facts["reports"]) == 2
        assert task.stage_facts["latest_report"] == "ready"
        assert task.status == "ended"
        assert task.outcome == "ready"
        assert task.ended_at is not None

    def test_non_waiting_resets_attention_flag(self):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        task = _detached_task()
        superagent_trace.report_step(
            task, kind="waiting", attention={"q": 1}, script=1
        )
        superagent_trace.report_step(task, kind="failed", note="x", script=2)
        assert task.stage_facts["attention_pending"] is False


# ═══════════════════════════════════════════════════════════════
# record_script_run / record_flow_completed（Bitable 流，DB 级）
# ═══════════════════════════════════════════════════════════════


class TestRecordScriptRun:
    async def test_off_zero_write(self, db_session, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        _off(monkeypatch)
        ok = await superagent_trace.record_script_run(
            session=db_session, record_key="recB1", flow="bitable",
            script=2, ok=True,
        )
        assert ok is False
        assert await _tasks(db_session) == []

    async def test_success_creates_open_task_waiting(self, db_session, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        _on(monkeypatch)
        ok = await superagent_trace.record_script_run(
            session=db_session, record_key="recB1", flow="bitable",
            script=2, ok=True,
        )
        assert ok is True
        tasks = await _tasks(db_session)
        assert len(tasks) == 1
        task = tasks[0]
        assert task.executor == EXECUTOR_NAME
        assert task.status == "open"
        sub = (
            await db_session.execute(
                select(AgentTaskSubscription).where(
                    AgentTaskSubscription.task_id == task.id
                )
            )
        ).scalar_one()
        assert sub.thread_key == "bitable:hazard_id:recB1"
        assert task.stage_facts["latest_report"] == "waiting"
        assert task.stage_facts["reports"][-1]["script"] == 2
        # mandate 护栏：policy_version 键存在（未来底座开+Policy 换版不误投输入）
        assert "policy_version" in (task.mandate or {})

    async def test_failure_marks_failed(self, db_session, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        _on(monkeypatch)
        await superagent_trace.record_script_run(
            session=db_session, record_key="recB2", flow="bitable",
            script=3, ok=False, error="PluginError",
        )
        task = (await _tasks(db_session))[0]
        assert task.stage_facts["latest_report"] == "failed"
        assert task.stage_facts["reports"][-1]["note"] == "PluginError"

    async def test_completed_ends_task(self, db_session, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        _on(monkeypatch)
        await superagent_trace.record_script_run(
            session=db_session, record_key="recB3", flow="bitable",
            script=8, ok=True,
        )
        ended = await superagent_trace.record_flow_completed(
            session=db_session, record_key="recB3", flow="bitable",
        )
        assert ended is True
        task = (await _tasks(db_session))[0]
        assert task.status == "ended"
        assert task.outcome == "ready"

    async def test_same_record_reuses_task(self, db_session, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        _on(monkeypatch)
        for script in (1, 2):
            await superagent_trace.record_script_run(
                session=db_session, record_key="recB4", flow="bitable",
                script=script, ok=True,
            )
        tasks = await _tasks(db_session)
        assert len(tasks) == 1
        assert len(tasks[0].stage_facts["reports"]) == 2


# ═══════════════════════════════════════════════════════════════
# traced_run_script（Bitable 流 runner 包装）
# ═══════════════════════════════════════════════════════════════


class TestTracedRunner:
    async def test_output_traces_ok(self, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        calls: list[dict[str, Any]] = []

        async def fake_record(**kwargs: Any) -> bool:
            calls.append(kwargs)
            return True

        monkeypatch.setattr(superagent_trace, "record_script_run", fake_record)

        marker = object()

        async def base(script: Any, effective: dict[str, Any]) -> Any:
            return marker

        wrapped = superagent_trace.traced_run_script(
            record_id="recB9", runner=base
        )
        out = await wrapped(2, {"department": "一部"})
        assert out is marker  # 透传：不改 runner 行为
        assert len(calls) == 1
        assert calls[0]["record_key"] == "recB9"
        assert calls[0]["script"] == 2
        assert calls[0]["ok"] is True

    async def test_none_output_traces_failed(self, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        calls: list[dict[str, Any]] = []

        async def fake_record(**kwargs: Any) -> bool:
            calls.append(kwargs)
            return True

        monkeypatch.setattr(superagent_trace, "record_script_run", fake_record)

        async def base(script: Any, effective: dict[str, Any]) -> Any:
            return None

        wrapped = superagent_trace.traced_run_script(record_id="recB8", runner=base)
        out = await wrapped(5, {})
        assert out is None
        assert calls[0]["ok"] is False


# ═══════════════════════════════════════════════════════════════
# executor 注册与重放
# ═══════════════════════════════════════════════════════════════


class TestHazardIdExecutor:
    def _register(self):
        from app.modules.safety.ai_hazard_identification import superagent_trace

        superagent_trace.register_hazard_id_executor()

    def _exec(self):
        from app.platform.superagent.executors import get_executor

        registered = get_executor(EXECUTOR_NAME)
        assert registered is not None
        return registered[0]

    async def test_replay_bitable_advanced_waits_review(self, monkeypatch):
        self._register()
        from app.modules.safety.feishu import (
            hazard_identification_bitable_handler as handler,
        )

        async def fake_advance(record_id: str, **kwargs: Any) -> dict[str, Any]:
            return {"status": "advanced", "next_node": "待AI固有风险评价", "script": 3}

        monkeypatch.setattr(handler, "advance_bitable_record", fake_advance)
        report = await self._exec()(
            {"id": "t1", "short_name": "t", "title": "t", "mandate": {}},
            [{"action": "run_script", "flow": "bitable", "record_key": "recX",
              "script_no": 3}],
        )
        assert report.kind == "waiting"
        assert report.attention is not None

    async def test_replay_bitable_completed_ends(self, monkeypatch):
        self._register()
        from app.modules.safety.feishu import (
            hazard_identification_bitable_handler as handler,
        )

        async def fake_advance(record_id: str, **kwargs: Any) -> dict[str, Any]:
            return {"status": "noop", "reason": "completed"}

        monkeypatch.setattr(handler, "advance_bitable_record", fake_advance)
        report = await self._exec()(
            {"id": "t1", "short_name": "t", "title": "t", "mandate": {}},
            [{"action": "run_script", "flow": "bitable", "record_key": "recX",
              "script_no": 8}],
        )
        assert report.kind == "ready"
        assert report.end_task is True

    async def test_replay_bitable_noop_blocked(self, monkeypatch):
        self._register()
        from app.modules.safety.feishu import (
            hazard_identification_bitable_handler as handler,
        )

        async def fake_advance(record_id: str, **kwargs: Any) -> dict[str, Any]:
            return {"status": "noop", "reason": "precondition"}

        monkeypatch.setattr(handler, "advance_bitable_record", fake_advance)
        report = await self._exec()(
            {"id": "t1", "short_name": "t", "title": "t", "mandate": {}},
            [{"action": "run_script", "flow": "bitable", "record_key": "recX",
              "script_no": 2}],
        )
        assert report.kind == "blocked"

    async def test_replay_unknown_action_dropped(self):
        self._register()
        report = await self._exec()(
            {"id": "t1", "short_name": "t", "title": "t", "mandate": {}},
            [{"flow": "bitable", "record_key": "recX"}],
        )
        assert report.kind == "dropped"


# ═══════════════════════════════════════════════════════════════
# ORM 流挂点（service/safety.py run_script + review_script）
# ═══════════════════════════════════════════════════════════════


class _FakeRepo:
    def __init__(self, item: Any) -> None:
        self.item = item
        self.updates: list[dict[str, Any]] = []

    async def get_hazard_identification_by_id(self, hid: Any) -> Any:
        return self.item

    async def update_hazard_identification(
        self, hid: Any, data: dict[str, Any]
    ) -> dict[str, Any]:
        self.updates.append(dict(data))
        return data


def _orm_item(**overrides: Any) -> SimpleNamespace:
    kwargs: dict[str, Any] = dict(
        id=uuid4(),
        ai_node_progress="pending_script2",
        script1_review_status="approved",
        feishu_record_id=None,
    )
    kwargs.update(overrides)
    return SimpleNamespace(**kwargs)


class TestOrmWire:
    async def test_review_script_traces_approved(self, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace
        from app.modules.safety.service.safety import SafetyService

        calls: list[dict[str, Any]] = []

        async def fake_review_trace(**kwargs: Any) -> bool:
            calls.append(kwargs)
            return True

        monkeypatch.setattr(
            superagent_trace, "record_orm_review", fake_review_trace
        )

        item = _orm_item()
        svc = SafetyService(None)  # type: ignore[arg-type]
        svc.repo = _FakeRepo(item)  # type: ignore[assignment]
        result = await svc.review_script(item.id, 2, "approved")
        assert result is not None
        assert len(calls) == 1
        assert calls[0]["script_no"] == 2
        assert calls[0]["action"] == "approved"
        assert calls[0]["item"] is item

    async def test_review_script7_completed_flag(self, monkeypatch):
        from app.modules.safety.ai_hazard_identification import superagent_trace
        from app.modules.safety.service.safety import SafetyService

        calls: list[dict[str, Any]] = []

        async def fake_review_trace(**kwargs: Any) -> bool:
            calls.append(kwargs)
            return True

        monkeypatch.setattr(
            superagent_trace, "record_orm_review", fake_review_trace
        )

        item = _orm_item(
            ai_node_progress="pending_script7",
            script6_review_status="approved",
        )
        svc = SafetyService(None)  # type: ignore[arg-type]
        svc.repo = _FakeRepo(item)  # type: ignore[assignment]
        await svc.review_script(item.id, 7, "approved")
        assert calls[0]["completed"] is True

    async def _run_script_with_orchestrator(
        self, monkeypatch, plugin_result
    ) -> list[dict[str, Any]]:
        from app.modules.safety.ai_hazard_identification import (
            orchestrator as orch_mod,
        )
        from app.modules.safety.ai_hazard_identification import (
            superagent_trace,
        )
        from app.modules.safety.service.safety import SafetyService

        calls: list[dict[str, Any]] = []

        async def fake_run_trace(**kwargs: Any) -> bool:
            calls.append(kwargs)
            return True

        monkeypatch.setattr(
            superagent_trace, "record_orm_script_run", fake_run_trace
        )

        class _FakeAIService:
            async def close(self) -> None:
                pass

        class _FakeOrch:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def run_script(self, item: Any, n: int) -> Any:
                if isinstance(plugin_result, Exception):
                    raise plugin_result
                return plugin_result

        async def _fake_get_ai_service() -> Any:
            return _FakeAIService()

        monkeypatch.setattr(orch_mod, "HazardIdentificationOrchestrator", _FakeOrch)

        item = _orm_item()
        svc = SafetyService(None)  # type: ignore[arg-type]
        svc.repo = _FakeRepo(item)  # type: ignore[assignment]
        monkeypatch.setattr(svc, "_get_ai_service", _fake_get_ai_service)
        monkeypatch.setattr(svc, "_validate_prerequisites", lambda i, n: True)
        await svc.run_script(item.id, 2)
        return calls

    async def test_run_script_success_traces_ok(self, monkeypatch):
        calls = await self._run_script_with_orchestrator(monkeypatch, {"k": "v"})
        assert len(calls) == 1
        assert calls[0]["ok"] is True
        assert calls[0]["script_no"] == 2

    async def test_run_script_orchestrator_error_traces_failed(
        self, monkeypatch
    ):
        from app.modules.safety.ai_hazard_identification.orchestrator import (
            OrchestratorError,
        )

        calls = await self._run_script_with_orchestrator(
            monkeypatch, OrchestratorError("模型超时")
        )
        assert len(calls) == 1
        assert calls[0]["ok"] is False
        assert "模型超时" in calls[0]["error"]
