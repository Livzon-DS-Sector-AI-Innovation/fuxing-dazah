"""五金库退料平台链路测试（2026-11-26）：从已发料领料单发起退料。

覆盖：额度校验（单退/累计/在途/重校验）、提交即发起审批（feishu 通道编排：
未选审批人/实例创建失败停在草稿/manual 兜底）、审批人通过/驳回（飞书回流与
平台共用）、仓管验收回加（accept_return 复用，物料回库存）、平台先批后飞书
结论只留痕、飞书自建链路行为不变。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.modules.warehouse.hardware import return_flow
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMovement,
    HardwareRequisition,
)

def _patch_runtime(monkeypatch, values: dict) -> None:
    """runtime_store 单例替身：固定值表（审批配置已迁系统配置，2026-11-26）。"""
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    monkeypatch.setattr(
        runtime_store, "get_value", lambda key: values.get(key)
    )


# ── 造数 ──


async def _mk_material(db, *, name="退料物料", qty_stock=None):
    from app.modules.warehouse.hardware.models import HardwareMaterial
    from app.modules.warehouse.hardware.schemas import (
        ReceiptCreate,
        ReceiptItemIn,
    )

    material = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec="DN25", unit="个",
        category="金属阀门", managed_class="stocked", safety_stock=Decimal("0"),
        no_expiry=True,
    )
    db.add(material)
    await db.flush()
    if qty_stock is not None:
        payload = ReceiptCreate(
            source="manual", mode="stocked", supplier_name="测试供应商",
            items=[ReceiptItemIn(
                material_id=str(material.id), name=material.name,
                spec=material.spec, unit=material.unit, quantity=qty_stock,
                match_confidence="manual",
            )],
        )
        receipt = await hw.create_receipt(db, payload)
        await hw.accept_receipt(
            db, receipt.id, inspected_by_warehouse="ou_w", inspected_by_dept="ou_d",
        )
    return material


async def _mk_issued_requisition(db, material, issued_qty: str) -> HardwareRequisition:
    """已发料领料单（带飞书实例 code，退料关联锚点）。"""
    from app.modules.warehouse.hardware.schemas import (
        RequisitionCreate,
        RequisitionItemIn,
    )

    req = await hw.create_requisition(
        db,
        RequisitionCreate(
            dept_name="发酵", applicant="张三", approver_user_id="u_approver",
            items=[RequisitionItemIn(material_id=str(material.id), need_qty=Decimal(issued_qty))],
        ),
        user=None,
    )
    await hw.submit_requisition(db, req.id)
    await hw.approve_requisition(db, req.id, approver="李主管")
    await hw.issue_requisition(db, req.id, issued_by="仓管", received_by="张三")
    # 手工挂实例 code（模拟飞书通道领料；额度归集的关联锚点）
    req.approval_instance_code = f"INST-REQ-{uuid4().hex[:8].upper()}"
    await db.flush()
    await db.refresh(req)
    return req


def _rows(material, qty: str) -> list[dict[str, Any]]:
    return [{"material_id": str(material.id), "quantity": qty}]


# ── 额度校验 ──


async def test_return_quota_single_and_cumulative(db_session):
    """额度：退量>实发拦截；多单累计占用；拆单绕过拦截。"""
    m = await _mk_material(db_session, name="额度甲", qty_stock=Decimal("10"))
    req = await _mk_issued_requisition(db_session, m, "10")

    # 单退超量 → 拦截
    with pytest.raises(hw.HardwareError, match="超可退"):
        await return_flow.create_return_from_requisition(
            db_session, req.id, returned_by="张三",
            approver_user_id="u_approver", approver_name="赵审批",
            items=_rows(m, "11"),
        )

    # 合法第一单（draft 即占额度）
    ret1 = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "4"),
    )
    # 第二单累计超额（10-4=6 可退，退 7 拦）
    with pytest.raises(hw.HardwareError, match="超可退"):
        await return_flow.create_return_from_requisition(
            db_session, req.id, returned_by="张三",
            approver_user_id="u_approver", approver_name="赵审批",
            items=_rows(m, "7"),
        )
    # 第二单合法（6）
    ret2 = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "6"),
    )
    # 第三单（额度 0）
    with pytest.raises(hw.HardwareError, match="超可退"):
        await return_flow.create_return_from_requisition(
            db_session, req.id, returned_by="张三",
            approver_user_id="u_approver", approver_name="赵审批",
            items=_rows(m, "1"),
        )
    assert ret1.status == "draft" and ret2.status == "draft"


async def test_return_quota_resubmit_exclude_self(db_session):
    """提交时重校验排除自身在途额度（draft 单改状态后重提交不自我挤占）。"""
    m = await _mk_material(db_session, name="额度乙", qty_stock=Decimal("10"))
    req = await _mk_issued_requisition(db_session, m, "10")
    ret = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "10"),
    )
    # manual 通道（未配置 feishu 分支）：提交重校验须通过（排除自身后额度=10）
    submitted = await return_flow.submit_return(db_session, ret.id)
    assert submitted.status == "pending"
    assert submitted.approval_channel == "manual"


# ── 状态机 + 飞书通道编排 ──


async def test_return_submit_feishu_channel(db_session, monkeypatch):
    """feishu 通道：未选审批人 422；实例创建失败停在 draft；成功落 pending+实例。"""
    from app.modules.warehouse.hardware import approval_channel as ac

    calls: list[dict[str, Any]] = []

    class _Channel:
        name = "feishu"

        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail

        async def submit_return(self, db, ret, req):
            calls.append({"return_no": ret.return_no, "approver": ret.approver_user_id})
            if self.fail:
                raise ac.ApprovalChannelError("实例创建失败（测试注入）")
            ret.approval_channel = "feishu"
            ret.approval_instance_code = "INST_RET_TEST"
            ret.approval_status = "pending"
            await db.flush()
            return "INST_RET_TEST"

    m = await _mk_material(db_session, name="通道丙", qty_stock=Decimal("5"))
    req = await _mk_issued_requisition(db_session, m, "5")

    # 未选审批人 → 拦截停 draft
    ret = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三", items=_rows(m, "1"),
    )
    monkeypatch.setattr(ac, "get_return_approval_channel", lambda: _Channel())
    with pytest.raises(hw.HardwareError, match="未选择审批人"):
        await return_flow.submit_return(db_session, ret.id)

    # 实例创建失败 → 停 draft 不降级
    ret.approver_user_id = "u_approver"
    ret.approver_name = "赵审批"
    await db_session.flush()
    monkeypatch.setattr(ac, "get_return_approval_channel", lambda: _Channel(fail=True))
    with pytest.raises(hw.HardwareError, match="飞书审批发起失败"):
        await return_flow.submit_return(db_session, ret.id)
    await db_session.refresh(ret)
    assert ret.status == "draft" and ret.approval_channel is None

    # 成功 → pending + feishu + 实例 code
    monkeypatch.setattr(ac, "get_return_approval_channel", lambda: _Channel())
    submitted = await return_flow.submit_return(db_session, ret.id)
    await db_session.refresh(submitted)
    assert submitted.status == "pending"
    assert submitted.approval_channel == "feishu"
    assert submitted.approval_instance_code == "INST_RET_TEST"
    assert calls[-1]["approver"] == "u_approver"


async def test_return_full_path_manual_channel(db_session):
    """manual 全链路：提交→待审批→通过→待验收→仓管验收回加（物料回库存+流水）。"""
    m = await _mk_material(db_session, name="全链丁", qty_stock=Decimal("10"))
    req = await _mk_issued_requisition(db_session, m, "6")
    lot = (await hw.get_fifo_lots(db_session, m.id))[0]
    before_remaining = lot.remaining_quantity

    ret = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        # 预填发料批次（回原批次）
        items=[{"material_id": str(m.id), "quantity": "2", "preferred_lot_id": str(lot.id)}],
        reason_note="用剩退回",
    )
    submitted = await return_flow.submit_return(db_session, ret.id)
    assert submitted.status == "pending"

    approved = await return_flow.approve_return(db_session, ret.id, approved_by="赵审批")
    assert approved.status == "approved"
    assert approved.leader_signed is True and approved.leader_signed_by == "赵审批"
    # 审批通过不动账
    await db_session.refresh(lot)
    assert lot.remaining_quantity == before_remaining

    # 仓管验收回加：回原批次（preferred），在手+2
    from app.modules.warehouse.hardware.stocktake import accept_return

    accepted = await accept_return(db_session, ret.id, accepted_by="钱仓管")
    assert accepted.status == "accepted"
    await db_session.refresh(lot)
    assert lot.remaining_quantity == before_remaining + Decimal("2")
    mvs = [
        mv for mv in await db_session.execute(
            __import__("sqlalchemy").select(HardwareMovement).where(
                HardwareMovement.ref_table == "hardware_returns",
                HardwareMovement.ref_id == ret.id,
            )
        )
    ]
    assert len(mvs) == 1
    # 验收后额度释放？——不释放（accepted 仍计入已退：可退=实发−已退）
    quota = await return_flow.collect_requisition_quota(db_session, req)
    assert quota[str(m.id)]["returned"] == 2


async def test_return_reject_and_cancel(db_session):
    """驳回/撤回：pending 驳回→rejected；draft 撤回→cancelled；状态闸。"""
    m = await _mk_material(db_session, name="驳撤戊", qty_stock=Decimal("5"))
    req = await _mk_issued_requisition(db_session, m, "5")

    ret = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "1"),
    )
    cancelled = await return_flow.cancel_return(db_session, ret.id)
    assert cancelled.status == "cancelled"
    with pytest.raises(hw.HardwareError):
        await return_flow.cancel_return(db_session, ret.id)

    ret2 = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "1"),
    )
    await return_flow.submit_return(db_session, ret2.id)
    rejected = await return_flow.reject_return(
        db_session, ret2.id, rejected_by="赵审批", reason="数量不对"
    )
    assert rejected.status == "rejected" and rejected.rejected_by == "赵审批"
    # 驳回释放额度：再退满 5 可过
    ret3 = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "5"),
    )
    assert ret3.status == "draft"
    # approved 驳回（拒退）：先撤 ret3 腾额度再建
    await return_flow.cancel_return(db_session, ret3.id)
    ret4 = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "1"),
    )
    await return_flow.submit_return(db_session, ret4.id)
    await return_flow.approve_return(db_session, ret4.id, approved_by="赵审批")
    denied = await return_flow.reject_return(
        db_session, ret4.id, rejected_by="钱仓管", reason="实物不符"
    )
    assert denied.status == "rejected"


async def test_return_feishu_backflow_and_platform_first(db_session, monkeypatch):
    """飞书回流：APPROVED→approved 待仓管验收（不自动回加）；平台先批后飞书结论只留痕一次。"""
    import app.platform.integrations.feishu.approval as approval_mod
    from app.core.config import get_settings
    from app.modules.warehouse.hardware import approval_channel as ac
    from app.modules.warehouse.hardware import approval_ingest as ai

    m = await _mk_material(db_session, name="回流己", qty_stock=Decimal("5"))
    req = await _mk_issued_requisition(db_session, m, "5")
    _patch_runtime(monkeypatch, {"hardware_approval_code": "TEST-CODE"})
    monkeypatch.setattr(
        ac.FeishuApprovalChannel, "_credentials", staticmethod(lambda: ("id", "secret"))
    )

    ret = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "2"),
    )
    await return_flow.submit_return(db_session, ret.id)
    ret.approval_channel = "feishu"
    ret.approval_instance_code = "INST-RET-A"
    ret.returned_by_open_id = "ou_starter"
    await db_session.flush()

    # 飞书先通过：approved（待仓管验收，不自动回加——2026-11-26 用户终版
    # 拍板：退料须仓管员验收后才回库存）；验收前批次不动
    result = await ai.sync_status(db_session, "INST-RET-A", status="APPROVED")
    assert result == {"action": "synced", "doc_no": ret.return_no, "status": "approved"}
    await db_session.refresh(ret)
    assert ret.status == "approved"
    assert ret.leader_signed is True and ret.leader_signed_by == "赵审批"
    assert ret.accepted_by is None and not ret.lot_adjustments
    # 仓管验收回加（回加模式=未预填批次 → 新建 return 批次）
    from app.modules.warehouse.hardware.stocktake import accept_return

    accepted = await accept_return(db_session, ret.id, accepted_by="钱仓管")
    assert accepted.status == "accepted"
    assert accepted.lot_adjustments and accepted.lot_adjustments[0]["mode"] == "new"

    # 平台先通过（撤回实例）→ 飞书后续结论只留痕一次
    ret2 = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "1"),
    )
    await return_flow.submit_return(db_session, ret2.id)
    ret2.approval_channel = "feishu"
    ret2.approval_instance_code = "INST-RET-B"
    ret2.returned_by_open_id = "ou_starter"
    await db_session.flush()
    fake = AsyncMock(return_value=True)
    with patch.object(approval_mod, "cancel_instance", fake):
        await return_flow.approve_return(
            db_session, ret2.id, approved_by="赵审批", withdraw_instance=True
        )
    assert fake.await_count == 1
    # 之后飞书的后续结论各只留痕一次（事件/轮询/对账会重复送达）
    for _ in range(2):
        await ai.sync_status(db_session, "INST-RET-B", status="APPROVED")
    await ai.sync_status(db_session, "INST-RET-B", status="REJECTED")
    await ai.sync_status(db_session, "INST-RET-B", status="CANCELED")
    await db_session.refresh(ret2)
    assert ret2.status == "approved"
    assert (ret2.remark or "").count("后续APPROVED") == 1
    assert (ret2.remark or "").count("后续REJECTED") == 1
    assert "后续CANCELED" not in (ret2.remark or "")

    # 飞书驳回/撤销 pending 单
    ret3 = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "1"),
    )
    await return_flow.submit_return(db_session, ret3.id)
    ret3.approval_channel = "feishu"
    ret3.approval_instance_code = "INST-RET-C"
    await db_session.flush()
    assert (await ai.sync_status(db_session, "INST-RET-C", status="REJECTED"))["status"] == "rejected"
    ret4 = await return_flow.create_return_from_requisition(
        db_session, req.id, returned_by="张三",
        approver_user_id="u_approver", approver_name="赵审批",
        items=_rows(m, "1"),
    )
    await return_flow.submit_return(db_session, ret4.id)
    ret4.approval_channel = "feishu"
    ret4.approval_instance_code = "INST-RET-D"
    await db_session.flush()
    assert (await ai.sync_status(db_session, "INST-RET-D", status="CANCELED"))["status"] == "cancelled"


def test_can_user_approve_return_rule():
    ret = return_flow.HardwareReturn(
        return_no="WJK-TK-TEST", dept_name="发酵", returned_by="张三",
        items=[], status="pending", approver_user_id="u_approver",
    )

    class _User:
        id = "u1"
        name = "张三"
        feishu_user_id = "u_approver"

    manage = {"warehouse:hardware:return:manage"}
    assert return_flow.can_user_approve_return(ret, user=_User(), perms=manage)
    assert return_flow.can_user_approve_return(ret, user=_User(), perms=set())
    assert return_flow.can_user_approve_return(ret, user=None, perms=set()) is False
    _User.feishu_user_id = "u_other"
    assert return_flow.can_user_approve_return(
        ret, user=_User(), perms={"warehouse:hardware:return:read"}
    ) is False
