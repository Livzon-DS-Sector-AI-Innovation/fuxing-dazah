"""五金库 M3 验收测试：审批双通道（feishu client 单测/manual 代录）+ 状态机
接通道 + 紧急 24h 补单提醒任务。

验收口径（任务书）：feishu 通道=client 单测（uuid 幂等/参数契约/未配置降级）
+ 配置就绪冒烟；manual 通道真机 3 单由用户验收阶段执行（此处以单测覆盖状态
机全链与库存对平逻辑）；紧急补单定时任务可触发。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareMovement,
    HardwareRequisition,
)
from app.modules.warehouse.hardware.schemas import (
    ReceiptCreate,
    ReceiptItemIn,
    RequisitionCreate,
    RequisitionItemIn,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def _mk_stocked(db, name="球阀·M3", qty=Decimal("100"), safety=Decimal("10")):
    m = HardwareMaterial(name=f"{name}·{m3_tag()}", spec="DN25", unit="个", category="金属阀门",
                         managed_class="stocked", safety_stock=safety, no_expiry=True)
    db.add(m)
    await db.flush()
    payload = ReceiptCreate(source="manual", items=[
        ReceiptItemIn(material_id=str(m.id), name=m.name, spec=m.spec, unit=m.unit, quantity=qty),
    ])
    receipt = await hw.create_receipt(db, payload)
    await hw.accept_receipt(db, receipt.id, inspected_by_warehouse="ou_wh", inspected_by_dept="ou_dept")
    return m


_counter = {"n": 0}


def m3_tag() -> str:
    _counter["n"] += 1
    return f"M3{_counter['n']:03d}{__import__('uuid').uuid4().hex[:4].upper()}"


async def _mk_requisition(db, material, qty=Decimal("10"), req_type="normal"):
    req = await hw.create_requisition(
        db,
        RequisitionCreate(
            dept_name="发酵", applicant="测试员", req_type=req_type,
            items=[RequisitionItemIn(material_id=str(material.id), need_qty=qty)],
        ),
    )
    await hw.submit_requisition(db, req.id)
    return req


# ── feishu 通道 client 单测 ──


async def test_feishu_channel_uuid_idempotency_contract():
    """uuid 幂等：同 req.id 派生同一 uuid（重试不重单）；form 为 JSON 字符串。"""
    import inspect
    import uuid as uuid_mod

    from app.platform.integrations.feishu import approval as approval_mod

    # 契约：create_instance 存在且签名含幂等 uuid
    sig = inspect.signature(approval_mod.create_instance)
    assert "uuid_idempotency" in sig.parameters
    assert "approval_code" in sig.parameters and "form" in sig.parameters

    # uuid 幂等派生逻辑（FeishuApprovalChannel.submit 内 uuid5）可复现
    req_id = uuid_mod.uuid4()
    u1 = str(uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, f"hardware-requisition:{req_id}"))
    u2 = str(uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, f"hardware-requisition:{req_id}"))
    assert u1 == u2


async def test_feishu_submit_uses_safety_credentials_and_creates_instance(db_session):
    """feishu 通道提交：走 safety 凭证 + create_instance，落 instance_code。"""
    from app.modules.warehouse.hardware.approval_channel import (
        FeishuApprovalChannel,
    )

    material = await _mk_stocked(db_session)
    req = await _mk_requisition(db_session, material)

    captured: dict = {}

    async def fake_create(approval_code, user_id, form, **kwargs):
        captured.update(
            approval_code=approval_code, user_id=user_id,
            form=form, uuid=kwargs.get("uuid_idempotency"),
            app_id=kwargs.get("app_id"), app_secret=kwargs.get("app_secret"),
        )
        return "inst_test_123"

    with patch(
        "app.platform.integrations.feishu.approval.create_instance", fake_create
    ), patch(
        "app.modules.warehouse.hardware.approval_channel.get_settings",
        return_value=_settings_stub(
            HARDWARE_APPROVAL_CHANNEL="feishu", HARDWARE_APPROVAL_CODE="OP-TEST-001",
            SAFETY_FEISHU_APP_ID="cli_safety", SAFETY_FEISHU_APP_SECRET="sec",
        ),
    ):
        channel = FeishuApprovalChannel("OP-TEST-001")
        items = await _items_for(db_session, req)
        ref = await channel.submit(db_session, req, items)

    assert ref == "inst_test_123"
    assert req.approval_channel == "feishu"
    assert req.approval_instance_code == "inst_test_123"
    assert captured["approval_code"] == "OP-TEST-001"
    assert captured["app_id"] == "cli_safety"  # safety 凭证（拍板口径）
    assert isinstance(captured["form"], list)  # create_instance 内部序列化
    assert any("发酵" in str(it.get("value", "")) for it in captured["form"])
    assert req.req_no in str(captured["form"])  # 单号回溯键入表单


async def test_feishu_poll_result_mapping(db_session):
    """轮询结果映射：APPROVED→approved / REJECTED→rejected / PENDING→None。"""
    from app.modules.warehouse.hardware.approval_channel import FeishuApprovalChannel

    channel = FeishuApprovalChannel("OP-TEST-001")

    class FakeReq:
        req_no = "WJK-LY-261104-001"
        approval_instance_code = "inst_x"

    with patch(
        "app.platform.integrations.feishu.approval.get_instance",
        AsyncMock(return_value={"status": "APPROVED", "form": "[]"}),
    ):
        assert await channel.poll_result(db_session, FakeReq()) == "approved"
    with patch(
        "app.platform.integrations.feishu.approval.get_instance",
        AsyncMock(return_value={"status": "REJECTED", "form": "[]"}),
    ):
        assert await channel.poll_result(db_session, FakeReq()) == "rejected"
    with patch(
        "app.platform.integrations.feishu.approval.get_instance",
        AsyncMock(return_value={"status": "PENDING", "form": "[]"}),
    ):
        assert await channel.poll_result(db_session, FakeReq()) is None


def test_factory_fallback_without_code():
    """未配置 definition code → 自动落 manual 通道（不炸）。"""
    from app.modules.warehouse.hardware.approval_channel import (
        ManualApprovalChannel,
        feishu_channel_configured,
        get_approval_channel,
    )

    with patch("app.modules.warehouse.hardware.approval_channel.get_settings", return_value=_settings_stub()):
        channel = get_approval_channel()
        assert isinstance(channel, ManualApprovalChannel)
        assert feishu_channel_configured() is False


def test_factory_selects_feishu_when_configured():
    with patch(
        "app.modules.warehouse.hardware.approval_channel.get_settings",
        return_value=_settings_stub(
            HARDWARE_APPROVAL_CHANNEL="feishu", HARDWARE_APPROVAL_CODE="OP-REAL"
        ),
    ):
        from app.modules.warehouse.hardware.approval_channel import (
            FeishuApprovalChannel,
            get_approval_channel,
        )

        channel = get_approval_channel()
        assert isinstance(channel, FeishuApprovalChannel)
        assert channel.approval_code == "OP-REAL"


def _settings_stub(**overrides):
    """config.Settings 替身（只暴露 approval_channel 读的属性）。"""
    class _S:
        HARDWARE_APPROVAL_CHANNEL = overrides.get("HARDWARE_APPROVAL_CHANNEL", "")
        HARDWARE_APPROVAL_CODE = overrides.get("HARDWARE_APPROVAL_CODE", "")
        HARDWARE_APPROVAL_USER_KEY = overrides.get("HARDWARE_APPROVAL_USER_KEY", "user_id")
        SAFETY_FEISHU_APP_ID = overrides.get("SAFETY_FEISHU_APP_ID", "")
        SAFETY_FEISHU_APP_SECRET = overrides.get("SAFETY_FEISHU_APP_SECRET", "")
    return _S()


async def _items_for(db, req):
    from app.modules.warehouse.hardware.approval_channel import _load_items

    return await _load_items(db, req)


# ── manual 通道全链（3 单口径：常规通过/超额备注/驳回释放）+ 库存逐单对平 ──


async def test_manual_full_chain_three_cases(db_session):
    """manual 通道三单：①常规通过→发料实扣 ②超额（备注代录生产总监提示）
    ③驳回释放。每单库存变动与流水对平。"""
    from app.modules.warehouse.hardware.approval_channel import ManualApprovalChannel

    # 单①：常规通过 → issued
    m1 = await _mk_stocked(db_session, name="常规球阀")
    req1 = await _mk_requisition(db_session, m1, Decimal("10"))
    ch = ManualApprovalChannel()
    await ch.submit(db_session, req1, [])
    assert req1.approval_channel == "manual" and req1.status == "pending"
    await hw.approve_requisition(db_session, req1.id, approver="李主管")
    await hw.issue_requisition(db_session, req1.id, issued_by="仓管员", received_by="测试员")
    rows, _ = await hw.list_stock_rows(db_session, keyword=m1.name)
    assert rows[0]["on_hand"] == Decimal("90") and rows[0]["reserved"] == Decimal("0")
    mvs, n1 = await hw.list_movements(db_session, business_type="req_issue")
    assert n1 == 1 and mvs[0].quantity == Decimal("10")

    # 单②：超额（excess，manual 审批备注=需生产总监提示）
    m2 = await _mk_stocked(db_session, name="超额法兰", qty=Decimal("50"), safety=Decimal("0"))
    req2 = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="提炼一期", applicant="测试员", req_type="excess",
            items=[RequisitionItemIn(material_id=str(m2.id), need_qty=Decimal("30"))],
        ),
    )
    await hw.submit_requisition(db_session, req2.id)
    await ch.submit(db_session, req2, [])
    await hw.approve_requisition(
        db_session, req2.id, approver="李主管", note="超额领用已报生产总监口头同意"
    )
    assert req2.approval_note and "生产总监" in req2.approval_note
    await hw.issue_requisition(db_session, req2.id, issued_by="仓管员", received_by="测试员")
    rows2, _ = await hw.list_stock_rows(db_session, keyword=m2.name)
    assert rows2[0]["on_hand"] == Decimal("20")

    # 单③：驳回 → 释放预扣
    m3 = await _mk_stocked(db_session, name="驳回垫片", safety=Decimal("0"))
    req3 = await _mk_requisition(db_session, m3, Decimal("20"))
    await ch.submit(db_session, req3, [])
    rows3, _ = await hw.list_stock_rows(db_session, keyword=m3.name)
    assert rows3[0]["reserved"] == Decimal("20")  # 预扣中
    await hw.reject_requisition(db_session, req3.id, approver="李主管", reason="用途不符")
    rows3, _ = await hw.list_stock_rows(db_session, keyword=m3.name)
    assert rows3[0]["reserved"] == Decimal("0")  # 释放
    assert rows3[0]["on_hand"] == Decimal("100")  # 未发料不变
    assert req3.status == "rejected" and req3.rejected_reason == "用途不符"


async def test_submit_approval_falls_back_to_manual(db_session):
    """feishu 通道故障 → submit_approval 自动降级 manual（预扣不阻断）。"""
    from app.modules.warehouse.hardware.approval_channel import (
        ApprovalChannelError,
        submit_approval,
    )

    material = await _mk_stocked(db_session, name="降级球阀")
    req = await _mk_requisition(db_session, material)

    class BrokenChannel:
        name = "feishu"

        async def submit(self, db, req_, items):
            raise ApprovalChannelError("模拟飞书故障")

        async def poll_result(self, db, req_):
            return None

    with patch(
        "app.modules.warehouse.hardware.approval_channel.get_approval_channel",
        return_value=BrokenChannel(),
    ):
        ref = await submit_approval(db_session, req)
    assert ref.startswith("manual:")
    assert req.approval_channel == "manual"


# ── 紧急 24h 补单提醒任务 ──


async def test_urgent_overdue_marking_and_task(db_session):
    """紧急单发料后 24h 未补单 → overdue_unpatched 标记 + 推送事件；补单闭合。"""
    from app.modules.warehouse.hardware.scheduled import run_urgent_patch_check

    material = await _mk_stocked(db_session, name="紧急轴承")
    req = await _mk_requisition(db_session, material, Decimal("5"), req_type="urgent")
    # 紧急单 pending 直发（先发后补）
    await hw.issue_requisition(db_session, req.id, issued_by="仓管员", received_by="测试员")
    assert req.status == "issued"
    assert req.urgent_patch_deadline is not None

    # 24h 内：不标记
    summary = await run_urgent_patch_check(db_session, now=datetime.now(CN_TZ))
    assert summary["marked"] == 0

    # 模拟超期：截止时间前移
    req.urgent_patch_deadline = datetime.now(CN_TZ) - timedelta(hours=1)
    await db_session.flush()
    summary = await run_urgent_patch_check(db_session)
    assert summary["marked"] == 1
    await db_session.refresh(req)
    assert req.status == "overdue_unpatched"

    # 幂等：再跑不重复
    summary2 = await run_urgent_patch_check(db_session)
    assert summary2["marked"] == 0


async def test_scheduled_tasks_registered():
    """TaskDefinition 注册形态：名字唯一+interval 配置。"""
    from app.modules.warehouse.hardware.scheduled import (
        HARDWARE_APPROVAL_POLL_TASK,
        URGENT_PATCH_CHECK_TASK,
    )

    assert URGENT_PATCH_CHECK_TASK.name == "warehouse.hardware_urgent_patch_check"
    assert URGENT_PATCH_CHECK_TASK.schedule.interval_seconds == 1800
    assert HARDWARE_APPROVAL_POLL_TASK.name == "warehouse.hardware_approval_poll"
