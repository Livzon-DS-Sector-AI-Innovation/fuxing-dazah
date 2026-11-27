"""五金库 M7 验收测试：报废出库并入申领出库全路径（2026-11-25）——提交即预扣 /
审批通过不动库存（飞书回流与平台通过共用）/ 仓管出库才实扣（FIFO、指定批次）/
驳回撤回释放预扣 / 合并列表与平台审批权限 + 实物照片初筛（advisory 标记落行/
停用降级不阻塞）。

设计依据：docs/DESIGN-五金库系统原生模块-20261104.md §十一 三期 M7、§9.1（只标记
红线）；spec .scratch/hardware-store-p3/spec.md §4/§5。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.warehouse.hardware import scrap as sc
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMovement,
    HardwareReceiptItem,
)

BASE = "/api/v1/warehouse/hardware"


# ── 造数工具（沿 M1 模式：uuid 后缀隔离共享开发库存量）──


def _patch_runtime(monkeypatch, values: dict) -> None:
    """runtime_store 单例替身：固定值表（审批配置已迁系统配置，2026-11-26）。"""
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    monkeypatch.setattr(
        runtime_store, "get_value", lambda key: values.get(key)
    )


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
                          reason="damaged", approver_user_id=None, approver_name=None) -> Any:
    """报废草稿造数（单行；多行场景直接调 sc.create_scrap）。"""
    return await sc.create_scrap(
        db,
        dept_name="发酵",
        requested_by="张仓管",
        scrap_reason=reason,
        reason_note="测试报废",
        approver_user_id=approver_user_id,
        approver_name=approver_name,
        items=[{
            "material_id": str(material.id),
            "quantity": str(qty),
            **({"preferred_lot_id": str(preferred_lot_id)} if preferred_lot_id else {}),
        }],
    )


async def _to_pending(db, scrap: Any, *, approver_user_id: str | None = "u_approver",
                      approver_name: str = "赵审批") -> Any:
    """草稿 → 待审批（同申领「确定即提交」；未配置飞书分支=审批人在平台点通过）。"""
    if not scrap.approver_user_id and approver_user_id:
        scrap.approver_user_id = approver_user_id
        scrap.approver_name = approver_name
        await db.flush()
    return await sc.submit_scrap(db, scrap.id)


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


async def _remaining_by_lot(db, material_id) -> dict[Any, Decimal]:
    rows = (
        await db.execute(
            select(HardwareReceiptItem).where(
                HardwareReceiptItem.material_id == material_id,
                HardwareReceiptItem.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    return {r.id: r.remaining_quantity for r in rows}


# ── 报废出库全路径（服务层）──


async def test_scrap_full_path_matches_requisition(db_session):
    """验收①（同申领全路径）：提交即预扣 → 审批通过不动库存 → 仓管出库 FIFO 实扣。"""
    m = await _mk_material(db_session, name="全路径报废甲")
    await _mk_inbound(db_session, m, Decimal("10"), arrived=None)  # 早批次
    await _mk_inbound(db_session, m, Decimal("8"))                 # 晚批次
    lots = await hw.get_fifo_lots(db_session, m.id)
    assert len(lots) == 2

    scrap = await _mk_draft_scrap(db_session, m, Decimal("12"), reason="obsolete")
    assert scrap.scrap_no.startswith("WJK-BF-") and scrap.status == "draft"
    assert await hw.available_of_material(db_session, m.id) == Decimal("18")  # 草稿不预扣

    # ① 提交：预扣生效（可用 18→6），不动批次、无流水
    await _to_pending(db_session, scrap)
    await db_session.refresh(scrap)
    assert scrap.status == "pending"
    assert scrap.approval_channel == "manual"  # 未配置飞书分支=审批人在平台点通过
    assert await hw.available_of_material(db_session, m.id) == Decimal("6")
    assert await _scrap_movements(db_session, m.id) == []

    # ② 审批人通过：进待出库，预扣保持、库存不动
    approved = await sc.approve_scrap(db_session, scrap.id, approved_by="赵审批")
    await db_session.refresh(approved)
    assert approved.status == "approved"
    assert approved.approved_by == "赵审批"
    assert await hw.available_of_material(db_session, m.id) == Decimal("6")
    assert await _scrap_movements(db_session, m.id) == []

    # ③ 仓管出库：FIFO 扣批次（早批次 10 扣光、晚批次扣 2 剩 6）+ scrap 流水
    issued = await sc.execute_scrap(db_session, scrap.id, executed_by="钱仓管")
    await db_session.refresh(issued)
    assert issued.status == "issued"
    assert issued.scrapped_at is not None and issued.executed_by == "钱仓管"
    remaining = await _remaining_by_lot(db_session, m.id)
    assert remaining[lots[0].id] == Decimal("0")
    assert remaining[lots[1].id] == Decimal("6")

    scrap_mvs = await _scrap_movements(db_session, m.id)
    assert len(scrap_mvs) == 2  # 逐批两条
    assert sum(mv.quantity for mv in scrap_mvs) == Decimal("12")
    assert all(mv.direction == "outbound" and mv.quantity > 0 for mv in scrap_mvs)
    assert all(mv.ref_table == "hardware_scraps" and mv.ref_id == scrap.id for mv in scrap_mvs)

    # 库存口径：预扣转实扣（在手 18→6，可用仍 6）
    detail = await hw.get_material_stock(db_session, m.id)
    assert detail["on_hand"] == Decimal("6")
    assert await hw.available_of_material(db_session, m.id) == Decimal("6")
    assert issued.lot_allocations is not None and len(issued.lot_allocations) == 2


async def test_scrap_reject_and_cancel_release_reservation(db_session):
    """验收②：驳回/撤回释放预扣且零动账；状态闸（仅待审批可驳回/撤回）。"""
    m = await _mk_material(db_session, name="驳回报废乙")
    await _mk_inbound(db_session, m, Decimal("5"))
    before = await _remaining_by_lot(db_session, m.id)

    scrap = await _mk_draft_scrap(db_session, m, Decimal("3"), reason="damaged")
    await _to_pending(db_session, scrap)
    assert await hw.available_of_material(db_session, m.id) == Decimal("2")
    rejected = await sc.reject_scrap(
        db_session, scrap.id, rejected_by="赵审批", reason="照片不足，补充留证后再报"
    )
    await db_session.refresh(rejected)
    assert rejected.status == "rejected"
    assert rejected.approval_status == "rejected"
    assert rejected.rejected_by == "赵审批"
    assert await hw.available_of_material(db_session, m.id) == Decimal("5")
    assert await _scrap_movements(db_session, m.id) == []
    assert await _remaining_by_lot(db_session, m.id) == before
    with pytest.raises(hw.HardwareError):
        await sc.reject_scrap(db_session, scrap.id, rejected_by="任何人", reason="重复驳回")

    # 撤回：释放预扣
    scrap2 = await _mk_draft_scrap(db_session, m, Decimal("2"))
    await _to_pending(db_session, scrap2)
    assert await hw.available_of_material(db_session, m.id) == Decimal("3")
    cancelled = await sc.cancel_scrap(db_session, scrap2.id)
    await db_session.refresh(cancelled)
    assert cancelled.status == "cancelled"
    assert await hw.available_of_material(db_session, m.id) == Decimal("5")

    # 已到待出库：不可驳回、不可撤回
    scrap3 = await _mk_draft_scrap(db_session, m, Decimal("1"))
    await _to_pending(db_session, scrap3)
    await sc.approve_scrap(db_session, scrap3.id, approved_by="赵审批")
    with pytest.raises(hw.HardwareError):
        await sc.reject_scrap(db_session, scrap3.id, rejected_by="赵审批", reason="late")
    with pytest.raises(hw.HardwareError):
        await sc.cancel_scrap(db_session, scrap3.id)


async def test_scrap_partial_lines_preferred_lot(db_session):
    """验收③：部分行报废 + preferred_lot 指定——指定批次优先扣，未指定行走 FIFO。"""
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
    await _to_pending(db_session, scrap)
    await sc.approve_scrap(db_session, scrap.id, approved_by="赵审批")
    result = await sc.execute_scrap(db_session, scrap.id, executed_by="钱仓管")

    remaining = await _remaining_by_lot(db_session, m.id)
    # 指定行扣晚批次 6→2；FIFO 行扣首批次 10→8
    assert remaining[later_lot.id] == Decimal("2")
    assert remaining[lots[0].id] == Decimal("8")
    # 结果留档 mode 区分
    assert {a["mode"] for a in result.lot_allocations} == {"preferred", "fifo"}


async def test_scrap_state_gates_and_lot_validation(db_session):
    """状态闸：未审批不可出库；提交超可领量拦截；指定批次无效/余额不足在出库时拦截。"""
    m = await _mk_material(db_session, name="闸门报废丁")
    await _mk_inbound(db_session, m, Decimal("3"))

    scrap = await _mk_draft_scrap(db_session, m, Decimal("1"), reason="expired")
    with pytest.raises(hw.HardwareError):
        await sc.approve_scrap(db_session, scrap.id, approved_by="赵审批")  # 草稿不可审批
    with pytest.raises(hw.HardwareError):
        await sc.execute_scrap(db_session, scrap.id, executed_by="钱仓管")  # 草稿不可出库

    # 提交超可领量 = 拦截
    over = await _mk_draft_scrap(db_session, m, Decimal("5"))
    with pytest.raises(hw.HardwareError, match="可报废量不足"):
        await sc.submit_scrap(db_session, over.id)

    # 待审批不可出库；通过后不可重复审批
    await _to_pending(db_session, scrap)
    with pytest.raises(hw.HardwareError, match="审批通过后才可出库"):
        await sc.execute_scrap(db_session, scrap.id, executed_by="钱仓管")
    await sc.approve_scrap(db_session, scrap.id, approved_by="赵审批")
    with pytest.raises(hw.HardwareError):
        await sc.approve_scrap(db_session, scrap.id, approved_by="赵审批")

    # 预扣只按数量不锁批次：待出库期间指定批次被调少 → 出库时按批次拦截、状态不变
    m2 = await _mk_material(db_session, name="闸门批次戊")
    await _mk_inbound(db_session, m2, Decimal("3"))
    lots = await hw.get_fifo_lots(db_session, m2.id)
    scrap2 = await _mk_draft_scrap(
        db_session, m2, Decimal("3"), preferred_lot_id=lots[0].id
    )
    await _to_pending(db_session, scrap2)
    await sc.approve_scrap(db_session, scrap2.id, approved_by="赵审批")
    lot_row = await db_session.get(HardwareReceiptItem, lots[0].id)
    lot_row.remaining_quantity = Decimal("2")
    await db_session.flush()
    with pytest.raises(hw.HardwareError, match="余额不足"):
        await sc.execute_scrap(db_session, scrap2.id, executed_by="钱仓管")
    await db_session.refresh(scrap2)
    assert scrap2.status == "approved"
    assert await _scrap_movements(db_session, m2.id) == []

    # 指定不存在的批次 = 出库时拦截
    m3 = await _mk_material(db_session, name="闸门批次己")
    await _mk_inbound(db_session, m3, Decimal("2"))
    scrap3 = await _mk_draft_scrap(db_session, m3, Decimal("1"), preferred_lot_id=uuid4())
    await _to_pending(db_session, scrap3)
    await sc.approve_scrap(db_session, scrap3.id, approved_by="赵审批")
    with pytest.raises(hw.HardwareError, match="指定批次无效"):
        await sc.execute_scrap(db_session, scrap3.id, executed_by="钱仓管")

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


async def test_scrap_submit_feishu_branch(db_session, monkeypatch):
    """飞书分支已配置：提交即把审批单发给所选审批人；未选审批人/发起失败停在草稿。"""
    from app.modules.warehouse.hardware import approval_channel as ac

    calls: list[dict[str, Any]] = []

    class _Channel:
        name = "feishu"

        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail

        async def submit_scrap(self, db, s, items):
            calls.append({"scrap_id": s.id, "approver": s.approver_user_id, "rows": len(items)})
            if self.fail:
                raise ac.ApprovalChannelError("实例创建失败（测试注入）")
            s.approval_channel = "feishu"
            s.approval_instance_code = "INST_SCRAP_TEST"
            s.approval_status = "pending"
            await db.flush()
            return "INST_SCRAP_TEST"

    m = await _mk_material(db_session, name="飞书分支己")
    await _mk_inbound(db_session, m, Decimal("5"))
    monkeypatch.setattr(ac, "get_scrap_approval_channel", lambda: _Channel())

    # 未选审批人 → 拦截，停在草稿、不预扣
    scrap = await _mk_draft_scrap(db_session, m, Decimal("2"))
    with pytest.raises(hw.HardwareError, match="未选择审批人"):
        await sc.submit_scrap(db_session, scrap.id)
    await db_session.refresh(scrap)
    assert scrap.status == "draft"
    assert await hw.available_of_material(db_session, m.id) == Decimal("5")

    # 实例创建失败 → 上抛，停在草稿、不预扣（不静默降级，同申领）
    scrap.approver_user_id = "u_approver"
    scrap.approver_name = "赵审批"
    await db_session.flush()
    monkeypatch.setattr(ac, "get_scrap_approval_channel", lambda: _Channel(fail=True))
    with pytest.raises(hw.HardwareError, match="飞书审批发起失败"):
        await sc.submit_scrap(db_session, scrap.id)
    await db_session.refresh(scrap)
    assert scrap.status == "draft"
    assert await hw.available_of_material(db_session, m.id) == Decimal("5")

    # 发起成功：待审批 + 飞书通道 + 实例 code + 预扣
    monkeypatch.setattr(ac, "get_scrap_approval_channel", lambda: _Channel())
    submitted = await sc.submit_scrap(db_session, scrap.id)
    await db_session.refresh(submitted)
    assert submitted.status == "pending"
    assert submitted.approval_channel == "feishu"
    assert submitted.approval_instance_code == "INST_SCRAP_TEST"
    assert await hw.available_of_material(db_session, m.id) == Decimal("3")
    assert calls[-1] == {"scrap_id": scrap.id, "approver": "u_approver", "rows": 1}


async def test_scrap_feishu_backflow_and_platform_first(db_session, monkeypatch):
    """飞书回流 APPROVED → 待出库（不动库存）；平台先通过则撤回实例，之后飞书结论只留痕。"""
    import app.platform.integrations.feishu.approval as approval_mod
    from app.core.config import get_settings
    from app.modules.warehouse.hardware import approval_channel as ac
    from app.modules.warehouse.hardware import approval_ingest as ai

    m = await _mk_material(db_session, name="回流审批庚")
    await _mk_inbound(db_session, m, Decimal("6"))
    _patch_runtime(monkeypatch, {"hardware_approval_code": "TEST-CODE"})
    monkeypatch.setattr(
        ac.FeishuApprovalChannel, "_credentials", staticmethod(lambda: ("id", "secret"))
    )

    async def _feishu_pending(qty: str, instance: str) -> Any:
        s = await _mk_draft_scrap(
            db_session, m, Decimal(qty), approver_user_id="u_approver", approver_name="赵审批"
        )
        await _to_pending(db_session, s)
        s.approval_channel = "feishu"
        s.approval_instance_code = instance
        s.requested_by_open_id = "ou_starter"
        await db_session.flush()
        return s

    # 飞书先通过（主管批+办理完=实例 APPROVED）：自动出库实扣（同申领口径）
    scrap = await _feishu_pending("2", "INST-A")
    result = await ai.sync_status(db_session, "INST-A", status="APPROVED")
    assert result == {"action": "synced", "doc_no": scrap.scrap_no, "status": "issued"}
    await db_session.refresh(scrap)
    assert scrap.status == "issued"
    assert scrap.executed_by == "飞书审批·仓管办理"
    assert scrap.scrapped_at is not None
    # 预扣转实扣：在手 6→4，可用仍 4；流水已落
    assert await hw.available_of_material(db_session, m.id) == Decimal("4")
    assert len(await _scrap_movements(db_session, m.id)) == 1

    # 平台先通过：撤回未决飞书实例（best-effort），进待出库
    scrap2 = await _feishu_pending("1", "INST-B")
    fake = AsyncMock(return_value=True)
    with patch.object(approval_mod, "cancel_instance", fake):
        approved = await sc.approve_scrap(
            db_session, scrap2.id, approved_by="赵审批", withdraw_instance=True
        )
    await db_session.refresh(approved)
    assert approved.status == "approved"
    assert approved.approval_status == "approved"
    assert fake.await_count == 1
    assert fake.await_args.args[:3] == ("TEST-CODE", "INST-B", "ou_starter")

    # 之后飞书才出结论：只留痕（且只记一次），不改状态、不动库存
    for _ in range(2):
        await ai.sync_status(db_session, "INST-B", status="APPROVED")
    await ai.sync_status(db_session, "INST-B", status="REJECTED")
    await db_session.refresh(scrap2)
    assert scrap2.status == "approved"
    assert (scrap2.remark or "").count("飞书审批单后续通过") == 1
    assert (scrap2.remark or "").count("飞书审批单后续驳回") == 1
    assert len(await _scrap_movements(db_session, m.id)) == 1
    assert await hw.available_of_material(db_session, m.id) == Decimal("3")

    # 飞书驳回 / 撤销：待审批 → 已驳回 / 已撤回，释放预扣
    scrap3 = await _feishu_pending("1", "INST-C")
    assert (await ai.sync_status(db_session, "INST-C", status="REJECTED"))["status"] == "rejected"
    await db_session.refresh(scrap3)
    assert scrap3.status == "rejected" and scrap3.approval_status == "rejected"
    scrap4 = await _feishu_pending("1", "INST-D")
    assert (await ai.sync_status(db_session, "INST-D", status="CANCELED"))["status"] == "cancelled"
    await db_session.refresh(scrap4)
    assert scrap4.status == "cancelled"
    assert await hw.available_of_material(db_session, m.id) == Decimal("3")


def test_scrap_can_user_approve_rule():
    """平台通过资格：持「报废管理」权限，或被选为该单审批人（identity.feishu_user_id 一致）。"""
    scrap = sc.HardwareScrap(
        scrap_no="WJK-BF-TEST", dept_name="发酵", requested_by="张三",
        scrap_reason="damaged", status="pending", approver_user_id="u_approver",
    )

    class _User:
        id = "u1"
        name = "张三"
        feishu_user_id = "u_approver"

    manage = {"warehouse:hardware:scrap:manage"}
    assert sc.can_user_approve_scrap(scrap, user=_User(), perms=manage)
    assert sc.can_user_approve_scrap(scrap, user=_User(), perms=set())  # 所选审批人本人
    assert sc.can_user_approve_scrap(scrap, user=None, perms=set()) is False
    _User.feishu_user_id = "u_other"
    assert sc.can_user_approve_scrap(
        scrap, user=_User(), perms={"warehouse:hardware:scrap:read"}
    ) is False
    scrap.approver_user_id = None
    assert sc.can_user_approve_scrap(scrap, user=_User(), perms=set()) is False


# ── 合并列表 / 库存列表预扣 / 平台审批权限（HTTP）──

HARDWARE_PERMS = frozenset({
    "warehouse:hardware:stock:read",
    "warehouse:hardware:requisition:read",
    "warehouse:hardware:requisition:create",
    "warehouse:hardware:scrap:read",
    "warehouse:hardware:scrap:manage",
})


@pytest.fixture
async def hardware_api(api_context):
    """api_context 之上放行五金库权限（conftest 的 WAREHOUSE_PERMS 只含主仓权限码）。"""
    async def _grant(user_id: str, db: object) -> set[str]:
        return set(HARDWARE_PERMS)

    with patch("app.platform.permission.deps.get_user_permissions", new=_grant):
        yield api_context


async def _stock_row(client, material) -> dict[str, Any]:
    resp = await client.get(f"{BASE}/stock", params={"keyword": material.name, "page_size": 50})
    assert resp.status_code == 200
    row = next(r for r in resp.json()["data"] if r["material"]["id"] == str(material.id))
    # 接口把 Decimal 序列化成字符串，这里统一成 Decimal 再比较
    for key in ("on_hand", "reserved", "available"):
        row[key] = Decimal(str(row[key]))
    return row


async def _doc_ids(client, status: str) -> set[tuple[str, str]]:
    resp = await client.get(f"{BASE}/outbound-docs", params={"status": status, "page_size": 200})
    assert resp.status_code == 200
    return {(r["doc_kind"], r["id"]) for r in resp.json()["data"]}


class TestScrapOutboundPathApi:
    async def test_submit_reserve_approve_issue_over_http(self, hardware_api) -> None:
        """页面同路径：确定即提交 → 库存列表预扣 → 待审批页签 → 通过 → 待发料页签 → 出库实扣。"""
        client, db = hardware_api
        m = await _mk_material(db, name="接口全路径甲")
        await _mk_inbound(db, m, Decimal("5"))
        scrap = await _mk_draft_scrap(
            db, m, Decimal("2"), approver_user_id="u_approver", approver_name="赵审批"
        )

        # 确定即提交（同申领）：预扣生效
        resp = await client.post(f"{BASE}/scraps/{scrap.id}/submit", json={})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "pending"
        row = await _stock_row(client, m)
        assert (row["on_hand"], row["reserved"], row["available"]) == (5, 2, 3)

        # 同页再造一张领料单：两类单据进同一个「待审批」
        resp = await client.post(
            f"{BASE}/requisitions",
            json={
                "dept_name": "发酵", "applicant": "测试员", "approver_user_id": "u_approver",
                "items": [{"material_id": str(m.id), "need_qty": 1}],
            },
        )
        assert resp.status_code == 201
        req_id = resp.json()["data"]["id"]
        resp = await client.post(f"{BASE}/requisitions/{req_id}/submit", json={})
        assert resp.status_code == 200
        assert await _doc_ids(client, "pending") >= {("scrap", str(scrap.id)), ("requisition", req_id)}

        resp = await client.get(f"{BASE}/outbound-docs", params={"status": "pending", "page_size": 200})
        body = resp.json()
        rows = {(r["doc_kind"], r["id"]): r for r in body["data"]}
        scrap_row = rows[("scrap", str(scrap.id))]
        assert scrap_row["requisition"] is None
        assert scrap_row["scrap"]["scrap_no"] == scrap.scrap_no
        assert scrap_row["scrap"]["approver_name"] == "赵审批"
        assert scrap_row["scrap"]["can_approve"] is True  # 持报废管理权限
        req_row = rows[("requisition", req_id)]
        assert req_row["scrap"] is None and req_row["requisition"]["id"] == req_id
        assert body["meta"]["total"] >= 2

        # 审批人平台点通过：进「待发料」页签，库存不动
        resp = await client.post(f"{BASE}/scraps/{scrap.id}/approve", json={})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "approved"
        assert ("scrap", str(scrap.id)) in await _doc_ids(client, "approved")
        assert ("scrap", str(scrap.id)) not in await _doc_ids(client, "pending")
        row = await _stock_row(client, m)
        assert (row["on_hand"], row["reserved"]) == (5, 3)  # 报废 2 + 领料 1，均未实扣

        # 仓管出库：实扣，进「已发料」页签
        resp = await client.post(f"{BASE}/scraps/{scrap.id}/execute", json={"executed_by": "web"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "issued"
        assert len(data["lot_allocations"]) == 1
        assert ("scrap", str(scrap.id)) in await _doc_ids(client, "issued")
        row = await _stock_row(client, m)
        assert (row["on_hand"], row["reserved"], row["available"]) == (3, 1, 2)

    async def test_approve_requires_manage_perm_or_designated_approver(
        self, hardware_api, test_user
    ) -> None:
        """平台通过/驳回准入：报废管理权限 或 被选为该单审批人；否则 403。"""
        client, db = hardware_api
        if not test_user.feishu_user_id:
            pytest.skip("测试用户无 feishu_user_id，无法验证所选审批人通道")
        m = await _mk_material(db, name="接口权限乙")
        await _mk_inbound(db, m, Decimal("5"))
        scrap = await _mk_draft_scrap(
            db, m, Decimal("1"), approver_user_id="u_someone_else", approver_name="别人"
        )
        resp = await client.post(f"{BASE}/scraps/{scrap.id}/submit", json={})
        assert resp.status_code == 200

        async def _read_only(user_id: str, db_obj: object) -> set[str]:
            return {"warehouse:hardware:scrap:read"}

        with patch("app.platform.permission.deps.get_user_permissions", new=_read_only):
            detail = (await client.get(f"{BASE}/scraps/{scrap.id}")).json()["data"]
            assert detail["can_approve"] is False
            resp = await client.post(f"{BASE}/scraps/{scrap.id}/approve", json={})
            assert resp.status_code == 403
            resp = await client.post(f"{BASE}/scraps/{scrap.id}/reject", json={"reason": "不同意"})
            assert resp.status_code == 403

            # 被选为该单审批人 → 可在平台通过，审批人记为登录用户
            scrap.approver_user_id = test_user.feishu_user_id
            await db.flush()
            detail = (await client.get(f"{BASE}/scraps/{scrap.id}")).json()["data"]
            assert detail["can_approve"] is True
            resp = await client.post(f"{BASE}/scraps/{scrap.id}/approve", json={})
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["status"] == "approved"
            assert data["approved_by"] == test_user.name


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
