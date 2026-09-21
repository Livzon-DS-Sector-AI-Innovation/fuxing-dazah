"""推送订阅中心测试（V3.0 分期A Ticket 01）：registry/store/引擎/晨报生成器。

接缝：服务函数级（spec Testing Decisions）——
- store 用构造函数 row_loader 注入预设行（仿 TestSchedulerStore）；
- 引擎直接调 run_due_tasks / run_task，dry_run=True 走 notification 注入口；
- 失败告警 monkeypatch failure_notifier.fire_notify_failure。

引擎返回语义：只有「实际尝试执行」的任务出现在结果里
（executed/failed/skipped_no_target/skipped_busy）；
未到期与停用任务静默跳过（tick 高频轮询不产生噪音）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.cards import build_card
from app.modules.warehouse.ai_audit import failure_notifier
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseDailyBriefing,
    WarehousePushLog,
    WarehousePushTaskAudit,
)
from app.modules.warehouse.push_center import engine, generators
from app.modules.warehouse.push_center.registry import iter_tasks
from app.modules.warehouse.push_center.store import PushConfigStore

CN_TZ = ZoneInfo("Asia/Shanghai")

# 固定日期锚点：2026-09-21 周一 / 2026-09-23 周三 / 2026-10-01 周四
MON_0845 = datetime(2026, 9, 21, 8, 45, tzinfo=CN_TZ)
WED_0830 = datetime(2026, 9, 23, 8, 30, tzinfo=CN_TZ)
OCT01_0845 = datetime(2026, 10, 1, 8, 45, tzinfo=CN_TZ)


@dataclass
class StubPushRow:
    """模拟 push_tasks 活行（store 只读这几个属性）。"""

    task_name: str
    enabled: bool = True
    schedule: dict[str, Any] | None = None
    targets: str | None = None
    note: str | None = None
    is_deleted: bool = False


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value, raising=False)


def _make_store(
    rows: dict[str, StubPushRow | None], monkeypatch: pytest.MonkeyPatch
) -> PushConfigStore:
    _patch_settings(monkeypatch, WAREHOUSE_ALERT_CHAT_ID="")
    return PushConfigStore(row_loader=lambda name: rows.get(name))


async def _logs(db: AsyncSession, task_name: str) -> list[WarehousePushLog]:
    rows = (
        await db.execute(
            select(WarehousePushLog).where(WarehousePushLog.task_name == task_name)
        )
    ).scalars().all()
    return list(rows)


@pytest.fixture
def engine_env(monkeypatch: pytest.MonkeyPatch) -> PushConfigStore:
    """引擎测试环境：晨报任务指向 oc_test，其余定时任务停用，失败告警静音。"""
    rows = _with_disabled_defaults(
        {
            "morning_report": StubPushRow(task_name="morning_report", targets="oc_test"),
        }
    )
    test_store = _make_store(rows, monkeypatch)
    monkeypatch.setattr(engine, "push_store", test_store)
    monkeypatch.setattr(failure_notifier, "fire_notify_failure", MagicMock())
    return test_store


def _with_disabled_defaults(
    rows: dict[str, StubPushRow | None],
) -> dict[str, StubPushRow | None]:
    """未列出的定时任务补停用行（封闭性：新任务注册表默认启用，会污染到期断言）。"""
    full: dict[str, StubPushRow | None] = {
        info.task_name: StubPushRow(task_name=info.task_name, enabled=False)
        for info in iter_tasks()
        if info.trigger == "scheduled"
    }
    full.update(rows)
    return full


def _swap_rows(store: PushConfigStore, rows: dict[str, StubPushRow | None]) -> None:
    store._row_loader = lambda name: _with_disabled_defaults(rows).get(name)  # noqa: SLF001 — 测试注入口
    store.invalidate()


def _stub_generator(scene: str) -> Any:
    """占位生成器（周报/月报真实生成器属 Ticket 03，到期测试只关心调度逻辑）。"""

    async def _gen(db: AsyncSession, now: datetime) -> dict[str, Any]:
        return build_card(title=f"桩卡-{scene}", template="blue", elements=[])

    return _gen


def _register_stubs(
    monkeypatch: pytest.MonkeyPatch, *scenes: str
) -> None:
    patched = dict(generators.GENERATORS)
    for scene in scenes:
        patched.setdefault(scene, _stub_generator(scene))
    monkeypatch.setattr(generators, "GENERATORS", patched)


@pytest.fixture(autouse=True)
async def _hermetic_push_tables(db_session: AsyncSession) -> AsyncIterator[None]:
    """清空推送日志/审计表（事务内删除，随 teardown 回滚）。

    共享开发库存在真实运行数据（真机验证/日常推送），精确计数断言
    （len == 1 / .one()）必须只看到本用例写入的行。
    """
    from sqlalchemy import delete

    await db_session.execute(delete(WarehousePushLog))
    await db_session.execute(delete(WarehousePushTaskAudit))
    yield


# ═══════════════════════════════════════════════════════════════
# registry
# ═══════════════════════════════════════════════════════════════


class TestPushRegistry:
    def test_all_tasks_registered(self) -> None:
        names = {info.task_name for info in iter_tasks()}
        assert names == {
            # V3.0 分期A（5 个）
            "morning_report",
            "weekly_stock_report",
            "monthly_report_push",
            "stale_lists",
            "express_notify",
            # V3.0 分期B（QC 请验放行，3 个事件型）
            "arrival_inspection",
            "qc_progress_alert",
            "release_notify",
            # V3.0 分期C（供应商不一致提醒，事件型）
            "supplier_mismatch_alert",
            # V3.0 分期D（分析补全，7 个定时型）
            "finished_daily_summary",
            "invoice_four_state",
            "finished_disposition_lists",
            "shipment_analysis",
            "material_usage_compare",
            "workshop_weekly_usage",
            "annual_report",
        }

    def test_scheduled_vs_event(self) -> None:
        by_name = {info.task_name: info for info in iter_tasks()}
        for name in ("express_notify", "arrival_inspection", "qc_progress_alert", "release_notify"):
            assert by_name[name].trigger == "event"
            assert by_name[name].default_schedule is None
        for name in (
            "morning_report",
            "weekly_stock_report",
            "monthly_report_push",
            "stale_lists",
            "finished_daily_summary",
            "invoice_four_state",
            "finished_disposition_lists",
            "shipment_analysis",
            "material_usage_compare",
            "workshop_weekly_usage",
            "annual_report",
        ):
            assert by_name[name].trigger == "scheduled"
            assert by_name[name].default_schedule is not None

    def test_annual_report_yearly_schedule(self) -> None:
        """年报推送为 yearly 调度（分期D 新增第五态）。"""
        info = {t.task_name: t for t in iter_tasks()}["annual_report"]
        assert info.default_schedule == {"type": "yearly", "month": 1, "day": 1, "time": "08:30"}


# ═══════════════════════════════════════════════════════════════
# store
# ═══════════════════════════════════════════════════════════════


class TestPushStore:
    def test_missing_row_defaults_from_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_store({}, monkeypatch)
        view = store.get_task_view("morning_report")
        assert view.enabled is True
        assert view.schedule == {"type": "daily", "time": "08:00"}
        assert view.targets == ()
        assert view.source == "default"

    def test_db_row_overrides_targets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_store(
            {"morning_report": StubPushRow(task_name="morning_report", targets="oc_a, ou_b")},
            monkeypatch,
        )
        view = store.get_task_view("morning_report")
        assert view.targets == ("oc_a", "ou_b")
        assert view.source == "db"

    def test_env_fallback_targets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_ALERT_CHAT_ID="oc_env")
        store = PushConfigStore(row_loader=lambda name: None)
        view = store.get_task_view("morning_report")
        assert view.targets == ("oc_env",)

    def test_disabled_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_store(
            {"morning_report": StubPushRow(task_name="morning_report", enabled=False)},
            monkeypatch,
        )
        assert store.get_task_view("morning_report").enabled is False

    def test_unknown_task_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_store({}, monkeypatch)
        with pytest.raises(ValueError, match="未知任务"):
            store.get_task_view("nope")

    async def test_set_task_rejects_bad_schedule(
        self, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
    ) -> None:
        store = _make_store({}, monkeypatch)
        with pytest.raises(ValueError, match="schedule"):
            await store.set_task(
                db_session,
                "morning_report",
                {"schedule": {"type": "cron", "expr": "* * * * *"}},
            )

    async def test_set_task_writes_row_and_audit(
        self, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
    ) -> None:
        store = _make_store({}, monkeypatch)
        view = await store.set_task(
            db_session,
            "morning_report",
            {"enabled": False, "targets": "oc_x", "note": "验收"},
            operator_name="管理员",
        )
        assert view.enabled is False
        assert view.targets == ("oc_x",)
        audit = (
            await db_session.execute(
                select(WarehousePushTaskAudit).where(
                    WarehousePushTaskAudit.task_name == "morning_report"
                )
            )
        ).scalars().one()
        assert audit.action == "disable"
        assert audit.operator_name == "管理员"
        assert audit.after_json is not None and audit.after_json["targets"] == "oc_x"


# ═══════════════════════════════════════════════════════════════
# 引擎：到期判断与执行
# ═══════════════════════════════════════════════════════════════


class TestRunDueTasks:
    async def test_daily_task_due_in_window_executes_once(
        self, db_session: AsyncSession, engine_env: PushConfigStore
    ) -> None:
        results = await engine.run_due_tasks(db_session, WED_0830, dry_run=True)
        assert [r.task_name for r in results] == ["morning_report"]
        assert results[0].status == "executed"

        logs = await _logs(db_session, "morning_report")
        assert len(logs) == 1
        assert logs[0].status == "success"
        assert logs[0].target == "oc_test"
        assert logs[0].message_id == notification.DRY_RUN_MESSAGE_ID
        assert logs[0].slot == datetime(2026, 9, 23, 8, 0, tzinfo=CN_TZ)
        assert logs[0].trigger == "scheduled"

        # 同窗口内重复 tick：当日仅执行一次（静默跳过，无新日志）
        results2 = await engine.run_due_tasks(
            db_session, WED_0830 + timedelta(minutes=10), dry_run=True
        )
        assert results2 == []
        assert len(await _logs(db_session, "morning_report")) == 1

    async def test_daily_task_outside_window_silent(
        self, db_session: AsyncSession, engine_env: PushConfigStore
    ) -> None:
        results = await engine.run_due_tasks(
            db_session, datetime(2026, 9, 23, 10, 0, tzinfo=CN_TZ), dry_run=True
        )
        assert results == []
        assert len(await _logs(db_session, "morning_report")) == 0

    async def test_disabled_task_silent(
        self, db_session: AsyncSession, engine_env: PushConfigStore
    ) -> None:
        _swap_rows(
            engine_env,
            {
                "morning_report": StubPushRow(task_name="morning_report", enabled=False),
                "weekly_stock_report": StubPushRow(task_name="weekly_stock_report", enabled=False),
                "monthly_report_push": StubPushRow(task_name="monthly_report_push", enabled=False),
                "stale_lists": StubPushRow(task_name="stale_lists", enabled=False),
            },
        )
        results = await engine.run_due_tasks(db_session, WED_0830, dry_run=True)
        assert results == []
        assert len(await _logs(db_session, "morning_report")) == 0

    async def test_no_target_skips_and_logs(
        self,
        db_session: AsyncSession,
        engine_env: PushConfigStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_ALERT_CHAT_ID="")
        _swap_rows(
            engine_env,
            {"morning_report": StubPushRow(task_name="morning_report", targets="")},
        )
        results = await engine.run_due_tasks(db_session, WED_0830, dry_run=True)
        assert [r.status for r in results] == ["skipped_no_target"]
        logs = await _logs(db_session, "morning_report")
        assert len(logs) == 1
        assert logs[0].status == "skipped"
        assert logs[0].error is not None and "目标" in logs[0].error

    async def test_weekly_task_due_only_on_weekday(
        self, db_session: AsyncSession, engine_env: PushConfigStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _register_stubs(monkeypatch, "weekly_stock_report")
        _swap_rows(
            engine_env,
            {
                "morning_report": StubPushRow(task_name="morning_report", enabled=False),
                "weekly_stock_report": StubPushRow(
                    task_name="weekly_stock_report", targets="oc_test"
                ),
                "monthly_report_push": StubPushRow(task_name="monthly_report_push", enabled=False),
                "stale_lists": StubPushRow(task_name="stale_lists", enabled=False),
            },
        )

        # 周三 09:00：本周槽位是周一 08:30，已出窗 → 静默
        results = await engine.run_due_tasks(
            db_session, datetime(2026, 9, 23, 9, 0, tzinfo=CN_TZ), dry_run=True
        )
        assert results == []

        # 周一 08:45：在窗口内 → 执行
        results = await engine.run_due_tasks(db_session, MON_0845, dry_run=True)
        assert [r.task_name for r in results] == ["weekly_stock_report"]
        assert results[0].status == "executed"
        logs = await _logs(db_session, "weekly_stock_report")
        assert logs[0].slot == datetime(2026, 9, 21, 8, 30, tzinfo=CN_TZ)

    async def test_monthly_task_due_on_first_day(
        self, db_session: AsyncSession, engine_env: PushConfigStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _register_stubs(monkeypatch, "monthly_report_push")
        _swap_rows(
            engine_env,
            {
                "morning_report": StubPushRow(task_name="morning_report", enabled=False),
                "weekly_stock_report": StubPushRow(task_name="weekly_stock_report", enabled=False),
                "monthly_report_push": StubPushRow(
                    task_name="monthly_report_push", targets="oc_test"
                ),
                "stale_lists": StubPushRow(task_name="stale_lists", enabled=False),
            },
        )

        # 09:45 已出窗（08:30 + 60min）→ 静默
        results = await engine.run_due_tasks(
            db_session, datetime(2026, 10, 1, 9, 45, tzinfo=CN_TZ), dry_run=True
        )
        assert results == []

        results = await engine.run_due_tasks(db_session, OCT01_0845, dry_run=True)
        assert [r.task_name for r in results] == ["monthly_report_push"]
        assert results[0].status == "executed"
        logs = await _logs(db_session, "monthly_report_push")
        assert logs[0].slot == datetime(2026, 10, 1, 8, 30, tzinfo=CN_TZ)

    async def test_interval_task_due_and_cooldown(
        self, db_session: AsyncSession, engine_env: PushConfigStore
    ) -> None:
        _swap_rows(
            engine_env,
            {
                "morning_report": StubPushRow(
                    task_name="morning_report",
                    schedule={"type": "interval", "seconds": 60},
                    targets="oc_test",
                ),
                "weekly_stock_report": StubPushRow(task_name="weekly_stock_report", enabled=False),
                "monthly_report_push": StubPushRow(task_name="monthly_report_push", enabled=False),
                "stale_lists": StubPushRow(task_name="stale_lists", enabled=False),
            },
        )

        now = datetime(2026, 9, 23, 12, 0, tzinfo=CN_TZ)
        results = await engine.run_due_tasks(db_session, now, dry_run=True)
        assert [r.status for r in results] == ["executed"]
        logs = await _logs(db_session, "morning_report")
        assert logs[0].slot is None

        # 冷却期内（< 60s）不再触发
        results = await engine.run_due_tasks(
            db_session, now + timedelta(seconds=30), dry_run=True
        )
        assert results == []

    async def test_generator_failure_isolated_and_notified(
        self, db_session: AsyncSession, engine_env: PushConfigStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _swap_rows(
            engine_env,
            {
                "morning_report": StubPushRow(task_name="morning_report", targets="oc_a"),
                "weekly_stock_report": StubPushRow(task_name="weekly_stock_report", enabled=False),
                "monthly_report_push": StubPushRow(task_name="monthly_report_push", enabled=False),
                "stale_lists": StubPushRow(
                    task_name="stale_lists",
                    schedule={"type": "daily", "time": "08:20"},
                    targets="oc_b",
                ),
            },
        )

        async def _boom(db: AsyncSession, now: datetime) -> dict[str, Any]:
            raise RuntimeError("清单查询失败")

        monkeypatch.setattr(
            generators, "GENERATORS", {**generators.GENERATORS, "stale_lists": _boom}
        )

        results = await engine.run_due_tasks(db_session, WED_0830, dry_run=True)
        by_name = {r.task_name: r.status for r in results}
        assert by_name["stale_lists"] == "failed"
        assert by_name["morning_report"] == "executed"

        failed_logs = await _logs(db_session, "stale_lists")
        assert len(failed_logs) == 1
        assert failed_logs[0].status == "failed"
        assert "清单查询失败" in (failed_logs[0].error or "")

        # 失败告警触发一次，且不影响其他任务的成功日志
        assert len(await _logs(db_session, "morning_report")) == 1
        failure_notifier.fire_notify_failure.assert_called_once()

    async def test_send_failure_logs_failed_row(
        self, db_session: AsyncSession, engine_env: PushConfigStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_send(chat_id: str, card: dict[str, Any], dry_run: bool | None = None):
            return None  # 发送失败（不抛异常）

        monkeypatch.setattr(notification, "send_card", _fake_send)
        results = await engine.run_due_tasks(db_session, WED_0830, dry_run=True)
        assert [r.status for r in results] == ["executed"]
        logs = await _logs(db_session, "morning_report")
        assert logs[0].status == "failed"
        assert logs[0].message_id is None
        failure_notifier.fire_notify_failure.assert_called_once()

    async def test_run_task_manual_bypasses_due_check(
        self, db_session: AsyncSession, engine_env: PushConfigStore
    ) -> None:
        now = datetime(2026, 9, 23, 15, 0, tzinfo=CN_TZ)  # 窗口外手动触发
        result = await engine.run_task(db_session, "morning_report", now, dry_run=True)
        assert result.status == "executed"
        logs = await _logs(db_session, "morning_report")
        assert logs[0].trigger == "manual"
        # 窗口外手动触发不占用当日槽位（不阻断后续定时执行）
        assert logs[0].slot is None

    async def test_task_mutex_busy(
        self, db_session: AsyncSession, engine_env: PushConfigStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = asyncio.Event()

        async def _slow(db: AsyncSession, now: datetime) -> dict[str, Any]:
            await release.wait()
            return {"schema": "2.0", "body": {"elements": []}}

        monkeypatch.setattr(
            generators, "GENERATORS", {**generators.GENERATORS, "morning_report": _slow}
        )
        t1 = asyncio.create_task(engine.run_task(db_session, "morning_report", WED_0830, dry_run=True))
        await asyncio.sleep(0)  # 让 t1 进入锁
        t2 = asyncio.create_task(engine.run_task(db_session, "morning_report", WED_0830, dry_run=True))
        result2 = await t2
        assert result2.status == "skipped_busy"
        release.set()
        result1 = await t1
        assert result1.status == "executed"


# ═══════════════════════════════════════════════════════════════
# 晨报生成器
# ═══════════════════════════════════════════════════════════════


class TestMorningGenerator:
    async def test_card_structure_and_briefing_upsert(self, db_session: AsyncSession) -> None:
        generator = generators.get_push_generator("morning_report")
        assert generator is not None
        card = await generator(db_session, WED_0830)
        assert card["schema"] == "2.0"
        assert "晨报" in card["header"]["title"]["content"]
        joined = "".join(str(e) for e in card["body"]["elements"])
        assert "入库" in joined and "出库" in joined
        assert "异常" in joined

        # 聚合同日幂等落库（briefing 行存在，重复生成覆盖不报错）
        async def _briefing_count() -> int:
            return (
                await db_session.execute(
                    select(func.count())
                    .select_from(WarehouseDailyBriefing)
                    .where(WarehouseDailyBriefing.brief_date == WED_0830.date())
                )
            ).scalar_one()

        assert await _briefing_count() == 1
        card2 = await generator(db_session, WED_0830)
        assert card2["schema"] == "2.0"
        assert await _briefing_count() == 1


# ═══════════════════════════════════════════════════════════════
# 周报 / 月报 / 清单生成器（Ticket 03）
# ═══════════════════════════════════════════════════════════════


async def _seed_movement(
    db: AsyncSession,
    *,
    direction: str,
    quantity: float,
    occurred_at: datetime,
    suffix: str,
) -> None:
    """seed 物料+库位+流水（远古时间窗隔离共享库中的其他数据）。"""
    from app.modules.warehouse.models import (
        WarehouseLocation,
        WarehouseMaterial,
        WarehouseMovement,
    )

    material = WarehouseMaterial(
        code=f"V3A-M-{suffix}", name=f"推送测试物料{suffix}", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    location = WarehouseLocation(code=f"V3A-L-{suffix}", name="推送测试库位")
    db.add_all([material, location])
    await db.flush()
    db.add(
        WarehouseMovement(
            movement_no=f"V3A-{direction[:2].upper()}-{suffix}",
            direction=direction,
            source_type="purchase",
            material_id=material.id,
            material_code=material.code,
            material_name=material.name,
            quantity=Decimal(str(quantity)),
            unit=material.unit,
            location_id=location.id,
            location_code=location.code,
            location_name=location.name,
            occurred_at=occurred_at,
        )
    )
    await db.flush()


class TestWeeklyMonthlyGenerators:
    async def test_weekly_card_counts_seeded_movements(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 呆滞/不合格计数走 Base（query_report），测试假件化
        async def _fake_report(report_type: str) -> dict[str, Any]:
            return {
                "report_type": report_type,
                "total": 3 if report_type == "dead" else 2,
                "records": [],
                "note": "",
            }

        monkeypatch.setattr(generators, "query_report", _fake_report)
        await _seed_movement(
            db_session, direction="inbound", quantity=10,
            occurred_at=datetime(2019, 12, 28, 10, 0, tzinfo=CN_TZ), suffix="W1",
        )
        await _seed_movement(
            db_session, direction="outbound", quantity=4,
            occurred_at=datetime(2019, 12, 29, 11, 0, tzinfo=CN_TZ), suffix="W2",
        )
        generator = generators.get_push_generator("weekly_stock_report")
        assert generator is not None
        card = await generator(db_session, datetime(2020, 1, 1, 8, 30, tzinfo=CN_TZ))
        assert "周库存报表" in card["header"]["title"]["content"]
        joined = "".join(str(e) for e in card["body"]["elements"])
        assert "入库** 1 笔 / 10" in joined
        assert "出库** 1 笔 / 4" in joined
        assert "库存概况" in joined
        assert "呆滞批次** 3 条" in joined
        assert "不合格物料** 2 条" in joined

    async def test_monthly_card_reuses_monthly_report(self, db_session: AsyncSession) -> None:
        await _seed_movement(
            db_session, direction="inbound", quantity=30,
            occurred_at=datetime(2019, 12, 15, 9, 0, tzinfo=CN_TZ), suffix="M1",
        )
        generator = generators.get_push_generator("monthly_report_push")
        assert generator is not None
        card = await generator(db_session, datetime(2020, 1, 1, 8, 30, tzinfo=CN_TZ))
        assert "仓储月报 · 2019-12" in card["header"]["title"]["content"]
        joined = "".join(str(e) for e in card["body"]["elements"])
        assert "入库** 1 笔 / 30" in joined
        assert "出库** 0 笔 / 0" in joined


class TestStaleListsGenerator:
    @staticmethod
    def _fake_report(dead_total: int, unqualified_total: int) -> Any:
        async def _report(report_type: str) -> dict[str, Any]:
            if report_type == "dead":
                return {
                    "report_type": "dead", "report_name": "呆料批次清单",
                    "total": dead_total,
                    "records": [
                        {"物料名称": f"呆料物料{i}", "物料批号": f"B{i}",
                         "呆料产生数量（入库数量）": str(10 + i), "单位": "Kg"}
                        for i in range(min(dead_total, 3))
                    ],
                    "note": "",
                }
            return {
                "report_type": "unqualified", "report_name": "不合格物料汇总",
                "total": unqualified_total,
                "records": [
                    {"物料名称": f"不合格物料{i}", "不合格项目": "含量不达标",
                     "处理方式": "", "到货日期": "2026-09-01"}
                    for i in range(min(unqualified_total, 3))
                ],
                "note": "",
            }

        return _report

    async def test_card_with_llm_summary(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(generators, "query_report", self._fake_report(2, 1))

        async def _llm(prompt: str) -> str:
            return "建议优先复核呆料批次，可联系使用部门消化库存。"

        monkeypatch.setattr(generators, "_llm_summarize", _llm)
        generator = generators.get_push_generator("stale_lists")
        assert generator is not None
        card = await generator(db_session, WED_0830)
        assert "呆滞与不合格清单" in card["header"]["title"]["content"]
        joined = "".join(str(e) for e in card["body"]["elements"])
        assert "呆滞批次 2 条" in joined
        assert "不合格物料 1 条" in joined
        assert "建议优先复核呆料批次" in joined

    async def test_llm_failure_falls_back_to_template(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(generators, "query_report", self._fake_report(3, 2))

        async def _llm(prompt: str) -> str:
            raise RuntimeError("LLM 不可用")

        monkeypatch.setattr(generators, "_llm_summarize", _llm)
        generator = generators.get_push_generator("stale_lists")
        assert generator is not None
        card = await generator(db_session, WED_0830)
        joined = "".join(str(e) for e in card["body"]["elements"])
        assert "呆滞批次 3 条、不合格物料 2 条待处理" in joined

    async def test_empty_lists_green_card(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(generators, "query_report", self._fake_report(0, 0))
        generator = generators.get_push_generator("stale_lists")
        assert generator is not None
        card = await generator(db_session, WED_0830)
        joined = "".join(str(e) for e in card["body"]["elements"])
        assert "无待处理项" in joined
