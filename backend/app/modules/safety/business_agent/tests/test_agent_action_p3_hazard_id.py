"""Agent 执行面三期（agent-action-p3）危险源辨识流转两件测试。

覆盖 spec（.scratch/agent-action-p3/spec.md）T4：
submit_hazard_identification（draft → in_progress 提交进 AI 流程）/
retry_hazard_identification_node（事件丢失兜底重触发当前节点）。
仅 safety_admin。

测试接缝：工具函数边界直接调用；resolve 走 FakeSession（select 结果），
SafetyService.submit / advance_bitable_record 类级/模块级打桩。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    ROLE_DEPT_LEADER,
    ROLE_INSPECTOR,
    ROLE_SAFETY_ADMIN,
    ROLE_VIEWER,
    check,
)
from app.modules.safety.business_agent.tools import registry
from app.modules.safety.business_agent.tools.hazard_id_action_tools import (
    retry_hazard_identification_node,
    submit_hazard_identification,
)


class _FakeResult:
    def __init__(self, *, one: Any = None) -> None:
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.commits = 0

    async def execute(self, stmt: Any) -> _FakeResult:
        return self._results.pop(0)

    async def commit(self) -> None:
        self.commits += 1


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _ctx(db: Any, role: str = "safety_admin") -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(db=db, person=None, role=role, session_id="s1", channel="test")
    )


def _hid(
    *,
    hid_id: uuid.UUID | None = None,
    status: str = "draft",
    feishu_record_id: str = "recA",
    hazard_id_no: str = "HI-20261028-001",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=hid_id or uuid.uuid4(),
        hazard_id_no=hazard_id_no,
        overall_status=status,
        ai_node_progress="pending_input",
        feishu_record_id=feishu_record_id,
        department="生产一部",
        is_deleted=False,
    )


# ═══ 接线 ═══


class TestHazardIdActionWiring:
    def test_tool_kind_write(self) -> None:
        assert registry.TOOL_KIND["submit_hazard_identification"] is True
        assert registry.TOOL_KIND["retry_hazard_identification_node"] is True

    def test_group_mounted(self) -> None:
        group = tool_selector.TOOL_GROUPS["hazard"]
        assert "submit_hazard_identification" in group
        assert "retry_hazard_identification_node" in group

    @pytest.mark.parametrize(
        "message",
        [
            "把这条危险源辨识提交 AI 流程",
            "这条辨识重新触发一下",
            "补触发一下辨识节点",
        ],
    )
    def test_route_hits_hazard(self, message: str) -> None:
        decision = tool_selector.route_message(message)
        group_tools = set(tool_selector.TOOL_GROUPS["hazard"])
        assert group_tools & set(decision.tool_names), (
            f"{message} 未命中 hazard 挂载: {decision}"
        )

    def test_permissions_admin_only(self) -> None:
        for tool in ("submit_hazard_identification", "retry_hazard_identification_node"):
            assert check(ROLE_SAFETY_ADMIN, tool)
            assert not check(ROLE_DEPT_LEADER, tool)
            assert not check(ROLE_INSPECTOR, tool)
            assert not check(ROLE_VIEWER, tool)


# ═══ submit ═══


class TestSubmitHazardIdentification:
    def _stub_submit(self, monkeypatch: pytest.MonkeyPatch, ret: Any) -> dict:
        from app.modules.safety.service.safety import SafetyService

        calls: dict = {"ids": []}

        async def fake(self, hid: uuid.UUID):
            calls["ids"].append(hid)
            return ret

        monkeypatch.setattr(SafetyService, "submit_hazard_identification", fake)
        return calls

    def test_submit_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        item = _hid()
        updated = SimpleNamespace(
            **{**item.__dict__, "overall_status": "in_progress",
               "ai_node_progress": "pending_script1"},
        )
        calls = self._stub_submit(monkeypatch, updated)
        db = FakeSession([_FakeResult(one=item)])
        out = _run(submit_hazard_identification(_ctx(db), ref=item.hazard_id_no))
        assert out["success"] is True
        assert out["hazard_id_no"] == item.hazard_id_no
        assert out["overall_status"] == "in_progress"
        assert out["ai_node_progress"] == "pending_script1"
        assert calls["ids"] == [item.id]
        assert db.commits >= 1

    def test_submit_non_draft_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_submit(monkeypatch, None)  # 不应被调用
        item = _hid(status="in_progress")
        db = FakeSession([_FakeResult(one=item)])
        out = _run(submit_hazard_identification(_ctx(db), ref=str(item.id)))
        assert out["success"] is False
        assert "draft" in out["message"]
        assert db.commits == 0

    def test_submit_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_submit(monkeypatch, None)
        db = FakeSession([_FakeResult(one=None)])
        out = _run(submit_hazard_identification(_ctx(db), ref="HI-20991231-999"))
        assert out["success"] is False
        assert "未找到" in out["message"]

    def test_submit_service_none_after_draft(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """service 返回 None（竞态下状态已变）→ 状态不允许说明。"""
        self._stub_submit(monkeypatch, None)
        item = _hid(status="draft")
        db = FakeSession([_FakeResult(one=item)])
        out = _run(submit_hazard_identification(_ctx(db), ref=item.hazard_id_no))
        assert out["success"] is False
        assert "状态" in out["message"]


# ═══ retry ═══


class TestRetryHazardIdentificationNode:
    def _stub_advance(self, monkeypatch: pytest.MonkeyPatch, ret: dict) -> dict:
        import app.modules.safety.feishu.hazard_identification_bitable_handler as h

        calls: dict = {"args": []}

        async def fake(record_id: str, **kwargs):
            calls["args"].append({"record_id": record_id, **kwargs})
            return ret

        monkeypatch.setattr(h, "advance_bitable_record", fake)
        return calls

    def test_retry_advanced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        item = _hid(status="in_progress", feishu_record_id="recXYZ")
        calls = self._stub_advance(
            monkeypatch,
            {"status": "advanced", "next_node": "pending_script2_review", "script": 1},
        )
        db = FakeSession([_FakeResult(one=item)])
        out = _run(retry_hazard_identification_node(_ctx(db), ref=item.hazard_id_no))
        assert out["success"] is True
        assert out["next_node"] == "pending_script2_review"
        assert calls["args"][0]["record_id"] == "recXYZ"
        assert calls["args"][0]["skip_dedup"] is True

    def test_retry_noop_reason_passthrough(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = _hid(status="in_progress")
        self._stub_advance(
            monkeypatch,
            {"status": "noop", "reason": "completed", "message": "流程已全部完成"},
        )
        db = FakeSession([_FakeResult(one=item)])
        out = _run(retry_hazard_identification_node(_ctx(db), ref=str(item.id)))
        assert out["success"] is False  # 未推进，如实说明
        assert out["reason"] == "completed"
        assert out["message"] == "流程已全部完成"

    def test_retry_not_bitable_mirror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._stub_advance(monkeypatch, {"status": "advanced"})
        item = _hid(status="in_progress", feishu_record_id="")
        db = FakeSession([_FakeResult(one=item)])
        out = _run(retry_hazard_identification_node(_ctx(db), ref=item.hazard_id_no))
        assert out["success"] is False
        assert "Bitable" in out["message"]
        assert calls["args"] == []  # 未触发 advance

    def test_retry_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_advance(monkeypatch, {})
        db = FakeSession([_FakeResult(one=None)])
        out = _run(retry_hazard_identification_node(_ctx(db), ref="rec-not-exist"))
        assert out["success"] is False
        assert "未找到" in out["message"]
