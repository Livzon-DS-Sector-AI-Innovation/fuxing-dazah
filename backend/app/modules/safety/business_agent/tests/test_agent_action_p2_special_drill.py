"""Agent 执行面二期（agent-action-p2）报备审批与演练动作工具测试。

覆盖 spec（.scratch/agent-action-p2/spec.md）T4-T5：
query_special_operation_reports / approve_special_operation_report /
reject_special_operation_report；generate_drill_eval /
create_hazards_from_drill。

测试接缝（与 test_agent_action_p2_hazard 一致）：工具函数边界直接调用，
FakeSession 按调用序返回预设结果（repo 层 scalar/execute 顺序），
路由断言走 tool_selector.select_tool_names 纯函数。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    ROLE_DEPT_LEADER,
    ROLE_INSPECTOR,
    ROLE_SAFETY_ADMIN,
    ROLE_VIEWER,
    allowed_tools,
)
from app.modules.safety.business_agent.tools import registry


# ── Fake DB（按调用序返回；记录 statement）────────────────────────


class _FakeResult:
    def __init__(self, *, scalar: Any = None, rows: list[Any] | None = None,
                 one: Any = None) -> None:
        self._scalar = scalar
        self._rows = rows or []
        self._one = one

    def scalar(self) -> Any:
        return self._scalar

    def scalars(self) -> Any:
        return SimpleNamespace(all=lambda: self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._one


class FakeSession:
    """依次返回预设结果；execute/scalar 各消费队列并记录 statement。"""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, stmt: Any) -> _FakeResult:
        self.statements.append(stmt)
        return self._results.pop(0)

    async def scalar(self, stmt: Any | None = None) -> Any:
        self.statements.append(stmt)
        return self._results.pop(0).scalar()

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        return None


def _ctx(db: Any) -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(db=db, chat_id="oc_test", role="safety_admin",
                             person=None),
    )


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _report(
    *, report_id: uuid.UUID | None = None, no: str = "XZ-2026-001",
    status: str = "submitted", op_type: str = "hot_work",
    dept: str = "生产部", leader: str = "张三",
) -> Any:
    from app.modules.safety.models import SpecialOperationReport

    return SpecialOperationReport(
        id=report_id or uuid.uuid4(), report_no=no, operation_type=op_type,
        operation_level="grade2", department=dept, location="罐区",
        work_description="罐区动火检修", work_leader_name=leader,
        applicant_name=leader, status=status,
        planned_start_time=datetime(2026, 10, 28, 9, 0, tzinfo=UTC),
        planned_end_time=datetime(2026, 10, 28, 17, 0, tzinfo=UTC),
    )


# ═══════════════════════════════════════════════════════════════════
# T5 演练动作 — generate_drill_eval / create_hazards_from_drill
# ═══════════════════════════════════════════════════════════════════


class TestDrillActionWiring:
    def test_registry_and_groups(self) -> None:
        from app.modules.safety.business_agent.tools.write_tools import (
            create_hazards_from_drill,
            generate_drill_eval,
        )

        for name, func in [
            ("generate_drill_eval", generate_drill_eval),
            ("create_hazards_from_drill", create_hazards_from_drill),
        ]:
            assert registry.TOOL_KIND[name] is True
            assert registry._FUNC_BY_NAME[name] is func
            assert name not in registry.RESIDENT_TOOLS
            assert name in tool_selector.TOOL_GROUPS["drill"]

    def test_permissions_admin_and_leader(self) -> None:
        """对齐 generate_drill_plan 现状：admin + leader。"""
        for name in ("generate_drill_eval", "create_hazards_from_drill"):
            assert name in allowed_tools(ROLE_SAFETY_ADMIN)
            assert name in allowed_tools(ROLE_DEPT_LEADER)
            assert name not in allowed_tools(ROLE_INSPECTOR)
            assert name not in allowed_tools(ROLE_VIEWER)

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("给上次消防演练生成评估表", "generate_drill_eval"),
            ("演练评估表 AI 生成一下", "generate_drill_eval"),
            ("把演练发现的问题转成隐患", "create_hazards_from_drill"),
            ("演练问题转隐患", "create_hazards_from_drill"),
        ],
    )
    def test_route_selects_drill_tools(self, message: str, expected: str) -> None:
        names = tool_selector.select_tool_names(message)
        assert expected in names, f"{message!r} → {names}"


def _drill_record(*, with_file: bool = True,
                  issues: str = "1. 疏散路线被占；2. 警报音量不足") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        drill_record_file=["/drill/record.docx"] if with_file else [],
        issues=issues,
    )


def _eval_doc() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(), title="2026 消防演练评估表", doc_type="drill_eval",
        version=1, feishu_doc_url="https://feishu.cn/docx/xxx",
        feishu_doc_status="created",
    )


def _patch_drill_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    record: Any,
    eval_doc: Any | None = None,
    created_hazards: list[dict] | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class _FakeDrillService:
        def __init__(self, db: Any) -> None:
            pass

        async def resolve_pg_record(self, ref: str) -> Any:
            captured["resolve_ref"] = ref
            return record

        async def create_hazards_from_issues(self, rid: Any) -> list[dict]:
            captured["create_record_id"] = str(rid)
            return created_hazards or []

    async def _fake_generate_eval_form(session: Any, record_id: Any, **kw: Any):
        captured["eval_record_id"] = str(record_id)
        captured["eval_kwargs"] = kw
        return eval_doc

    monkeypatch.setattr(
        "app.modules.safety.service.emergency_drill.EmergencyDrillService",
        _FakeDrillService,
    )
    monkeypatch.setattr(
        "app.modules.safety.service.drill_eval.generate_eval_form",
        _fake_generate_eval_form,
    )
    return captured


class TestGenerateDrillEval:
    def test_generates_eval_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.write_tools import (
            generate_drill_eval,
        )

        record = _drill_record()
        captured = _patch_drill_service(
            monkeypatch, record=record, eval_doc=_eval_doc(),
        )

        db = FakeSession([])
        result = _run(generate_drill_eval(_ctx(db), record_id="recABC"))

        assert result["success"] is True
        assert result["title"] == "2026 消防演练评估表"
        assert captured["resolve_ref"] == "recABC"
        assert captured["eval_record_id"] == str(record.id)
        assert db.commits >= 1

    def test_no_record_file_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.write_tools import (
            generate_drill_eval,
        )

        _patch_drill_service(
            monkeypatch, record=_drill_record(with_file=False), eval_doc=_eval_doc(),
        )

        result = _run(generate_drill_eval(_ctx(FakeSession([])), record_id="recABC"))

        assert result["success"] is False
        assert "演练记录表" in result["error"]

    def test_eval_generation_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.write_tools import (
            generate_drill_eval,
        )

        _patch_drill_service(
            monkeypatch, record=_drill_record(), eval_doc=None,
        )

        result = _run(generate_drill_eval(_ctx(FakeSession([])), record_id="recABC"))

        assert result["success"] is False

    def test_record_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.write_tools import (
            generate_drill_eval,
        )

        _patch_drill_service(monkeypatch, record=None, eval_doc=None)

        result = _run(generate_drill_eval(_ctx(FakeSession([])), record_id="rec404"))

        assert result["success"] is False
        assert "rec404" in result["error"]


class TestCreateHazardsFromDrill:
    def test_creates_hazards(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.write_tools import (
            create_hazards_from_drill,
        )

        record = _drill_record()
        created = [
            {"hazard_id": "hz-1", "hazard_no": "HZ-20261028-001",
             "drill_record_id": str(record.id)},
            {"hazard_id": "hz-2", "hazard_no": "HZ-20261028-002",
             "drill_record_id": str(record.id)},
        ]
        captured = _patch_drill_service(
            monkeypatch, record=record, created_hazards=created,
        )

        db = FakeSession([])
        result = _run(create_hazards_from_drill(_ctx(db), record_id=str(record.id)))

        assert result["success"] is True
        assert result["created_count"] == 2
        assert result["items"] == created
        assert captured["create_record_id"] == str(record.id)
        assert db.commits >= 1

    def test_empty_issues_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.write_tools import (
            create_hazards_from_drill,
        )

        _patch_drill_service(monkeypatch, record=_drill_record(issues="  "))

        result = _run(create_hazards_from_drill(_ctx(FakeSession([])), record_id="r"))

        assert result["success"] is False
        assert "演练问题" in result["error"]

    def test_record_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.write_tools import (
            create_hazards_from_drill,
        )

        _patch_drill_service(monkeypatch, record=None)

        result = _run(create_hazards_from_drill(_ctx(FakeSession([])), record_id="x"))

        assert result["success"] is False


# ═══════════════════════════════════════════════════════════════════
# T4 报备查询 + 审批
# ═══════════════════════════════════════════════════════════════════


class TestSpecialOpApprovalWiring:
    def test_registry_and_groups(self) -> None:
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            approve_special_operation_report,
            query_special_operation_reports,
            reject_special_operation_report,
        )

        assert registry.TOOL_KIND["query_special_operation_reports"] is False
        assert registry.TOOL_KIND["approve_special_operation_report"] is True
        assert registry.TOOL_KIND["reject_special_operation_report"] is True
        for name, func in [
            ("query_special_operation_reports", query_special_operation_reports),
            ("approve_special_operation_report", approve_special_operation_report),
            ("reject_special_operation_report", reject_special_operation_report),
        ]:
            assert registry._FUNC_BY_NAME[name] is func
            assert name not in registry.RESIDENT_TOOLS
            assert name in tool_selector.TOOL_GROUPS["special_op"]

    def test_permissions_query_all_roles(self) -> None:
        for role in (ROLE_SAFETY_ADMIN, ROLE_DEPT_LEADER, ROLE_INSPECTOR,
                     ROLE_VIEWER):
            assert "query_special_operation_reports" in allowed_tools(role)

    def test_permissions_approve_reject_admin_only(self) -> None:
        """审批仅 safety_admin；其余三角色拒绝（spec 拍板②）。"""
        assert "approve_special_operation_report" in allowed_tools(ROLE_SAFETY_ADMIN)
        assert "reject_special_operation_report" in allowed_tools(ROLE_SAFETY_ADMIN)
        for role in (ROLE_DEPT_LEADER, ROLE_INSPECTOR, ROLE_VIEWER):
            assert "approve_special_operation_report" not in allowed_tools(role)
            assert "reject_special_operation_report" not in allowed_tools(role)

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("有哪些待审批的特殊作业报备", "query_special_operation_reports"),
            ("待审批的报备给我看一下", "query_special_operation_reports"),
            ("把张三的动火报备批了", "approve_special_operation_report"),
            ("驳回这份特殊作业报备", "reject_special_operation_report"),
            ("报备审批情况怎么样", "query_special_operation_reports"),
        ],
    )
    def test_route_selects_approval_tools(self, message: str, expected: str) -> None:
        names = tool_selector.select_tool_names(message)
        assert expected in names, f"{message!r} → {names}"


class TestQuerySpecialOperationReports:
    def test_lists_submitted_reports(self) -> None:
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            query_special_operation_reports,
        )

        # repo 顺序：scalar(count) → execute(rows)
        db = FakeSession([
            _FakeResult(scalar=2),
            _FakeResult(rows=[_report(), _report(no="XZ-2026-002")]),
        ])
        result = _run(query_special_operation_reports(
            _ctx(db), status="submitted",
        ))

        assert result["success"] is True
        assert result["total"] == 2
        item = result["items"][0]
        assert item["report_no"] == "XZ-2026-001"
        assert item["operation_type"] == "动火作业"
        assert item["display_status"] == "审批中"
        params = str(db.statements[0].compile().params)
        assert "submitted" in params

    def test_operation_type_cn_normalized(self) -> None:
        """中文作业类型（动火作业）归一为 hot_work 再过滤。"""
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            query_special_operation_reports,
        )

        db = FakeSession([
            _FakeResult(scalar=1), _FakeResult(rows=[_report()]),
        ])
        _run(query_special_operation_reports(
            _ctx(db), operation_type="动火作业",
        ))

        params = str(db.statements[0].compile().params)
        assert "hot_work" in params

    def test_invalid_status_hint(self) -> None:
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            query_special_operation_reports,
        )

        result = _run(query_special_operation_reports(
            _ctx(FakeSession([])), status="moon",
        ))

        assert result["success"] is False
        assert "status" in result["error"]


class TestApproveSpecialOperationReport:
    def test_approve_by_report_no(self) -> None:
        """report_no 双态定位（用户口头引用编号，spec 拍板⑥）。"""
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            approve_special_operation_report,
        )

        report = _report()
        approved = _report(status="approved")  # repo.update 刷新后的对象
        # _resolve_report: execute(select by report_no)
        # service.approve_report → repo.get_by_id → execute(select)
        #                   → repo.update: execute(update) + execute(select)
        db = FakeSession([
            _FakeResult(one=report),          # resolve by_no
            _FakeResult(one=report),          # approve_report 内部 get_by_id
            _FakeResult(),                    # update
            _FakeResult(one=approved),        # refreshed select
        ])
        result = _run(approve_special_operation_report(
            _ctx(db), report_id="XZ-2026-001",
        ))

        assert result["success"] is True
        assert result["status"] == "已审批"
        assert db.commits >= 1
        assert "XZ-2026-001" in str(db.statements[0].compile().params)

    def test_approve_by_uuid(self) -> None:
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            approve_special_operation_report,
        )

        rid = uuid.uuid4()
        report = _report(report_id=rid)
        approved = _report(report_id=rid, status="approved")
        db = FakeSession([
            _FakeResult(one=report),    # get_report by id
            _FakeResult(one=report),    # approve_report 内部 get_by_id
            _FakeResult(),              # update
            _FakeResult(one=approved),  # refreshed select
        ])
        result = _run(approve_special_operation_report(_ctx(db), report_id=str(rid)))

        assert result["success"] is True

    def test_approve_not_found(self) -> None:
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            approve_special_operation_report,
        )

        db = FakeSession([_FakeResult(one=None)])
        result = _run(approve_special_operation_report(
            _ctx(db), report_id="XZ-9999",
        ))

        assert result["success"] is False
        assert "XZ-9999" in result["error"]

    def test_approve_wrong_state_explained(self) -> None:
        """非「审批中」状态的报备给出明确说明（draft/approved/rejected 不可审）。"""
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            approve_special_operation_report,
        )

        report = _report(status="draft")
        db = FakeSession([_FakeResult(one=report)])
        result = _run(approve_special_operation_report(
            _ctx(db), report_id="XZ-2026-001",
        ))

        assert result["success"] is False
        assert "草稿" in result["error"]


class TestRejectSpecialOperationReport:
    def test_reject_with_reason(self) -> None:
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            reject_special_operation_report,
        )

        report = _report()
        rejected = _report(status="rejected")
        rejected.rejection_reason = "安全措施不完整"
        db = FakeSession([
            _FakeResult(one=report),
            _FakeResult(one=report),    # reject_report 内部 get_by_id
            _FakeResult(),
            _FakeResult(one=rejected),
        ])
        result = _run(reject_special_operation_report(
            _ctx(db), report_id="XZ-2026-001", reason="安全措施不完整",
        ))

        assert result["success"] is True
        assert result["status"] == "已驳回"
        assert "安全措施不完整" in result["rejection_reason"]

    def test_reject_requires_reason(self) -> None:
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            reject_special_operation_report,
        )

        result = _run(reject_special_operation_report(
            _ctx(FakeSession([])), report_id="XZ-2026-001", reason="",
        ))

        assert result["success"] is False
        assert "原因" in result["error"]

    def test_reject_wrong_state_explained(self) -> None:
        from app.modules.safety.business_agent.tools.special_op_action_tools import (
            reject_special_operation_report,
        )

        report = _report(status="approved")
        db = FakeSession([_FakeResult(one=report)])
        result = _run(reject_special_operation_report(
            _ctx(db), report_id="XZ-2026-001", reason="不合规",
        ))

        assert result["success"] is False
        assert "已审批" in result["error"]
