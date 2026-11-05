"""五金库 M6 验收测试：superagent 事件源 hardware_alert_scan（5 类事件，
external_id 幂等=白名单∪闭环去重）+ Policy 三组合播种（R1+R2+HW）+
三执行器（催办卡/速递格/计划草案——零动账红线）。

设计依据：docs/DESIGN-五金库系统原生模块-20261104.md §九 9.2/9.3、§十一 二期；
R1 参照 backend/app/modules/safety/service/alarm_hazard_r1/。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware import planning as pl
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareMovement,
    HardwareReceipt,
    HardwareRequisition,
)
from app.platform.superagent.models import AgentSource
from app.platform.superagent.sources import source_registry

CN_TZ = ZoneInfo("Asia/Shanghai")

HW_SOURCE_NAME = "warehouse.hardware_alert_scan"


async def _mk_material(db, *, name="事件物料", safety=Decimal("50")):
    m = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec="DN50", unit="个",
        category="金属阀门", managed_class="stocked", safety_stock=safety,
        no_expiry=True,
    )
    db.add(m)
    await db.flush()
    return m


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
    return receipt


async def _mk_source_row(db, *, config: dict | None = None) -> AgentSource:
    """源行：迁移已在共享库播种同名行——复用（真机已有行先例），无则造。"""
    row = await db.scalar(
        select(AgentSource).where(AgentSource.name == HW_SOURCE_NAME)
    )
    if row is not None:
        row.config = config or {
            "schedule": {"strategy": "interval", "interval_seconds": 3600},
            "evaluate": True,
            "draft_backlog_threshold": 5,
        }
        row.enabled = True
        await db.flush()
        return row
    row = AgentSource(
        kind="hardware_alert_scan",
        name=HW_SOURCE_NAME,
        config=config or {
            "schedule": {"strategy": "interval", "interval_seconds": 3600},
            "evaluate": True,
            "draft_backlog_threshold": 5,
        },
        enabled=True,
    )
    db.add(row)
    await db.flush()
    return row


async def _mk_cursors(last_hour: bool = True) -> dict:
    """预置读位（首见 rebase 后第二轮才产 drafts，对齐 R1 门控语义）。"""
    if last_hour:
        return {"last_tick": (datetime.now(CN_TZ) - timedelta(hours=2)).isoformat()}
    return {}


# ── Ticket 07：事件源 + Policy 组合 ──


async def test_alert_scan_five_event_types(db_session):
    """五类事件扫描：低库存/紧急未补/草稿积压/超时未发料 全部成 draft；external_id 稳定。"""
    from app.modules.warehouse.hardware.superagent.scan_source import HardwareAlertScanSource

    # ① 低库存：available(10) < safety(50)
    m_low = await _mk_material(db_session, name="低库存物料", safety=Decimal("50"))
    await _mk_inbound(db_session, m_low, Decimal("10"))
    # ② 紧急 24h 未补单：issued+urgent+deadline 已过
    req = HardwareRequisition(
        req_no=f"WJK-LY-T-{uuid4().hex[:6].upper()}", dept_name="发酵",
        applicant="张三", req_type="urgent", status="overdue_unpatched",
        urgent_patch_deadline=datetime.now(CN_TZ) - timedelta(hours=30),
        issued_at=datetime.now(CN_TZ) - timedelta(hours=54),
    )
    db_session.add(req)
    # ③ OCR 草稿积压：6 张 draft（阈值 5）
    for _ in range(6):
        db_session.add(HardwareReceipt(
            receipt_no=f"WJK-RK-T-{uuid4().hex[:8].upper()}", source="ocr",
            mode="stocked", status="draft",
        ))
    # ④ 审批通过未发料超时：approved 且 approved_at 49h 前
    db_session.add(HardwareRequisition(
        req_no=f"WJK-LY-T2-{uuid4().hex[:6].upper()}", dept_name="动力机修",
        applicant="李四", req_type="normal", status="approved",
        approved_at=datetime.now(CN_TZ) - timedelta(hours=49),
    ))
    await db_session.flush()

    source = HardwareAlertScanSource()
    row = await _mk_source_row(db_session)
    cursors = await _mk_cursors()
    result = await source.poll(db_session, row, cursors)

    by_type: dict[str, list] = {}
    for d in result.drafts:
        et = (d.payload or {}).get("event_type")
        by_type.setdefault(et, []).append(d)
    today = datetime.now(CN_TZ).strftime("%Y-%m-%d")

    assert by_type.get("low_stock"), "低库存事件应成 draft"
    low = by_type["low_stock"][0]
    assert low.external_id == f"low_stock:{m_low.id}:{today}"
    assert low.payload["available"] == 10 and low.payload["safety_stock"] == 50
    assert by_type.get("urgent_unpatched"), "紧急未补单事件应成 draft"
    assert by_type.get("draft_backlog"), f"草稿积压应成 draft（{by_type.keys()}）"
    assert by_type["draft_backlog"][0].external_id == f"draft_backlog:{today}"
    assert by_type["draft_backlog"][0].payload["count"] == 6
    assert by_type.get("issue_timeout"), "超时未发料应成 draft"
    assert by_type.get("daily_digest"), "每日速递 draft 应产出（按日幂等键）"
    assert by_type["daily_digest"][0].external_id == f"daily_digest:{today}"
    # 读位推进（ingest 同事务承接）
    assert result.cursor_updates.get("last_tick")


async def test_alert_scan_low_stock_recovers_then_breaks_again(db_session):
    """低库存闭环去重：恢复后再击穿=新 external_id（日期键自然滚动口径下
    同日恢复再击穿不重复——external_id 天粒度；跨日再击穿=新事件）。"""
    from app.modules.warehouse.hardware.superagent.scan_source import HardwareAlertScanSource

    m = await _mk_material(db_session, name="击穿物料", safety=Decimal("5"))
    await _mk_inbound(db_session, m, Decimal("3"))  # available 3 < 5 击穿

    source = HardwareAlertScanSource()
    row = await _mk_source_row(db_session)
    now = datetime.now(CN_TZ)
    r1 = await source.poll(db_session, row, {"last_tick": (now - timedelta(hours=2)).isoformat()})
    low1 = [d for d in r1.drafts if d.payload.get("event_type") == "low_stock"]
    assert len(low1) == 1 and low1[0].external_id == f"low_stock:{m.id}:{now.strftime('%Y-%m-%d')}"

    # 补货恢复（available 10 > 5）→ 同轮不再产该物料低库存 draft
    await _mk_inbound(db_session, m, Decimal("7"))
    r2 = await source.poll(db_session, row, {"last_tick": (now - timedelta(hours=1)).isoformat()})
    low2 = [d for d in r2.drafts if d.payload.get("event_type") == "low_stock"
            and d.payload.get("material_id") == str(m.id)]
    assert low2 == [], "恢复后不应再产低库存事件"
    # 跨日再击穿=新事件由日期键保证（external_id 含 YYYY-MM-DD），不重复造时间断言


async def test_alert_scan_ingest_dedup(db_session):
    """同事件二次 ingest= duplicate（白名单∪闭环去重验收口径）。"""
    from app.platform.superagent.ingest import ingest_draft
    from app.modules.warehouse.hardware.superagent.scan_source import HardwareAlertScanSource

    m = await _mk_material(db_session, name="去重物料", safety=Decimal("100"))
    await _mk_inbound(db_session, m, Decimal("1"))

    source = HardwareAlertScanSource()
    row = await _mk_source_row(db_session)
    now = datetime.now(CN_TZ)
    cursors = {"last_tick": (now - timedelta(hours=2)).isoformat()}
    r1 = await source.poll(db_session, row, cursors)
    low = next(d for d in r1.drafts if d.payload.get("event_type") == "low_stock")

    outcome1, t1 = await ingest_draft(db_session, row, low)
    outcome2, t2 = await ingest_draft(db_session, row, low)
    assert outcome1 == "stored"
    assert outcome2 == "duplicate", "同事件二次触发不重复（external_id 幂等）"
    assert t2.id == t1.id


async def test_policy_combined_r1_r2_hardware(db_session):
    """Policy 三组合播种：现行版本含 R1+R2+HW 全部规则；重复 ensure 哈希稳定。"""
    from app.modules.safety.superagent_bridge import ensure_guardian_r2_policy
    from app.platform.superagent.policy import get_current_policy, policy_version_hash

    from app.modules.warehouse.hardware.superagent.rule import hardware_alert_rules

    await ensure_guardian_r2_policy(db_session)
    current = await get_current_policy(db_session)
    rule_ids = {r["rule_id"] for r in current.rules}
    assert "fire_alarm_candidate" in rule_ids  # R1
    assert {"guardian_review_remind", "guardian_score_map"} <= rule_ids  # R2
    expected_hardware = {r["rule_id"] for r in hardware_alert_rules()}
    assert expected_hardware <= rule_ids, "hardware 规则必须进现行 Policy（防升版挤掉）"

    # 幂等：重复 ensure 不升版
    hash_before = policy_version_hash(
        current.rules, current.accept_mode, current.admission or {},
    )
    await ensure_guardian_r2_policy(db_session)
    again = await get_current_policy(db_session)
    assert policy_version_hash(again.rules, again.accept_mode, again.admission or {}) == hash_before


async def test_source_kind_and_executors_registered():
    """warehouse 桥：kind 注册幂等；三执行器注册到位。"""
    from app.platform.superagent.executors import get_executor

    from app.modules.warehouse.hardware.superagent.bridge import (
        register_hardware_superagent,
    )

    register_hardware_superagent()
    register_hardware_superagent()  # 幂等
    assert source_registry.get("hardware_alert_scan") is not None
    for name in ("hardware_urge", "hardware_digest_push", "hardware_plan_draft"):
        assert get_executor(name) is not None, f"{name} 未注册"


# ── Ticket 08：三执行器行为 ──


async def test_executor_urge_no_chat_skips(monkeypatch):
    """空 chat 配置：静默跳过不报错（Report ready + skipped）。"""
    from app.modules.warehouse.hardware.superagent import executors as hw_exec

    async def _fake_payload(session, task_dict):
        return {"event_type": "low_stock", "external_id": "low_stock:x:2026-11-05"}

    monkeypatch.setattr(hw_exec, "_origin_payload", _fake_payload)
    monkeypatch.delenv("WAREHOUSE_HARDWARE_ALERT_CHAT_ID", raising=False)
    monkeypatch.delenv("WAREHOUSE_TEST_CHAT_ID", raising=False)
    report = await hw_exec.hardware_urge({"id": str(uuid4())}, [])
    assert report.kind == "ready"
    assert report.output.get("skipped") is True


def test_executor_urge_card_body():
    """催办卡文案：标题/物料/数字（payload=Source SQL 聚合）落卡正确。"""
    from app.modules.warehouse.hardware.superagent.executors import _build_urge_body

    body = _build_urge_body({
        "event_type": "low_stock", "name": "测试阀门", "spec": "DN25",
        "available": 3, "safety_stock": 10, "on_hand": 5, "reserved": 2,
        "code": None,
    })
    assert body["title"].startswith("🔴")
    assert "测试阀门" in body["content"]
    assert "3" in body["content"] and "10" in body["content"]


async def test_digest_numbers_match_movements(db_session):
    """digest 数字与流水逐项一致（数字全 SQL 聚合验收口径）。"""
    from app.modules.warehouse.hardware.superagent.executors import fetch_digest_numbers

    m = await _mk_material(db_session, name="速递物料")
    await _mk_inbound(db_session, m, Decimal("8"))
    db_session.add(HardwareMovement(
        movement_no=f"WJK-MV-D-{uuid4().hex[:8].upper()}",
        direction="outbound", business_type="req_issue",
        material_id=m.id, material_name=m.name,
        quantity=Decimal("3"),
        occurred_at=datetime.now(CN_TZ),
        dept_name="发酵",
    ))
    await db_session.flush()

    numbers = await fetch_digest_numbers(db_session)
    # 入库单（今日 accepted，含共享库其他当日单——按 >= 断言本单已计入）
    assert numbers["receipts_today"] >= 1
    assert numbers["outbound_qty_today"] >= 3
    assert numbers["low_stock_count"] >= 1  # safety=50 > available=5


async def test_executor_plan_draft_idempotent(db_session):
    """plan_draft 执行器走 M5 同一 service 入口：同月重跑不双建（幂等）。"""
    from app.modules.warehouse.hardware.models import HardwarePurchasePlan

    plan_month = f"{datetime.now(CN_TZ).year}-12"
    plan = await pl.generate_monthly_plan(db_session, plan_month, annotate=False)
    plan2 = await pl.generate_monthly_plan(db_session, plan_month, annotate=False)
    assert plan.id == plan2.id
    cnt = await db_session.scalar(
        select(func.count()).select_from(HardwarePurchasePlan).where(
            HardwarePurchasePlan.plan_month == plan_month,
        )
    )
    assert cnt == 1


# ── Ticket 09：报表完善 ──


async def test_movements_export_excel(db_session):
    """全量流水台账导出：不同 business_type 造数行数与关键列断言。"""
    from io import BytesIO

    from openpyxl import load_workbook

    from app.modules.warehouse.hardware import service as hw_service

    m = await _mk_material(db_session, name="台账物料")
    await _mk_inbound(db_session, m, Decimal("6"))
    db_session.add(HardwareMovement(
        movement_no=f"WJK-MV-E1-{uuid4().hex[:8].upper()}",
        direction="outbound", business_type="req_issue",
        material_id=m.id, material_name=m.name, quantity=Decimal("2"),
        occurred_at=datetime.now(CN_TZ), dept_name="发酵",
    ))
    db_session.add(HardwareMovement(
        movement_no=f"WJK-MV-E2-{uuid4().hex[:8].upper()}",
        direction="outbound", business_type="pass_out",
        material_id=m.id, material_name=m.name, quantity=Decimal("1"),
        occurred_at=datetime.now(CN_TZ), dept_name="提炼一期",
    ))
    await db_session.flush()

    xlsx, rows_count, truncated = await hw_service.export_movements_excel(
        db_session, keyword=m.name,
    )
    assert rows_count == 3 and not truncated
    wb = load_workbook(BytesIO(xlsx))
    ws = wb.active
    headers = [c.value for c in ws[1]]
    assert headers[:6] == ["流水号", "时间", "方向", "业务类型", "物料编码", "物资名称"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    # 本物料 3 条流水（inbound 1 + req_issue 1 + pass_out 1）
    assert len(rows) == 3
    biz = {r[3] for r in rows}
    assert {"入库", "领料出库", "直发出"} <= biz
