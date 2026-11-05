"""五金库 M7 验收测试：报废闭环（两步审批/通过销账 FIFO/驳回零动账/部分行报废
+ preferred_lot 指定）+ 实物照片初筛（advisory 标记落行/停用降级不阻塞）。

设计依据：docs/DESIGN-五金库系统原生模块-20261104.md §十一 三期 M7、§9.1（只标记
红线）；spec .scratch/hardware-store-p3/spec.md §4/§5。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.warehouse.hardware import scrap as sc
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMovement,
    HardwareReceiptItem,
)


# ── 造数工具（沿 M1 模式：uuid 后缀隔离共享开发库存量）──


async def _mk_material(db, *, name="报废物料", spec="DN25", unit="个",
                       safety=Decimal("10"), price=Decimal("8.0000")):
    from app.modules.warehouse.hardware.models import HardwareMaterial

    material = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec=spec, unit=unit,
        category="金属阀门", managed_class="stocked", safety_stock=safety,
        no_expiry=True, unit_price=price,
    )
    db.add(material)
    await db.flush()
    return material


async def _mk_inbound(db, material, qty: Decimal, *, arrived=None) -> None:
    """直接造 accepted 批次（绕过 receipt 全流程，测试聚焦报废本身）。"""
    from app.modules.warehouse.hardware.schemas import (
        ReceiptCreate,
        ReceiptItemIn,
    )

    payload = ReceiptCreate(
        source="manual", mode="stocked", supplier_name="测试供应商",
        arrived_at=arrived,
        items=[ReceiptItemIn(
            material_id=str(material.id), name=material.name,
            spec=material.spec, unit=material.unit, quantity=qty,
            match_confidence="manual", unit_price=material.unit_price,
        )],
    )
    receipt = await hw.create_receipt(db, payload)
    await hw.accept_receipt(
        db, receipt.id, inspected_by_warehouse="ou_warehouse", inspected_by_dept="ou_dept",
    )


async def _mk_draft_scrap(db, material, qty: Decimal, *, preferred_lot_id=None,
                          reason="damaged") -> Any:
    """报废草稿造数（单行；多行场景直接调 sc.create_scrap）。"""
    return await sc.create_scrap(
        db,
        dept_name="发酵",
        requested_by="张仓管",
        scrap_reason=reason,
        reason_note="测试报废",
        items=[{
            "material_id": str(material.id),
            "quantity": str(qty),
            **({"preferred_lot_id": str(preferred_lot_id)} if preferred_lot_id else {}),
        }],
    )


async def _movements_of(db, material_id) -> list[HardwareMovement]:
    return list(
        (
            await db.execute(
                select(HardwareMovement)
                .where(
                    HardwareMovement.material_id == material_id,
                    HardwareMovement.is_deleted.is_(False),
                )
                .order_by(HardwareMovement.created_at.asc())
            )
        ).scalars().all()
    )


async def _scrap_movements(db, material_id) -> list[HardwareMovement]:
    return [m for m in await _movements_of(db, material_id) if m.business_type == "scrap"]


# ── 报废闭环 ──


async def test_scrap_full_chain_fifo_deducts_lots(db_session):
    """验收①：通过销账（两步审批后）FIFO 扣批次正确——早批次先扣+scrap 流水恒正。"""
    m = await _mk_material(db_session, name="FIFO报废甲")
    await _mk_inbound(db_session, m, Decimal("10"), arrived=None)  # 早批次
    await _mk_inbound(db_session, m, Decimal("8"))                 # 晚批次

    lots = await hw.get_fifo_lots(db_session, m.id)
    assert len(lots) == 2 and lots[0].remaining_quantity == Decimal("10")

    scrap = await _mk_draft_scrap(db_session, m, Decimal("12"), reason="obsolete")
    assert scrap.scrap_no.startswith("WJK-BF-")
    assert scrap.status == "draft"

    await sc.submit_scrap(db_session, scrap.id)
    await db_session.refresh(scrap)
    assert scrap.status == "pending_dept"
    assert scrap.approval_channel == "manual"  # 未配置 feishu=自动 manual

    await sc.dept_confirm_scrap(db_session, scrap.id, confirmed_by="李主管")
    await db_session.refresh(scrap)
    assert scrap.status == "pending_final"
    assert scrap.dept_confirmed_by == "李主管"

    result = await sc.final_approve_scrap(db_session, scrap.id, approved_by="王负责人")
    await db_session.refresh(result)
    assert result.status == "approved"
    assert result.scrapped_at is not None

    # FIFO：早批次 10 扣光，晚批次扣 2 剩 6
    # （get_fifo_lots 只回余额>0 批次——扣光批次直查行断言）
    rows = (
        await db_session.execute(
            select(HardwareReceiptItem).where(
                HardwareReceiptItem.material_id == m.id,
                HardwareReceiptItem.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    remaining_by_lot = {r.id: r.remaining_quantity for r in rows}
    assert remaining_by_lot[lots[0].id] == Decimal("0")
    assert remaining_by_lot[lots[1].id] == Decimal("6")

    # scrap 流水：数量恒正、方向 outbound、ref 指向报废单
    scrap_mvs = await _scrap_movements(db_session, m.id)
    assert len(scrap_mvs) == 2  # 逐批两条
    total = sum(mv.quantity for mv in scrap_mvs)
    assert total == Decimal("12")
    assert all(mv.direction == "outbound" for mv in scrap_mvs)
    assert all(mv.quantity > 0 for mv in scrap_mvs)
    assert all(mv.ref_table == "hardware_scraps" and mv.ref_id == scrap.id for mv in scrap_mvs)

    # 库存口径：on_hand=8−... 早10+晚8=18，报废12 → 6
    detail = await hw.get_material_stock(db_session, m.id)
    assert detail["on_hand"] == Decimal("6")

    # 批次扣减结果留档
    assert result.lot_allocations is not None and len(result.lot_allocations) == 2


async def test_scrap_reject_zero_movements(db_session):
    """验收②：驳回零动账——pending_dept 驳回，批次/流水均不动。"""
    m = await _mk_material(db_session, name="驳回报废乙")
    await _mk_inbound(db_session, m, Decimal("5"))
    movements_before = await _movements_of(db_session, m.id)
    lots_before = await hw.get_fifo_lots(db_session, m.id)

    scrap = await _mk_draft_scrap(db_session, m, Decimal("3"), reason="damaged")
    await sc.submit_scrap(db_session, scrap.id)
    rejected = await sc.reject_scrap(
        db_session, scrap.id, rejected_by="李主管", reason="照片不足，补充留证后再报"
    )
    await db_session.refresh(rejected)
    assert rejected.status == "rejected"
    assert rejected.approval_status == "rejected"
    assert rejected.rejected_by == "李主管"

    # 零动账：无 scrap 流水、批次余额不变
    assert await _scrap_movements(db_session, m.id) == []
    assert len(await _movements_of(db_session, m.id)) == len(movements_before)
    lots_after = await hw.get_fifo_lots(db_session, m.id)
    assert lots_after[0].remaining_quantity == lots_before[0].remaining_quantity

    # 终审已批准单不可再驳
    scrap2 = await _mk_draft_scrap(db_session, m, Decimal("1"), reason="damaged")
    await sc.submit_scrap(db_session, scrap2.id)
    await sc.dept_confirm_scrap(db_session, scrap2.id, confirmed_by="李主管")
    await sc.final_approve_scrap(db_session, scrap2.id, approved_by="王负责人")
    with pytest.raises(hw.HardwareError):
        await sc.reject_scrap(db_session, scrap2.id, rejected_by="任何人", reason=" late")


async def test_scrap_partial_lines_preferred_lot(db_session):
    """验收③：部分行报废+preferred_lot 指定——指定批次优先扣，未指定行走 FIFO。"""
    m = await _mk_material(db_session, name="部分行报废丙")
    await _mk_inbound(db_session, m, Decimal("10"))  # FIFO 首批次
    await _mk_inbound(db_session, m, Decimal("6"))   # 晚批次
    lots = await hw.get_fifo_lots(db_session, m.id)
    later_lot = lots[1]

    # 行1：指定晚批次报废 4（应扣晚批次而非 FIFO 首批次）；行2：未指定报废 2（走 FIFO 首批次）
    scrap = await sc.create_scrap(
        db_session,
        dept_name="发酵",
        requested_by="张仓管",
        scrap_reason="damaged",
        items=[
            {"material_id": str(m.id), "quantity": "4", "preferred_lot_id": str(later_lot.id)},
            {"material_id": str(m.id), "quantity": "2"},
        ],
    )
    await sc.submit_scrap(db_session, scrap.id)
    await sc.dept_confirm_scrap(db_session, scrap.id, confirmed_by="李主管")
    result = await sc.final_approve_scrap(db_session, scrap.id, approved_by="王负责人")

    rows_after = (
        await db_session.execute(
            select(HardwareReceiptItem).where(
                HardwareReceiptItem.material_id == m.id,
                HardwareReceiptItem.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    lots_after = {l.id: l for l in rows_after}
    # 指定行扣晚批次 6→2；FIFO 行扣首批次 10→8
    assert lots_after[later_lot.id].remaining_quantity == Decimal("2")
    assert lots_after[lots[0].id].remaining_quantity == Decimal("8")
    # 结果留档 mode 区分
    modes = {a["mode"] for a in result.lot_allocations}
    assert modes == {"preferred", "fifo"}


async def test_scrap_state_gates_and_lot_validation(db_session):
    """状态机闸：未部门确认不可终审；指定批次无效/余额不足拦截；direct 物料拦截。"""
    m = await _mk_material(db_session, name="闸门报废丁")
    await _mk_inbound(db_session, m, Decimal("3"))

    # draft 直接终审 = 拒绝
    scrap = await _mk_draft_scrap(db_session, m, Decimal("1"), reason="expired")
    with pytest.raises(hw.HardwareError):
        await sc.final_approve_scrap(db_session, scrap.id, approved_by="王负责人")
    # draft 直接部门确认 = 拒绝（须先提交）
    with pytest.raises(hw.HardwareError):
        await sc.dept_confirm_scrap(db_session, scrap.id, confirmed_by="李主管")

    # 指定批次余额不足（报 3 只有余 3 的批次？不：批次余 3，报废 2 合法；造报废 5 拦截）
    lots = await hw.get_fifo_lots(db_session, m.id)
    scrap2 = await sc.create_scrap(
        db_session,
        dept_name="发酵",
        requested_by="张仓管",
        scrap_reason="damaged",
        items=[{
            "material_id": str(m.id), "quantity": "5",
            "preferred_lot_id": str(lots[0].id),
        }],
    )
    await sc.submit_scrap(db_session, scrap2.id)
    await sc.dept_confirm_scrap(db_session, scrap2.id, confirmed_by="李主管")
    with pytest.raises(hw.HardwareError, match="余额不足"):
        await sc.final_approve_scrap(db_session, scrap2.id, approved_by="王负责人")
    await db_session.refresh(scrap2)
    assert scrap2.status == "pending_final"  # 失败不动状态（事务回滚语义由调用方定）

    # 指定不存在的批次 = 拦截
    scrap3 = await sc.create_scrap(
        db_session,
        dept_name="发酵",
        requested_by="张仓管",
        scrap_reason="damaged",
        items=[{"material_id": str(m.id), "quantity": "1", "preferred_lot_id": str(uuid4())}],
    )
    await sc.submit_scrap(db_session, scrap3.id)
    await sc.dept_confirm_scrap(db_session, scrap3.id, confirmed_by="李主管")
    with pytest.raises(hw.HardwareError, match="指定批次无效"):
        await sc.final_approve_scrap(db_session, scrap3.id, approved_by="王负责人")

    # direct 物料拦截 + 非法条件拦截
    from app.modules.warehouse.hardware.models import HardwareMaterial

    direct = HardwareMaterial(
        name=f"direct物料·{uuid4().hex[:6].upper()}", unit="个",
        category="耗材", managed_class="direct", safety_stock=Decimal("0"),
    )
    db_session.add(direct)
    await db_session.flush()
    with pytest.raises(hw.HardwareError, match="车间单独需求类"):
        await _mk_draft_scrap(db_session, direct, Decimal("1"))
    with pytest.raises(hw.HardwareError, match="未知报废条件"):
        await sc.create_scrap(
            db_session, dept_name="发酵", requested_by="张", scrap_reason="other",
            items=[{"material_id": str(m.id), "quantity": "1"}],
        )


async def test_scrap_scrap_reason_four_options(db_session):
    """四条件单选全量可发起（制度 5.6：expired/damaged/obsolete/appraisal）。"""
    for reason in ("expired", "damaged", "obsolete", "appraisal"):
        m = await _mk_material(db_session, name=f"四条件{reason}")
        await _mk_inbound(db_session, m, Decimal("2"))
        scrap = await _mk_draft_scrap(db_session, m, Decimal("1"), reason=reason)
        assert scrap.scrap_reason == reason


# ── 实物照片初筛（Ticket 02）──


def _vision_stub(payload: dict[str, Any]):
    """构造 chat_with_tools 桩（返回固定 JSON 文本；plan_annotation 同款模式）。"""

    class _Stub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def chat_with_tools(self, *args, **kwargs):
            class _Msg:
                content = payload if isinstance(payload, str) else _json_dumps(payload)

            return _Msg()

    def _json_dumps(obj):
        import json

        return json.dumps(obj, ensure_ascii=False)

    return _Stub()


async def _mk_ocr_receipt(db, *, n_rows: int = 2) -> tuple[Any, list[str]]:
    """造 OCR 草稿单（多行，供初筛标记落行）；返回 (receipt, 行名列表)。

    行名带唯一后缀——同事务行 created_at 相同排序不稳定，断言按业务键定位
    （测试纪律：不按位置断言共享库行序）。
    """
    from app.modules.warehouse.hardware.schemas import (
        ReceiptCreate,
        ReceiptItemIn,
    )

    names = [f"初筛行{i}·{uuid4().hex[:6].upper()}" for i in range(n_rows)]
    payload = ReceiptCreate(
        source="ocr", mode="stocked", supplier_name="初筛供应商",
        items=[
            ReceiptItemIn(
                name=names[i], quantity=Decimal(f"{i + 1}"),
                match_confidence="unmatched",
            )
            for i in range(n_rows)
        ],
    )
    return await hw.create_receipt(db, payload), names


async def test_photo_screening_marks_rows(db_session, monkeypatch):
    """初筛标记落行：vision 返回 findings → 行 photo_screening.flagged 落库（只标记）。"""
    from app.modules.warehouse.hardware import photo_screening as ps

    receipt, row_names = await _mk_ocr_receipt(db_session, n_rows=2)
    # 钉死场景开（共享开发库 ai_scenario_configs 行会被并发会话读写，不依赖真行状态）
    monkeypatch.setattr(ps.scenario_store, "is_enabled", lambda s: True)
    monkeypatch.setattr(
        ps, "get_llm_client", lambda: _vision_stub({
            "rows": [
                {"row_index": 0, "findings": [
                    {"type": "破损", "severity": "high", "note": "外包装压溃，内容物可见"},
                ]},
                {"row_index": 1, "findings": []},
            ],
            "overall": "第 1 行疑似破损",
        })
    )
    summary = await ps.screen_receipt_photos(
        db_session, receipt.id,
        photos=[{"file_token": "tok1", "image_b64": "aGVsbG8=", "content_type": "image/jpeg"}],
    )
    assert summary["screened"] is True, f"summary={summary}"
    assert summary["flagged_rows"] == 1

    items = await hw.list_receipt_items(db_session, receipt.id)
    # 按业务键（行名）定位：同事务行 created_at 相同、DB 排序不稳定
    flagged_item = next(i for i in items if i.name == row_names[0])
    clean_item = next(i for i in items if i.name == row_names[1])
    assert flagged_item.photo_screening is not None
    assert flagged_item.photo_screening["flagged"] is True
    assert flagged_item.photo_screening["findings"][0]["type"] == "破损"
    # 无异常行：落 screened 空发现（不是 NULL——初筛过=有结论）
    assert clean_item.photo_screening is not None
    assert clean_item.photo_screening["flagged"] is False
    assert clean_item.photo_screening["findings"] == []


async def test_photo_screening_disabled_no_block(db_session, monkeypatch):
    """场景停用 → 无标记不阻塞（返回 screened=False，行保持 NULL）。"""
    from app.modules.warehouse.hardware import photo_screening as ps

    receipt, _names = await _mk_ocr_receipt(db_session, n_rows=1)
    monkeypatch.setattr(ps.scenario_store, "is_enabled", lambda s: False)
    summary = await ps.screen_receipt_photos(
        db_session, receipt.id,
        photos=[{"file_token": "tok1", "image_b64": "aGVsbG8=", "content_type": "image/jpeg"}],
    )
    assert summary["screened"] is False
    assert summary["reason"] == "scenario_disabled"
    items = await hw.list_receipt_items(db_session, receipt.id)
    assert all(i.photo_screening is None for i in items)


async def test_photo_screening_llm_failure_no_block(db_session, monkeypatch):
    """LLM 挂死 → 无标记不阻塞（沿 plan_annotation 降级红线）。"""
    from app.modules.warehouse.hardware import photo_screening as ps

    receipt, _names = await _mk_ocr_receipt(db_session, n_rows=1)

    class _Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def chat_with_tools(self, *args, **kwargs):
            raise RuntimeError("LLM down（测试注入）")

    monkeypatch.setattr(ps, "get_llm_client", lambda: _Boom())
    summary = await ps.screen_receipt_photos(
        db_session, receipt.id,
        photos=[{"file_token": "tok1", "image_b64": "aGVsbG8=", "content_type": "image/jpeg"}],
    )
    assert summary["screened"] is False
    assert summary["reason"] == "llm_error"
    items = await hw.list_receipt_items(db_session, receipt.id)
    assert all(i.photo_screening is None for i in items)


async def test_photo_screening_bad_json_no_block(db_session, monkeypatch):
    """LLM 输出非 JSON → 无标记不阻塞（不抛错）。"""
    from app.modules.warehouse.hardware import photo_screening as ps

    receipt, _names = await _mk_ocr_receipt(db_session, n_rows=1)
    monkeypatch.setattr(ps, "get_llm_client", lambda: _vision_stub("这不是JSON输出"))
    summary = await ps.screen_receipt_photos(
        db_session, receipt.id,
        photos=[{"file_token": "tok1", "image_b64": "aGVsbG8=", "content_type": "image/jpeg"}],
    )
    assert summary["screened"] is False
    assert summary["reason"] == "llm_error"
