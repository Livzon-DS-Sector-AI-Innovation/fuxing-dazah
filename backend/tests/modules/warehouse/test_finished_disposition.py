"""成品待处理清单推送 + 处理方案确认门测试（V3.0 分期D Ticket 03，§4.8④）。

链路（沿 A 期 test_confirm_integration E2E 模式）：清单到期推送（dry_run）→
后置钩子按表分单建确认卡（退货/不合格各一张）→ handle_action 确认 →
逐条回写 Base「处理确认日期=当天」。Base 交互全部假件化（零网络）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import confirm_request as cr
from app.modules.warehouse.ai_audit import failure_notifier
from app.modules.warehouse.models import WarehouseConfirmRequest
from app.modules.warehouse.push_center import engine, generators
from app.modules.warehouse.push_center.confirm_integrations import (
    FINISHED_DISPOSITION_BIZ,
    finished_disposition_confirm_hook,
)

CN_TZ = ZoneInfo("Asia/Shanghai")
# finished_disposition_lists 日程：daily 09:15 窗口 60min
AT_0930 = datetime(2026, 9, 23, 9, 30, tzinfo=CN_TZ)


@dataclass
class StubPushRow:
    task_name: str
    enabled: bool = True
    schedule: dict[str, Any] | None = None
    targets: str | None = None
    note: str | None = None
    is_deleted: bool = False


def _ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=CN_TZ).timestamp() * 1000)


class FakeDispositionAdapter:
    """退货/不合格/入库台账假件：退货 2 条待处理 + 不合格 1 条待处理 +
    各 1 条已确认；入库台账含 1 条待处理批次。"""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "finished_returns": [
                {
                    "record_id": "ret_1",
                    "fields": {"退货日期": _ms(date(2026, 9, 10)), "产品名称": "盐酸万古霉素",
                               "品规": "沉淀粉 HAP", "产品批号": "HAP2412004EBH",
                               "退货客户": "REIG", "退货原因": "过滤堵塞",
                               "退货量": 57.06, "单位": "kg", "处理确认日期": None},
                },
                {
                    "record_id": "ret_2",
                    "fields": {"退货日期": _ms(date(2026, 9, 12)), "产品名称": "达托霉素",
                               "品规": "DA低规", "产品批号": "DA2609001",
                               "退货客户": "can", "退货原因": "运输破损",
                               "退货量": 2.5, "单位": "kg", "处理确认日期": None},
                },
                {
                    "record_id": "ret_done",
                    "fields": {"退货日期": _ms(date(2026, 8, 1)), "产品名称": "替考拉宁",
                               "品规": "TE", "产品批号": "TE2608001", "退货客户": "-",
                               "退货原因": "过效期", "退货量": 1.0, "单位": "kg",
                               "处理确认日期": 1760000000000},
                },
            ],
            "finished_unqualified": [
                {
                    "record_id": "unq_1",
                    "fields": {"登记日期": _ms(date(2026, 9, 5)), "产品名称": "特拉万星",
                               "品规": "TL", "产品批号": "TL2012001",
                               "产生数量": 0.562, "单位": "kg", "产生原因": "过效期",
                               "处理确认日期": None},
                },
            ],
            "finished_receipt": [
                {
                    "record_id": "rcpt_p",
                    "fields": {"入库日期": _ms(date(2026, 9, 20)), "产品名称": "达托霉素",
                               "产品批号": "DA2609020", "入库数量": 10.0,
                               "质量状态": "待处理"},
                },
                {
                    "record_id": "rcpt_ok",
                    "fields": {"入库日期": _ms(date(2026, 9, 20)), "产品名称": "达托霉素",
                               "产品批号": "DA2609021", "入库数量": 8.0,
                               "质量状态": "合格"},
                },
            ],
        }
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def search_records_page(
        self, table_key: str, **kwargs: Any
    ) -> dict[str, Any]:
        rows = self.tables.get(table_key, [])
        return {"records": rows, "total": len(rows), "page_token": None}

    async def update_record(
        self, table_key: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self.update_calls.append((table_key, record_id, dict(fields)))
        return {"record_id": record_id, "fields": {}}


@pytest.fixture
async def disposition_env(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> FakeDispositionAdapter:
    """引擎环境：仅 finished_disposition_lists 启用（oc_test），Base 全假件。"""
    from app.modules.warehouse import base_mirror

    await db_session.execute(
        delete(WarehouseConfirmRequest).where(
            WarehouseConfirmRequest.business_type == FINISHED_DISPOSITION_BIZ
        )
    )
    monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: True)

    from app.modules.warehouse.push_center.registry import iter_tasks
    from app.modules.warehouse.push_center.store import PushConfigStore

    rows = {
        info.task_name: StubPushRow(task_name=info.task_name, enabled=False)
        for info in iter_tasks()
        if info.trigger == "scheduled"
    }
    rows["finished_disposition_lists"] = StubPushRow(
        task_name="finished_disposition_lists", targets="oc_test"
    )
    test_store = PushConfigStore(row_loader=lambda name: rows.get(name))
    monkeypatch.setattr(engine, "push_store", test_store)
    monkeypatch.setattr(failure_notifier, "fire_notify_failure", MagicMock())

    adapter = FakeDispositionAdapter()
    # 生成器与钩子都在调用时 from bitable_adapter import WarehouseBitableAdapter，
    # 补丁必须打在源模块属性上（两处同时生效）
    monkeypatch.setattr(
        "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
        lambda: adapter,
    )
    return adapter


async def _disposition_requests(db: AsyncSession) -> list[WarehouseConfirmRequest]:
    rows = (
        await db.execute(
            select(WarehouseConfirmRequest).where(
                WarehouseConfirmRequest.business_type == FINISHED_DISPOSITION_BIZ
            )
        )
    ).scalars().all()
    return sorted(rows, key=lambda r: r.ref_table)


class TestDispositionListGenerator:
    async def test_card_lists_three_sections(
        self, db_session: AsyncSession, disposition_env: FakeDispositionAdapter
    ) -> None:
        card = await generators._generate_finished_disposition_lists(db_session, AT_0930)
        assert card["header"]["template"] == "red"  # 有确认门待处理行
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "**成品退货 2 条**" in text
        assert "过滤堵塞" in text
        assert "**成品不合格 1 条**" in text
        assert "过效期" in text
        assert "**待处理入库批次** 1 批" in text

    async def test_green_when_nothing_pending(
        self, db_session: AsyncSession, disposition_env: FakeDispositionAdapter
    ) -> None:
        disposition_env.tables["finished_returns"] = []
        disposition_env.tables["finished_unqualified"] = []
        disposition_env.tables["finished_receipt"] = []
        card = await generators._generate_finished_disposition_lists(db_session, AT_0930)
        assert card["header"]["template"] == "green"
        assert "无待处理项" in "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )


class TestDispositionConfirmHook:
    async def test_push_creates_two_gates_split_by_table(
        self, db_session: AsyncSession, disposition_env: FakeDispositionAdapter
    ) -> None:
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]

        requests = await _disposition_requests(db_session)
        assert len(requests) == 2  # 退货一张 + 不合格一张
        returns_req = next(r for r in requests if r.ref_table == "finished_returns")
        unqualified_req = next(r for r in requests if r.ref_table == "finished_unqualified")
        # 只覆盖待处理行（处理确认日期为空）；已确认 ret_done 不入单
        assert sorted(returns_req.ref_record_ids) == ["ret_1", "ret_2"]
        assert unqualified_req.ref_record_ids == ["unq_1"]
        assert returns_req.writeback == {"处理确认日期": "@today"}
        assert returns_req.target == "oc_test"
        assert "成品退货处理方案确认" in returns_req.title

    async def test_no_gate_when_writeback_disabled(
        self,
        db_session: AsyncSession,
        disposition_env: FakeDispositionAdapter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.warehouse import base_mirror

        monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: False)
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]  # 清单推送不受影响
        assert await _disposition_requests(db_session) == []

    async def test_end_to_end_confirm_writes_back(
        self,
        db_session: AsyncSession,
        disposition_env: FakeDispositionAdapter,
    ) -> None:
        """全链路：清单推送 → 确认卡 → 确认 → 回写 处理确认日期=当天毫秒。"""
        results = await engine.run_due_tasks(db_session, AT_0930, dry_run=True)
        assert [r.status for r in results] == ["executed"]
        requests = await _disposition_requests(db_session)
        returns_req = next(r for r in requests if r.ref_table == "finished_returns")

        outcome = await cr.handle_action(
            db_session,
            value={
                "scene": cr.CONFIRM_GATE_SCENE,
                "request_id": str(returns_req.id),
                "action": "confirm",
            },
            operator_open_id="ou_worker",
        )
        assert outcome.ok is True
        assert returns_req.status == "confirmed"

        # 回写 2 条待处理退货行（处理确认日期=当天毫秒时间戳；
        # execute_writeback 经 lazy import 取 bitable_adapter 类——已被 fixture
        # 替换为假件工厂，直接断言假件自身的 update_calls）
        calls = disposition_env.update_calls
        assert {c[1] for c in calls} == {"ret_1", "ret_2"}
        assert all(c[0] == "finished_returns" for c in calls)
        assert all(isinstance(c[2]["处理确认日期"], int) for c in calls)

    async def test_direct_hook_without_targets_returns_empty(
        self, db_session: AsyncSession, disposition_env: FakeDispositionAdapter
    ) -> None:
        from app.modules.warehouse.push_center.store import PushTaskView

        view = PushTaskView(
            task_name="finished_disposition_lists",
            scene="finished_disposition_lists",
            label="清单", description="",
            trigger="scheduled", enabled=True, schedule=None, targets=(), source="db",
        )
        assert await finished_disposition_confirm_hook(
            db_session, view, AT_0930, dry_run=True
        ) == []
