"""清单确认门接入测试（V3.0 分期A Ticket 07 + P0 双门，验收②端到端）。

链路：stale_lists 到期推送（dry_run）→ 后置钩子创建 不合格处理门 + 超6月
呆滞批次处理门（P0-2）→ handle_action 确认 → 按映射逐条回写 Base 处理
日期/呆滞处理确认日期。Base 交互全部经 monkeypatch 假件（零网络）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import confirm_request as cr
from app.modules.warehouse.ai_audit import failure_notifier
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.models import (
    WarehouseConfirmAudit,
    WarehouseConfirmRequest,
)
from app.modules.warehouse.push_center import engine, generators
from app.modules.warehouse.push_center.confirm_integrations import (
    DEAD_DISPOSITION,
    UNQUALIFIED_DISPOSITION,
    stale_lists_confirm_hook,
)
from app.modules.warehouse.push_center.store import PushConfigStore

CN_TZ = ZoneInfo("Asia/Shanghai")
# stale_lists 日程：daily 09:00 窗口 60min；09:30 在窗口内
AT_0930 = datetime(2026, 9, 23, 9, 30, tzinfo=CN_TZ)


@dataclass
class StubPushRow:
    task_name: str
    enabled: bool = True
    schedule: dict[str, Any] | None = None
    targets: str | None = None
    note: str | None = None
    is_deleted: bool = False


class FakeUnqualifiedAdapter:
    """unqualified_stock + material_receipt（呆滞）假件。

    - unqualified：2 条待跟进（处理日期空）+ 1 条已处理；物料名称用富文本
      分段形态（真机实测），回归验证卡片摘要不出现字典 repr；
    - dead（P0-2）：默认空（既有用例仅不合格门）；呆滞用例注入 2 待跟进 +
      1 已确认（呆滞处理确认日期非空）。
    """

    def __init__(self) -> None:
        self.records = [
            {"record_id": "rec_u1", "fields": {"物料名称": [{"text": "不合格物料A", "type": "text"}], "不合格项目": "含量不达标", "处理方式": None, "处理日期": None}},
            {"record_id": "rec_u2", "fields": {"物料名称": [{"text": "不合格物料B", "type": "text"}], "不合格项目": "包装破损", "处理方式": None, "处理日期": None}},
            {"record_id": "rec_u3", "fields": {"物料名称": "不合格物料C", "不合格项目": "过期", "处理方式": "退货", "处理日期": 1760000000000}},
        ]
        self.dead_records: list[dict[str, Any]] = []
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def search_records_page(self, table_key: str, **kwargs: Any) -> dict[str, Any]:
        if table_key == "unqualified_stock":
            return {"records": self.records, "total": len(self.records), "page_token": None}
        if table_key == "material_receipt":
            return {
                "records": self.dead_records,
                "total": len(self.dead_records),
                "page_token": None,
            }
        raise AssertionError(f"未预期的表: {table_key}")

    async def update_record(self, table_key: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.update_calls.append((table_key, record_id, dict(fields)))
        return {"record_id": record_id, "fields": {}}


def _fake_list_report(unqualified_total: int = 3):
    async def _report(report_type: str) -> dict[str, Any]:
        if report_type == "dead":
            return {"report_type": "dead", "total": 0, "records": [], "note": ""}
        return {
            "report_type": "unqualified",
            "total": unqualified_total,
            "records": [
                {"物料名称": "不合格物料A", "不合格项目": "含量不达标", "处理方式": ""},
            ],
            "note": "",
        }

    return _report


@pytest.fixture
async def stale_env(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> FakeUnqualifiedAdapter:
    """引擎环境：仅 stale_lists 启用（oc_test），清单聚合与 Base 全部假件化。"""
    from sqlalchemy import delete

    from app.modules.warehouse import base_mirror
    from app.modules.warehouse.models import WarehouseConfirmRequest

    # 封闭性：清两类业务既有确认单（真机验证留有真实记录；事务内删除随回滚撤销）
    await db_session.execute(
        delete(WarehouseConfirmRequest).where(
            WarehouseConfirmRequest.business_type.in_(
                [UNQUALIFIED_DISPOSITION, DEAD_DISPOSITION]
            )
        )
    )
    # 回写开关默认开（生产默认关；建单路径依赖回写）
    monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: True)
    # 封闭性：全部定时任务停用，仅 stale_lists 启用（分期D 新增任务
    # 在 09:30 窗口内会到期，且其 Base 读取不在本文件假件覆盖范围）
    from app.modules.warehouse.push_center.registry import iter_tasks

    rows = {
        info.task_name: StubPushRow(task_name=info.task_name, enabled=False)
        for info in iter_tasks()
        if info.trigger == "scheduled"
    }
    rows["stale_lists"] = StubPushRow(task_name="stale_lists", targets="oc_test")
    test_store = PushConfigStore(row_loader=lambda name: rows.get(name))
    monkeypatch.setattr(engine, "push_store", test_store)
    monkeypatch.setattr(generators, "query_report", _fake_list_report())
    monkeypatch.setattr(failure_notifier, "fire_notify_failure", MagicMock())

    adapter = FakeUnqualifiedAdapter()
    import app.modules.warehouse.push_center.confirm_integrations as ci

    monkeypatch.setattr(ci, "WarehouseBitableAdapter", lambda: adapter)
    return adapter


async def _confirm_requests(
    db: AsyncSession, business_type: str = UNQUALIFIED_DISPOSITION
) -> list[WarehouseConfirmRequest]:
    rows = (
        await db.execute(
            select(WarehouseConfirmRequest).where(
                WarehouseConfirmRequest.business_type == business_type
            )
        )
    ).scalars().all()
    return list(rows)


class TestStaleListsConfirmHook:
    async def test_push_creates_confirm_request_with_pending_records(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter
    ) -> None:
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]

        requests = await _confirm_requests(db_session)
        assert len(requests) == 1
        request = requests[0]
        # 只覆盖待跟进（处理日期为空）的 2 条；已处理的 rec_u3 不入单
        assert request.ref_record_ids == ["rec_u1", "rec_u2"]
        assert request.ref_table == "unqualified_stock"
        assert request.target == "oc_test"
        assert request.status == "pending"
        assert request.card_message_id == "dry_run"
        # 回写映射：处理日期=@today 哨兵（确认执行时解析为当天毫秒时间戳）
        assert request.writeback == {"处理日期": "@today"}
        # 富文本分段规范解析：摘要显示纯文本名，不出现字典 repr
        assert "不合格物料A" in request.summary
        assert "不合格物料B" in request.summary
        assert "{'text'" not in request.summary
        assert "**2** 条不合格物料待跟进" in request.summary
        # create 审计
        audits = (
            await db_session.execute(
                select(WarehouseConfirmAudit).where(
                    WarehouseConfirmAudit.request_no == request.request_no
                )
            )
        ).scalars().all()
        assert any(a.action == "create" for a in audits)

    async def test_no_pending_creates_nothing(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter
    ) -> None:
        stale_env.records = [stale_env.records[2]]  # 仅保留已处理条目
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]
        assert await _confirm_requests(db_session) == []

    async def test_no_confirm_card_when_writeback_disabled(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回写开关关闭（生产默认）：清单卡照发，但不建确认单。"""
        from app.modules.warehouse import base_mirror

        monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: False)
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]  # 清单推送不受影响
        assert await _confirm_requests(db_session) == []

    async def test_hook_failure_does_not_fail_push(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("确认门钩子异常")

        monkeypatch.setattr(engine, "SCENE_POST_SEND_HOOKS", {"stale_lists": _boom})
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        # 清单推送本身成功，钩子失败只告警
        assert [r.status for r in results] == ["executed"]
        failure_notifier.fire_notify_failure.assert_called()
        assert await _confirm_requests(db_session) == []

    async def test_end_to_end_confirm_writes_back(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验收②全链路：清单推送 → 确认卡 → 群内确认 → 回写处理日期 → 回执。"""
        # 回写走 WarehouseBitableAdapter 假件（confirm_request.execute_writeback 内）
        update_mock = AsyncMock(return_value={"record_id": "r", "fields": {}})
        monkeypatch.setattr(WarehouseBitableAdapter, "update_record", update_mock)

        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]
        request = (await _confirm_requests(db_session))[0]

        # 群内任何人（点击者 ou_worker）确认 → 同步回写
        outcome = await cr.handle_action(
            db_session,
            value={"scene": cr.CONFIRM_GATE_SCENE, "request_id": str(request.id), "action": "confirm"},
            operator_open_id="ou_worker",
        )
        assert outcome.ok is True
        assert request.status == "confirmed"
        assert request.confirmed_by == "ou_worker"

        # 逐条回写待跟进记录（2 条，处理日期=当天时间戳）
        assert update_mock.await_count == 2
        calls = [c.args for c in update_mock.await_args_list]
        assert {c[1] for c in calls} == {"rec_u1", "rec_u2"}
        assert all(c[0] == "unqualified_stock" for c in calls)
        assert all(isinstance(c[2]["处理日期"], int) for c in calls)

        # 审计闭环：create → confirm → writeback_ok
        actions = (
            await db_session.execute(
                select(WarehouseConfirmAudit.action).where(
                    WarehouseConfirmAudit.request_no == request.request_no
                )
            )
        ).scalars().all()
        assert "create" in actions and "confirm" in actions and "writeback_ok" in actions

    async def test_direct_hook_requires_target(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.push_center.store import PushTaskView

        view = PushTaskView(
            task_name="stale_lists", scene="stale_lists", label="清单", description="",
            trigger="scheduled", enabled=True, schedule=None, targets=(), source="db",
        )
        assert await stale_lists_confirm_hook(db_session, view, AT_0930, dry_run=True) == []


class TestDeadStockConfirmGate:
    """超6月呆滞批次处理门（P0-2）：呆料判断=是 且 呆滞处理确认日期为空。"""

    @staticmethod
    def _dead_rows() -> list[dict[str, Any]]:
        return [
            {"record_id": "rec_d1", "fields": {"物料名称": "呆滞物料A", "物料批号": "PC260301", "入库数量": 12.5, "呆滞处理确认日期": None}},
            {"record_id": "rec_d2", "fields": {"物料名称": "呆滞物料B", "物料批号": "PC260401", "入库数量": 3, "呆滞处理确认日期": None}},
            {"record_id": "rec_d3", "fields": {"物料名称": "呆滞物料C", "物料批号": "PC260501", "入库数量": 8, "呆滞处理确认日期": 1760000000000}},
        ]

    async def test_dead_gate_created_with_pending_batches(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter
    ) -> None:
        stale_env.dead_records = self._dead_rows()
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]

        dead_requests = await _confirm_requests(db_session, DEAD_DISPOSITION)
        assert len(dead_requests) == 1
        request = dead_requests[0]
        # 只覆盖待跟进（呆滞处理确认日期为空）的 2 批；已确认的 rec_d3 不入单
        assert request.ref_record_ids == ["rec_d1", "rec_d2"]
        assert request.ref_table == "material_receipt"
        assert request.target == "oc_test"
        assert request.status == "pending"
        assert request.writeback == {"呆滞处理确认日期": "@today"}
        assert "超6月呆滞批次" in request.summary
        assert "呆滞物料A" in request.summary and "PC260301" in request.summary
        # 双门并存：不合格门（fixture 默认 2 条待跟进）也建了
        assert len(await _confirm_requests(db_session)) == 1

    async def test_no_dead_batches_no_dead_gate(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter
    ) -> None:
        stale_env.dead_records = []
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]
        assert await _confirm_requests(db_session, DEAD_DISPOSITION) == []

    async def test_end_to_end_dead_confirm_writes_back(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """呆滞门全链路：推送 → 确认卡 → 确认 → 逐条回写呆滞处理确认日期。"""
        stale_env.dead_records = self._dead_rows()
        update_mock = AsyncMock(return_value={"record_id": "r", "fields": {}})
        monkeypatch.setattr(WarehouseBitableAdapter, "update_record", update_mock)

        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]
        request = (await _confirm_requests(db_session, DEAD_DISPOSITION))[0]

        outcome = await cr.handle_action(
            db_session,
            value={"scene": cr.CONFIRM_GATE_SCENE, "request_id": str(request.id), "action": "confirm"},
            operator_open_id="ou_worker_dead",
        )
        assert outcome.ok is True
        assert request.status == "confirmed"

        # 逐条回写 material_receipt（2 条，呆滞处理确认日期=当天时间戳）
        assert update_mock.await_count == 2
        calls = [c.args for c in update_mock.await_args_list]
        assert {c[1] for c in calls} == {"rec_d1", "rec_d2"}
        assert all(c[0] == "material_receipt" for c in calls)
        assert all(isinstance(c[2]["呆滞处理确认日期"], int) for c in calls)

    async def test_one_gate_failure_does_not_block_other(
        self, db_session: AsyncSession, stale_env: FakeUnqualifiedAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不合格门拉取异常 → 呆滞门仍创建（单门失败不阻断另一门）。"""
        import app.modules.warehouse.push_center.confirm_integrations as ci

        stale_env.dead_records = self._dead_rows()

        async def _boom(adapter: Any) -> list[dict[str, Any]]:
            raise RuntimeError("不合格清单拉取失败")

        monkeypatch.setattr(ci, "fetch_unqualified_records", _boom)
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]
        assert await _confirm_requests(db_session) == []  # 不合格门失败
        assert len(await _confirm_requests(db_session, DEAD_DISPOSITION)) == 1  # 呆滞门照建
