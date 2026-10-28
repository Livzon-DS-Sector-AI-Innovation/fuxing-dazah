"""Agent 执行面三期（agent-action-p3）遥测报警处置两件测试。

覆盖 spec（.scratch/agent-action-p3/spec.md）T2：
ack_telemetry_alarm（值班确认，批量/按设备圈定，链路未启用降级）/
resolve_telemetry_alarm（处置关闭，说明必填，须先 acked）。

测试接缝（与 test_agent_action_p2_hazard/special_drill 一致）：
工具函数边界直接调用，FakeSession 按调用序返回预设结果
（list_alarms：count→rows 两次 execute；get_alarm：db.get），
确认流三路径照二期打桩模式（本批代表①）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    ROLE_CREATOR,
    ROLE_MANAGER,
    ROLE_VIEWER,
    check,
)
from app.modules.safety.business_agent.tools import registry
from app.modules.safety.business_agent.tools.telemetry_action_tools import (
    ack_telemetry_alarm,
    resolve_telemetry_alarm,
)


# ── 打桩基建（照 test_agent_action_p2_special_drill.FakeSession）──


class _FakeResult:
    def __init__(self, *, scalar_val=None, scalars_all=None) -> None:
        self._scalar_val = scalar_val
        self._scalars_all = scalars_all or []

    def scalar(self):
        return self._scalar_val

    def scalars(self):
        return self

    def all(self):
        return list(self._scalars_all)


class FakeSession:
    """依次返回预设 execute 结果；db.get 按 (model, pk) 查 _get_map。"""

    def __init__(self, results: list[_FakeResult] | None = None) -> None:
        self._results = list(results or [])
        self.statements: list[Any] = []
        self.commits = 0
        self._get_map: dict[tuple[type, Any], Any] = {}
        self.flushes = 0

    async def get(self, model: type, pk: Any) -> Any:
        return self._get_map.get((model, pk))

    async def execute(self, stmt: Any) -> _FakeResult:
        self.statements.append(stmt)
        return self._results.pop(0)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1


def _alarm(alarm_id: uuid.UUID, status: str = "firing", **kw: Any) -> SimpleNamespace:
    base = {
        "id": alarm_id,
        "equipment_no": "GL-01",
        "metric": "steam_pressure",
        "value": 1.2,
        "recorded_at": None,
        "created_at": None,
        "rule_desc": "蒸汽压力超上限",
        "level": "high",
        "status": status,
        "acked_at": None,
        "acked_by": None,
        "resolved_at": None,
        "resolution_note": None,
    }
    base.update(kw)
    obj = SimpleNamespace(**base)
    obj.is_deleted = False
    return obj


def _ctx(db: FakeSession, role: str = "creator", person: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(db=db, person=person, role=role, session_id="s1", channel="test")
    )


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _enable_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩采集链路为已启用（默认关，测试默认开）。"""
    monkeypatch.setattr(
        "app.modules.safety.telemetry.collector.poll_enabled", lambda: True
    )
    monkeypatch.setattr(
        "app.modules.safety.telemetry.source.source_chat_id",
        lambda: "oc_test_source",
    )


# ═══ 接线：TOOL_KIND / 组挂载 / 权限 ═══


class TestTelemetryActionWiring:
    def test_tool_kind_write(self) -> None:
        assert registry.TOOL_KIND["ack_telemetry_alarm"] is True
        assert registry.TOOL_KIND["resolve_telemetry_alarm"] is True

    def test_group_mounted(self) -> None:
        group = tool_selector.TOOL_GROUPS["telemetry"]
        assert "ack_telemetry_alarm" in group
        assert "resolve_telemetry_alarm" in group

    @pytest.mark.parametrize(
        "message",
        [
            "锅炉 GL-01 的报警帮我确认一下",
            "把销警处理一下",
            "这条报警处置关闭掉",
        ],
    )
    def test_route_hits_telemetry(self, message: str) -> None:
        decision = tool_selector.route_message(message)
        assert "ack_telemetry_alarm" in decision.tool_names or (
            "resolve_telemetry_alarm" in decision.tool_names
        ), f"{message} 未命中遥测处置挂载: {decision}"

    def test_permissions_admin_leader_only(self) -> None:
        for tool in ("ack_telemetry_alarm", "resolve_telemetry_alarm"):
            assert check(ROLE_CREATOR, tool)
            assert check(ROLE_MANAGER, tool)
            assert not check(ROLE_VIEWER, tool)


# ═══ ack_telemetry_alarm ═══


class TestAckTelemetryAlarm:
    def test_disabled_when_poll_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.modules.safety.telemetry.collector.poll_enabled", lambda: False
        )
        db = FakeSession()
        out = _run(ack_telemetry_alarm(_ctx(db), equipment_no="GL-01"))
        assert out["success"] is False
        assert "未启用" in out["message"]
        assert db.statements == []  # 降级不触库

    def test_disabled_when_source_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.modules.safety.telemetry.collector.poll_enabled", lambda: True
        )
        monkeypatch.setattr(
            "app.modules.safety.telemetry.source.source_chat_id", lambda: ""
        )
        db = FakeSession()
        out = _run(resolve_telemetry_alarm(_ctx(db), "any-id", note="已处置"))
        assert out["success"] is False
        assert "未启用" in out["message"]
        assert db.statements == []

    def test_disabled_matrix_ack_and_resolve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """降级判定 2×2 满配：两工具 ×（开关关/源群空）都返回说明不触库。"""
        for poll, src in ((False, "oc_x"), (True, "")):
            monkeypatch.setattr(
                "app.modules.safety.telemetry.collector.poll_enabled", lambda p=poll: p
            )
            monkeypatch.setattr(
                "app.modules.safety.telemetry.source.source_chat_id",
                lambda s=src: s,
            )
            db1, db2 = FakeSession(), FakeSession()
            out1 = _run(ack_telemetry_alarm(_ctx(db1), equipment_no="GL-01"))
            out2 = _run(resolve_telemetry_alarm(_ctx(db2), "any", note="x"))
            assert out1["success"] is False and "未启用" in out1["message"]
            assert out2["success"] is False and "未启用" in out2["message"]
            assert db1.statements == [] and db2.statements == []

    def test_no_args_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_link(monkeypatch)
        out = _run(ack_telemetry_alarm(_ctx(FakeSession())))
        assert out["success"] is False
        assert "alarm_ids" in out["message"] and "equipment_no" in out["message"]

    def test_ack_by_equipment_no_batches_firing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_link(monkeypatch)
        a1 = _alarm(uuid.uuid4())
        a2 = _alarm(uuid.uuid4())
        # list_alarms 调用序：count → rows
        db = FakeSession([_FakeResult(scalar_val=2), _FakeResult(scalars_all=[a1, a2])])
        person = SimpleNamespace(name="张安全", user_id="u1", open_id="ou1")
        out = _run(ack_telemetry_alarm(_ctx(db, person=person), equipment_no="GL-01"))
        assert out["success"] is True
        assert out["acked"] == 2 and out["skipped"] == 0 and out["missing"] == 0
        assert a1.status == "acked" and a2.status == "acked"
        assert a1.acked_by == "张安全"
        assert db.commits >= 1

    def test_ack_by_ids_mixed_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_link(monkeypatch)
        from app.modules.safety.models import TelemetryAlarmRecord

        ok = _alarm(uuid.uuid4(), status="firing")
        already = _alarm(uuid.uuid4(), status="acked")
        bad_id = "not-an-uuid"
        missing_id = uuid.uuid4()
        db = FakeSession()
        db._get_map[(TelemetryAlarmRecord, ok.id)] = ok
        db._get_map[(TelemetryAlarmRecord, already.id)] = already
        # missing_id 不入 map → get None
        out = _run(
            ack_telemetry_alarm(
                _ctx(db), alarm_ids=[str(ok.id), str(already.id), bad_id, str(missing_id)]
            )
        )
        assert out["success"] is True
        assert out["acked"] == 1
        assert out["skipped"] == 1  # 已 acked：状态机拒绝，幂等跳过
        assert out["missing"] == 2  # 非法 UUID + 不存在
        assert already.status == "acked"  # 未被改动


# ═══ resolve_telemetry_alarm ═══


class TestResolveTelemetryAlarm:
    def test_note_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_link(monkeypatch)
        out = _run(resolve_telemetry_alarm(_ctx(FakeSession()), "x", note="  "))
        assert out["success"] is False
        assert "处置说明必填" in out["message"]

    def test_resolve_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_link(monkeypatch)
        from app.modules.safety.models import TelemetryAlarmRecord

        a = _alarm(uuid.uuid4(), status="acked")
        db = FakeSession()
        db._get_map[(TelemetryAlarmRecord, a.id)] = a
        out = _run(
            resolve_telemetry_alarm(_ctx(db), str(a.id), note="已停炉检修，压力恢复正常")
        )
        assert out["success"] is True
        assert a.status == "resolved"
        assert a.resolution_note == "已停炉检修，压力恢复正常"
        assert out["item"]["status"] == "resolved"
        assert db.commits >= 1

    def test_requires_acked_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_link(monkeypatch)
        from app.modules.safety.models import TelemetryAlarmRecord

        a = _alarm(uuid.uuid4(), status="firing")
        db = FakeSession()
        db._get_map[(TelemetryAlarmRecord, a.id)] = a
        out = _run(resolve_telemetry_alarm(_ctx(db), str(a.id), note="处置了"))
        assert out["success"] is False
        assert "须先值班确认" in out["message"]
        assert a.status == "firing"

    def test_alarm_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_link(monkeypatch)
        out = _run(
            resolve_telemetry_alarm(
                _ctx(FakeSession()), str(uuid.uuid4()), note="处置了"
            )
        )
        assert out["success"] is False
        assert "不存在" in out["message"]


# ═══ 确认流三路径（本批代表①）═══


class TestAckConfirmationFlow:
    def _history_raw(self) -> list[dict]:
        from pydantic_ai.messages import (
            ModelMessagesTypeAdapter,
            ModelRequest,
            UserPromptPart,
        )

        base = json.loads(
            ModelMessagesTypeAdapter.dump_json(
                [ModelRequest(parts=[UserPromptPart(content="锅炉 GL-01 的报警帮我确认一下")])]
            )
        )
        from app.modules.safety.business_agent import executor
        from app.modules.safety.business_agent.schemas import PendingActionData

        pending = PendingActionData(
            tool_name="ack_telemetry_alarm",
            arguments={"equipment_no": "GL-01"},
            summary="值班确认 GL-01 firing 报警 ack_telemetry_alarm",
        )
        return executor._append_delegated_tool_call(base, pending)

    def _install_stubs(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        from app.modules.safety.business_agent import executor

        captured: dict = {}

        class _FakeDb:
            async def execute(self, stmt: Any) -> Any:
                return SimpleNamespace(scalar_one=lambda: 0)

            async def flush(self) -> None:
                return None

            def add(self, obj: Any) -> None:
                return None

        async def fake_agent_run(user_message, deps, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output="已确认报警", all_messages=lambda: [],
                new_messages=lambda: [],
            )

        async def fake_events(deps, result):
            return None

        async def fake_audit(*args, **kwargs):
            return None

        monkeypatch.setattr(executor, "_agent_run", fake_agent_run)
        monkeypatch.setattr(executor, "_record_tool_events", fake_events)
        monkeypatch.setattr(executor, "_audit_agent_resume", fake_audit)
        return captured

    def _resume(self, monkeypatch: pytest.MonkeyPatch, role: str, approved: bool) -> Any:
        from app.modules.safety.business_agent import executor
        from app.modules.safety.business_agent.schemas import SafetyDeps

        captured = self._install_stubs(monkeypatch)
        sid = "11111111-2222-3333-4444-555555555555"
        deps = SafetyDeps(
            db=SimpleNamespace(), person=None, role=role,
            session_id=sid, channel="test",
        )
        out = _run(executor.resume(
            sid, deps, action_id="action-1", approved=approved,
            message_history_raw=self._history_raw(),
        ))
        return out, captured

    def test_approved_grants_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out, captured = self._resume(monkeypatch, role="creator", approved=True)
        assert out["executed"] is True
        assert captured["resume_tool_names"] == ["ack_telemetry_alarm"]
        results = captured["deferred_tool_results"]
        assert list(results.approvals.values()) == [True]

    def test_cancelled_denies_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic_ai.tools import ToolDenied

        out, captured = self._resume(monkeypatch, role="creator", approved=False)
        value = list(captured["deferred_tool_results"].approvals.values())[0]
        assert isinstance(value, ToolDenied)

    def test_low_role_denied_with_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic_ai.tools import ToolDenied

        out, captured = self._resume(monkeypatch, role="viewer", approved=True)
        value = list(captured["deferred_tool_results"].approvals.values())[0]
        assert isinstance(value, ToolDenied)
        assert "权限不足" in str(value)
