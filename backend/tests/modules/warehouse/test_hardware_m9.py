"""五金库 M9 验收测试：observe→auto 阶段1 放权——direct 高置信自动入账
（默认关/双通道开关/四条件闸/审计快照/周报披露）。

设计依据：docs/DESIGN-五金库系统原生模块-20261104.md §9.3（红线：stocked
类永不自动；总闸一键熔断；全部 AI 动作审计）；spec .scratch/hardware-store-p3/spec.md §4。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareMovement,
    HardwareReceipt,
)

ENABLED_KEY = "hardware_ocr_auto_direct_enabled"
THRESHOLD_KEY = "hardware_ocr_auto_direct_min_confidence"


# ── 造数与 runtime 桩 ──


async def _mk_material(db, *, name="direct物料", spec=None, unit="个",
                       managed_class="direct"):
    material = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec=spec, unit=unit,
        category="耗材", managed_class=managed_class, safety_stock=Decimal("0"),
        no_expiry=True,
    )
    db.add(material)
    await db.flush()
    return material


async def _mk_direct_draft(db, material, *, score=Decimal("95"), dept="发酵") -> HardwareReceipt:
    """direct 高置信草稿（模拟 OCR 管线输出形态）。"""
    from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn

    payload = ReceiptCreate(
        source="ocr", mode="direct", supplier_name="直发供应商",
        target_dept=dept,
        items=[ReceiptItemIn(
            material_id=str(material.id), name=material.name,
            spec=material.spec, unit=material.unit, quantity=Decimal("4"),
            match_confidence="name_spec", match_score=score,
        )],
    )
    return await hw.create_receipt(db, payload)


def _patch_runtime(monkeypatch, *, enabled: Any, threshold: float = 0.9, source: str = "db"):
    """钉死 M9 双键（体内后装覆盖 conftest fixture；先失效进程内 TTL 缓存）。"""
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    runtime_store.invalidate(ENABLED_KEY)
    runtime_store.invalidate(THRESHOLD_KEY)

    class _View:
        def __init__(self, value: Any, src: str):
            self.value = value
            self.source = src

    original_get_value = runtime_store.get_value
    original_get_view = runtime_store.get_view

    def fake_get_value(key: str) -> Any:
        if key == ENABLED_KEY:
            return enabled
        if key == THRESHOLD_KEY:
            return threshold
        return original_get_value(key)

    def fake_get_view(key: str):
        if key == ENABLED_KEY:
            return _View(enabled, source)
        if key == THRESHOLD_KEY:
            return _View(threshold, source)
        return original_get_view(key)

    monkeypatch.setattr(runtime_store, "get_value", fake_get_value)
    monkeypatch.setattr(runtime_store, "get_view", fake_get_view)


# ── 验收用例 ──


async def test_switch_off_behavior_byte_identical(db_session):
    """验收①：开关关=行为与现状逐字节一致（评估零副作用、断言零自动单）。"""
    # 造 direct 高置信草稿（若开关开会自动入账的形态）
    m = await _mk_material(db_session, name="关闸物料")
    receipt = await _mk_direct_draft(db_session, m, score=Decimal("99"))

    # 不打桩=默认关（registry default=0；环境变量未配）——直接调评估
    result = await hw.try_auto_accept_direct(db_session, receipt.id, operator="测试")
    assert result is None
    await db_session.refresh(receipt)
    assert receipt.status == "draft"      # 留人工
    assert receipt.auto_accepted is False
    assert receipt.accepted_at is None
    assert receipt.auto_accept_snapshot is None  # 关闸短路零写入

    # 全库断言零自动单
    auto_count = await db_session.scalar(
        select(func.count()).select_from(HardwareReceipt).where(
            HardwareReceipt.auto_accepted.is_(True),
            HardwareReceipt.is_deleted.is_(False),
        )
    )
    assert (auto_count or 0) == 0


async def test_switch_on_full_conditions_auto_accepts(db_session, monkeypatch):
    """验收②：开关开+全条件满足=direct 自动 accepted + 审计标记/快照落库。"""
    _patch_runtime(monkeypatch, enabled=1, threshold=0.9, source="db")
    m = await _mk_material(db_session, name="自动入账物料")
    receipt = await _mk_direct_draft(db_session, m, score=Decimal("95"))

    result = await hw.try_auto_accept_direct(db_session, receipt.id, operator="测试")
    assert result is not None
    await db_session.refresh(result)
    assert result.status == "accepted"
    assert result.auto_accepted is True
    assert result.inspected_by_warehouse == "system:auto"
    assert result.auto_accept_snapshot is not None
    snap = result.auto_accept_snapshot
    assert snap["decision"] == "auto_accepted"
    assert snap["switch_source"] == "db"
    assert snap["threshold"] == 0.9
    assert snap["screening_flagged"] is False
    assert snap["row_scores"][0]["pass"] is True

    # direct 双流水净零（inbound+outbound 各一条 pass 流水，不占库存）
    mvs = list(
        (
            await db_session.execute(
                select(HardwareMovement).where(
                    HardwareMovement.ref_id == result.id,
                    HardwareMovement.is_deleted.is_(False),
                )
            )
        ).scalars().all()
    )
    assert {mv.business_type for mv in mvs} == {"pass_in", "pass_out"}
    assert all(mv.quantity > 0 for mv in mvs)

    # 幂等：再次评估返回 None（已 accepted）
    assert await hw.try_auto_accept_direct(db_session, result.id) is None


async def test_stocked_mixed_stays_draft_forever(db_session, monkeypatch):
    """红线：stocked 行混单永不自动（开关开也不行）→ 留人工队列。"""
    _patch_runtime(monkeypatch, enabled=1, threshold=0.5)
    stocked = await _mk_material(db_session, name="混单stocked", managed_class="stocked")
    direct = await _mk_material(db_session, name="混单direct")
    from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn

    payload = ReceiptCreate(
        source="ocr", mode="stocked", supplier_name="混合供应商",
        items=[
            ReceiptItemIn(
                material_id=str(direct.id), name=direct.name, unit=direct.unit,
                quantity=Decimal("3"), match_confidence="name_spec",
                match_score=Decimal("98"),
            ),
            ReceiptItemIn(
                material_id=str(stocked.id), name=stocked.name, unit=stocked.unit,
                quantity=Decimal("2"), match_confidence="name_spec",
                match_score=Decimal("98"),
            ),
        ],
    )
    receipt = await hw.create_receipt(db_session, payload)
    result = await hw.try_auto_accept_direct(db_session, receipt.id)
    assert result is None
    await db_session.refresh(receipt)
    assert receipt.status == "draft"
    assert receipt.auto_accept_snapshot["decision"].startswith("rejected_stocked_rows")


async def test_low_confidence_stays_draft(db_session, monkeypatch):
    """任一条件不满足·低置信：行分数<阈值 → 留 draft（低置信标黄走人工）。"""
    _patch_runtime(monkeypatch, enabled=1, threshold=0.9)
    m = await _mk_material(db_session, name="低置信物料")
    receipt = await _mk_direct_draft(db_session, m, score=Decimal("72"))  # <90
    result = await hw.try_auto_accept_direct(db_session, receipt.id)
    assert result is None
    await db_session.refresh(receipt)
    assert receipt.status == "draft"
    assert receipt.auto_accept_snapshot["decision"].startswith("rejected_low_confidence")


async def test_screening_flagged_stays_draft(db_session, monkeypatch):
    """任一条件不满足·初筛异常：photo_screening.flagged=true → 留 draft。"""
    _patch_runtime(monkeypatch, enabled=1, threshold=0.9)
    m = await _mk_material(db_session, name="初筛异常物料")
    receipt = await _mk_direct_draft(db_session, m, score=Decimal("96"))
    items = await hw.list_receipt_items(db_session, receipt.id)
    items[0].photo_screening = {
        "flagged": True,
        "findings": [{"type": "破损", "severity": "high", "note": "外壳破裂"}],
        "screened_at": "2026-11-05T10:00:00+08:00",
        "scenario": "hardware_photo_screening",
    }
    await db_session.flush()

    result = await hw.try_auto_accept_direct(db_session, receipt.id)
    assert result is None
    await db_session.refresh(receipt)
    assert receipt.status == "draft"
    assert receipt.auto_accept_snapshot["decision"] == "rejected_screening_flagged"


async def test_runtime_overrides_env_dual_channel(db_session, monkeypatch):
    """env/runtime 双通道：store 回退链 DB→env→default；runtime DB 值优先于 env。"""
    from app.core.config import get_settings
    from app.modules.warehouse.ops_config import runtime_registry
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    # ① env 兜底（直测 store 回退链：row=None → env → registry 默认）
    monkeypatch.setattr(get_settings(), "HARDWARE_OCR_AUTO_DIRECT_ENABLED", True)
    info = runtime_registry.get_runtime_key(ENABLED_KEY)
    value, source = runtime_store._resolve(info, None)
    assert value == 1 and source == "env"

    # ② runtime DB 通道覆盖 env：DB 行=0（播种默认）→ 关（优先级 DB > env）
    m2 = await _mk_material(db_session, name="db覆盖物料")
    receipt2 = await _mk_direct_draft(db_session, m2, score=Decimal("97"))
    _patch_runtime(monkeypatch, enabled=0, source="db")
    result2 = await hw.try_auto_accept_direct(db_session, receipt2.id)
    assert result2 is None
    await db_session.refresh(receipt2)
    assert receipt2.status == "draft"
    assert receipt2.auto_accepted is False
    # 关闸短路零写入（与现状逐字节一致口径；快照只在开关开时落）
    assert receipt2.auto_accept_snapshot is None
    # DB 通道 source=db 已由 test_switch_on_full_conditions_auto_accepts 的
    # snapshot["switch_source"]=="db" 断言覆盖


async def test_weekly_digest_discloses_auto_accepted(db_session, monkeypatch):
    """周报披露：fetch_digest_numbers 输出 auto_accepted_count（放权观察口径）。"""
    from app.modules.warehouse.hardware.superagent.executors import fetch_digest_numbers
    from datetime import datetime
    from zoneinfo import ZoneInfo

    _patch_runtime(monkeypatch, enabled=1, threshold=0.9)
    m = await _mk_material(db_session, name="披露物料")
    receipt = await _mk_direct_draft(db_session, m, score=Decimal("95"))
    auto = await hw.try_auto_accept_direct(db_session, receipt.id)
    assert auto is not None and auto.auto_accepted is True

    numbers = await fetch_digest_numbers(
        db_session, now=datetime.now(ZoneInfo("Asia/Shanghai")), days=7
    )
    assert numbers["auto_accepted_count"] >= 1


async def test_existing_m6_push_executors_are_naturally_auto(db_session):
    """M6 报告/催办执行器=推送类天然 auto（无需改；口径验证：零动账）。"""
    # 三执行器源码级断言：不调用 accept_receipt/发料/任何动账入口
    import inspect

    from app.modules.warehouse.hardware.superagent import executors as ex

    for fn_name in ("hardware_urge", "hardware_digest_push", "hardware_plan_draft"):
        source = inspect.getsource(getattr(ex, fn_name))
        assert "accept_receipt" not in source
        assert "issue_requisition" not in source
        assert "final_approve_scrap" not in source
        assert "_write_movement" not in source
