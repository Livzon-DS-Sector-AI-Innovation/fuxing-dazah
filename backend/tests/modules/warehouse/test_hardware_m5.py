"""五金库 M5 验收测试：月度采购计划（25 日快照+P7 公式+同月重跑幂等+表样导出）
+ 呆滞季度扫描 + 温湿度日检。

设计依据：docs/DESIGN-五金库系统原生模块-20261104.md §2.6/§十一 二期；
spec .scratch/hardware-store-p2/spec.md（P7：月采购量=安全库存+月使用量−25日库存）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.modules.warehouse.hardware import planning as pl
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareEnvLog,
    HardwareMaterial,
    HardwareMovement,
    HardwarePurchasePlan,
    HardwarePurchasePlanItem,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def _mk_material(db, *, name="计划物料", safety=Decimal("20"),
                       demands: dict | None = None):
    material = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec="DN32", unit="个",
        category="金属管件", managed_class="stocked", safety_stock=safety,
        no_expiry=True, monthly_demands=demands or {"发酵": 20, "动力机修": 25},
    )
    db.add(material)
    await db.flush()
    return material


async def _mk_inbound(db, material, qty: Decimal) -> None:
    from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn

    payload = ReceiptCreate(
        source="manual", mode="stocked", supplier_name="测试供应商",
        items=[ReceiptItemIn(
            material_id=str(material.id), name=material.name, spec=material.spec,
            unit=material.unit, quantity=qty, match_confidence="manual",
        )],
    )
    receipt = await hw.create_receipt(db, payload)
    await hw.accept_receipt(
        db, receipt.id, inspected_by_warehouse="ou_warehouse", inspected_by_dept="ou_dept",
    )


async def _mk_outbound(db, material, qty: Decimal, *, days_ago: int = 5) -> None:
    """直接造 req_issue 流水（近 30 天使用量口径）。"""
    mv = HardwareMovement(
        movement_no=f"WJK-MV-TEST-{uuid4().hex[:8].upper()}",
        direction="outbound", business_type="req_issue",
        material_id=material.id, material_name=material.name,
        quantity=qty,
        occurred_at=datetime.now(CN_TZ) - timedelta(days=days_ago),
        dept_name="发酵",
    )
    db.add(mv)
    await db.flush()


# ── Ticket 04：P7 公式 + 幂等 + 任务注册 ──


async def test_plan_formula_manual_check(db_session):
    """P7 公式与手工复核一致：采购量=安全库存+近30天使用−25日库存；负取 0。"""
    m1 = await _mk_material(db_session, name="公式物料甲", safety=Decimal("20"))
    m2 = await _mk_material(db_session, name="公式物料乙", safety=Decimal("5"))
    await _mk_inbound(db_session, m1, Decimal("30"))
    await _mk_outbound(db_session, m1, Decimal("25"), days_ago=5)
    # m2：库存 40 高位、无使用 → 公式 5+0-40=-35 → 取 0
    await _mk_inbound(db_session, m2, Decimal("40"))
    # 31 天前的旧流水不计入近 30 天使用
    await _mk_outbound(db_session, m2, Decimal("99"), days_ago=31)

    snapshot = datetime(2026, 11, 25, 9, 0, tzinfo=CN_TZ)
    plan = await pl.generate_monthly_plan(
        db_session, "2026-12", snapshot_at=snapshot, annotate=False,
    )
    assert plan.plan_month == "2026-12"
    items = await pl.list_plan_items(db_session, plan.id)
    by_m = {str(i.material_id): i for i in items}
    row1 = by_m[str(m1.id)]
    # 手工复核：安全 20 + 使用 25 − 库存 30 = 15
    assert row1.monthly_usage == Decimal("25")
    assert row1.stock_on_25th == Decimal("30")
    assert row1.safety_stock == Decimal("20")
    assert row1.purchase_qty == Decimal("15")
    assert row1.monthly_demand_total == Decimal("45")  # 20+25
    assert "库存高于安全线" not in (row1.remark or "")

    row2 = by_m[str(m2.id)]
    assert row2.monthly_usage == Decimal("0")  # 31 天前不计
    assert row2.purchase_qty == Decimal("0")
    assert "库存高于安全线" in (row2.remark or "")


async def test_plan_regenerate_keeps_edited_rows(db_session):
    """同月重跑幂等：未编辑行按新快照刷新，is_edited 行保留人工值。"""
    m1 = await _mk_material(db_session, name="幂等物料甲", safety=Decimal("10"))
    await _mk_inbound(db_session, m1, Decimal("8"))
    snapshot = datetime(2026, 11, 25, 9, 0, tzinfo=CN_TZ)

    plan = await pl.generate_monthly_plan(
        db_session, "2026-12", snapshot_at=snapshot, annotate=False,
    )
    items = await pl.list_plan_items(db_session, plan.id)
    row = next(i for i in items if i.material_id == m1.id)
    assert row.purchase_qty == Decimal("2")  # 10+0−8

    # 人工把采购量改成 50 → is_edited
    edited = await pl.update_plan_item(
        db_session, row.id, purchase_qty=Decimal("50"), remark="冬季检修备货",
    )
    assert edited.is_edited is True and edited.purchase_qty == Decimal("50")

    # 库存变化（再入 10 → on_hand 18）后同月重跑
    await _mk_inbound(db_session, m1, Decimal("10"))
    plan2 = await pl.generate_monthly_plan(
        db_session, "2026-12", snapshot_at=snapshot, annotate=False,
    )
    assert plan2.id == plan.id  # plan_month 唯一，头复用
    items2 = await pl.list_plan_items(db_session, plan2.id)
    row2 = next(i for i in items2 if i.material_id == m1.id)
    # 编辑行保留人工值（不按新公式刷新）
    assert row2.purchase_qty == Decimal("50")
    assert row2.is_edited is True
    # 同月只此一行（未重复建行）
    cnt = await db_session.scalar(
        select(func.count()).select_from(HardwarePurchasePlanItem).where(
            HardwarePurchasePlanItem.purchase_plan_id == plan.id,
        )
    )
    assert cnt == len(items)


async def test_monthly_plan_task_registered():
    """25 日 CRON 任务并入 register_hardware_tasks 注册全集。"""
    from app.platform.scheduler.registry import SchedulerRegistry

    from app.modules.warehouse.hardware.scheduled import register_hardware_tasks

    registry = SchedulerRegistry()
    register_hardware_tasks(registry)
    names = set(registry.tasks.keys())
    assert "warehouse.hardware_monthly_plan" in names


# ── Ticket 05：AI 注释场景 + 表样导出 ──


def test_plan_annotation_scenario_registered():
    """场景 hardware_plan_annotation 已注册（迁移播种的代码唯一事实源）。"""
    from app.modules.warehouse.ai_config.scenario_registry import get_scenario

    info = get_scenario("hardware_plan_annotation")
    assert info.model_type == "text"
    assert info.channel == "system"


async def test_plan_annotation_llm_failure_keeps_draft(db_session, monkeypatch):
    """LLM 调用失败 → ai_note 空、annotated=False，草案照常（不阻塞公式主流程）。"""
    from app.modules.warehouse.agent import llm_client as llm_mod

    class _Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def chat_with_tools(self, *args, **kwargs):
            raise RuntimeError("LLM down（测试注入）")

    monkeypatch.setattr(llm_mod, "get_llm_client", lambda: _Boom())

    m = await _mk_material(db_session, name="注释物料", safety=Decimal("10"))
    await _mk_inbound(db_session, m, Decimal("5"))
    await _mk_outbound(db_session, m, Decimal("2"), days_ago=3)  # 有用量→进注释目标集

    plan = await pl.generate_monthly_plan(
        db_session, "2026-12", annotate=True,
        snapshot_at=datetime(2026, 11, 25, 9, 0, tzinfo=CN_TZ),
    )
    assert plan.annotated is False  # 失败兜底
    items = await pl.list_plan_items(db_session, plan.id)
    assert items  # 草案行照常生成
    row = next(i for i in items if i.material_id == m.id)
    assert row.purchase_qty == Decimal("7")  # 10+2−5（流水造数不扣批次，on_hand=5）
    assert row.ai_note is None


async def test_plan_export_excel_columns(db_session):
    """制度附件 4 表样导出：11 列表头逐项断言（任务书列清单原文）。"""
    m = await _mk_material(db_session, name="导出物料", safety=Decimal("10"))
    await _mk_inbound(db_session, m, Decimal("3"))
    plan = await pl.generate_monthly_plan(
        db_session, "2026-12", annotate=False,
        snapshot_at=datetime(2026, 11, 25, 9, 0, tzinfo=CN_TZ),
    )
    items = await pl.list_plan_items(db_session, plan.id)

    from io import BytesIO

    from openpyxl import load_workbook

    xlsx = pl.export_plan_excel(items, plan_month=plan.plan_month)
    wb = load_workbook(BytesIO(xlsx))
    ws = wb.active
    headers = [c.value for c in ws[1]]
    assert headers == [
        "序号", "物料编码", "物资名称", "规格型号", "单位", "数量",
        "月需求合计", "安全库存量", "当月25日库存量", "月度采购量", "备注",
    ]
    row = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[2] == m.name)
    assert row[8] == 3  # 当月25日库存量
    assert row[9] == 7  # 月度采购量 10+0-3


# ── Ticket 06：呆滞扫描 + 温湿度 ──


async def test_stale_scan_backtracks_movements(db_session):
    """呆滞名单按 movements 回算：91 天无 outbound 且有库存=呆滞。"""
    m_stale = await _mk_material(db_session, name="呆滞物料")
    m_active = await _mk_material(db_session, name="活跃物料")
    m_empty = await _mk_material(db_session, name="零库存物料")
    await _mk_inbound(db_session, m_stale, Decimal("5"))
    await _mk_inbound(db_session, m_active, Decimal("5"))
    # 零库存物料：无入库批次（on_hand=0）→ 不进名单（流水造数不扣批次，
    # 真实扣批次走发料链；呆滞口径=on_hand>0 才有意义）
    # 呆滞物料：出库在 100 天前（>91）
    await _mk_outbound(db_session, m_stale, Decimal("1"), days_ago=100)
    # 活跃物料：出库在 10 天前
    await _mk_outbound(db_session, m_active, Decimal("1"), days_ago=10)
    await _mk_outbound(db_session, m_empty, Decimal("1"), days_ago=100)

    now = datetime(2026, 11, 5, 9, 0, tzinfo=CN_TZ)
    stale = await pl.scan_stale_materials(db_session, now=now)
    ids = {r["material_id"] for r in stale}
    assert str(m_stale.id) in ids
    assert str(m_active.id) not in ids
    assert str(m_empty.id) not in ids  # 零库存（无批次）不进名单
    row = next(r for r in stale if r["material_id"] == str(m_stale.id))
    assert row["on_hand"] == 5.0


async def test_env_log_upsert_daily_unique(db_session):
    """温湿度当日重复提交 upsert 不双行。"""
    from datetime import date as date_cls

    d = date_cls(2026, 11, 5)
    log1 = await pl.upsert_env_log(
        db_session, log_date=d, temperature=Decimal("22.5"),
        humidity=Decimal("45.0"), checked_by="仓管员甲",
    )
    log2 = await pl.upsert_env_log(
        db_session, log_date=d, temperature=Decimal("23.1"),
        humidity=Decimal("46.2"), checked_by="仓管员甲",
    )
    assert log1.id == log2.id
    assert log2.temperature == Decimal("23.1")  # 后值覆盖
    cnt = await db_session.scalar(
        select(func.count()).select_from(HardwareEnvLog).where(HardwareEnvLog.log_date == d)
    )
    assert cnt == 1


async def test_all_m5_tasks_registered():
    """25 日计划/季度呆滞/温湿度提醒三任务均注册生效。"""
    from app.platform.scheduler.registry import SchedulerRegistry

    from app.modules.warehouse.hardware.scheduled import register_hardware_tasks

    registry = SchedulerRegistry()
    register_hardware_tasks(registry)
    names = set(registry.tasks.keys())
    assert {
        "warehouse.hardware_monthly_plan",
        "warehouse.hardware_stale_scan",
        "warehouse.hardware_env_remind",
    } <= names


def test_push_center_scenes_registered():
    """呆滞清单/温湿度提醒事件型推送任务已入注册表（37e529db 断言族）。"""
    from app.modules.warehouse.push_center.registry import get_task
    from app.modules.warehouse.push_center.events import get_event_renderer

    for scene in ("hardware_stale_list", "hardware_env_remind"):
        info = get_task(scene)
        assert info is not None and info.trigger == "event"
        assert get_event_renderer(scene) is not None
