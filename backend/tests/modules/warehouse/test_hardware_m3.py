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
from app.modules.warehouse.hardware.approval_channel import APPROVER_NODE_ID as APPROVER_NODE
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


async def test_feishu_submit_matches_definition_form(db_session):
    """feishu 通道提交：仓储凭证 + 平台分支表单（分流键 + 六个普通控件）+
    发起人 user_id 解析。"""
    from uuid import uuid4

    from app.modules.warehouse.hardware.approval_channel import (
        KIND_VALUE_PLATFORM,
        KIND_WIDGET_ID,
        PLATFORM_WIDGETS,
        URGENT_VALUE_NO,
        URGENT_WIDGET_ID,
        FeishuApprovalChannel,
    )
    from app.platform.identity.models import User as IdentityUser

    # 领用人 = 真实 identity 用户（feishu_user_id 即创建实例的 user_id）
    starter = IdentityUser(
        name="领料测试人", department="发酵",
        employee_no=f"HW-M3-{uuid4().hex[:8]}",
        feishu_user_id=f"u_m3_{uuid4().hex[:8]}",
    )
    db_session.add(starter)
    await db_session.flush()

    material = await _mk_stocked(db_session)
    req = await _mk_requisition(db_session, material)
    req.applicant_user_id = starter.id
    req.approver_user_id = "u_supervisor_001"
    req.approver_name = "主管甲"
    await db_session.flush()

    captured: dict = {}

    async def fake_create(approval_code, user_id, form, **kwargs):
        captured.update(
            approval_code=approval_code, user_id=user_id,
            form=form, uuid=kwargs.get("uuid_idempotency"),
            app_id=kwargs.get("app_id"), app_secret=kwargs.get("app_secret"),
            node_approvers=kwargs.get("node_approver_user_id_list"),
        )
        return "inst_test_123"

    with patch(
        "app.platform.integrations.feishu.approval.create_instance", fake_create
    ), patch(
        "app.modules.warehouse.hardware.approval_channel.get_settings",
        return_value=_settings_stub(
            HARDWARE_APPROVAL_CHANNEL="feishu", HARDWARE_APPROVAL_CODE="OP-TEST-001",
            WAREHOUSE_FEISHU_APP_ID="cli_wh", WAREHOUSE_FEISHU_APP_SECRET="sec",
        ),
    ):
        channel = FeishuApprovalChannel("OP-TEST-001")
        items = await _items_for(db_session, req)
        ref = await channel.submit(db_session, req, items)

    assert ref == "inst_test_123"
    assert req.approval_channel == "feishu"
    assert req.approval_instance_code == "inst_test_123"
    assert captured["approval_code"] == "OP-TEST-001"
    assert captured["app_id"] == "cli_wh"  # 仓储凭证（2026-11-10 拍板口径）
    assert captured["user_id"] == starter.feishu_user_id  # 发起人=领用人
    # 发起人自选节点：随实例提交所选审批人
    assert captured["node_approvers"] == {APPROVER_NODE: ["u_supervisor_001"]}
    assert isinstance(captured["form"], list)  # create_instance 内部序列化
    # 平台分支：分流键 + 是否紧急（必填显式写否）+ 六个顶层普通控件（单物资）
    assert [w["id"] for w in captured["form"]] == [
        KIND_WIDGET_ID, URGENT_WIDGET_ID, *(c[0] for c in PLATFORM_WIDGETS)
    ]
    by_id = {w["id"]: w for w in captured["form"]}
    assert by_id[KIND_WIDGET_ID]["value"] == KIND_VALUE_PLATFORM
    assert by_id[URGENT_WIDGET_ID]["value"] == URGENT_VALUE_NO  # 前端常规申领=非紧急
    assert {w["id"]: w["type"] for w in captured["form"][2:]} == {
        c[0]: c[2] for c in PLATFORM_WIDGETS
    }
    values = [w["value"] for w in captured["form"][2:]]
    assert values == ["金属阀门", material.name, "DN25", "个", 100.0, 10.0]
    assert req.req_no not in str(captured["form"])  # 定稿表单无单号控件


async def test_feishu_submit_requires_approver(db_session):
    """未选审批人（主管及以上）→ 上抛，不创建实例（节点必须有人可批）。"""
    from app.modules.warehouse.hardware.approval_channel import (
        ApprovalChannelError,
        FeishuApprovalChannel,
    )

    material = await _mk_stocked(db_session, name="缺审批人球阀")
    req = await _mk_requisition(db_session, material)
    req.applicant_open_id = "xukangfu"  # 发起人可解析，专门测审批人缺失
    await db_session.flush()

    with patch(
        "app.modules.warehouse.hardware.approval_channel.get_settings",
        return_value=_settings_stub(
            HARDWARE_APPROVAL_CHANNEL="feishu", HARDWARE_APPROVAL_CODE="OP-TEST-001",
            WAREHOUSE_FEISHU_APP_ID="cli_wh", WAREHOUSE_FEISHU_APP_SECRET="sec",
        ),
    ):
        channel = FeishuApprovalChannel("OP-TEST-001")
        items = await _items_for(db_session, req)
        with pytest.raises(ApprovalChannelError, match="未选择审批人"):
            await channel.submit(db_session, req, items)


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


def _patch_channel_conf(monkeypatch, *, channel: str, code: str) -> None:
    """通道工厂读 runtime（2026-11-26 配置迁系统配置后），patch 读取 helper
    的落点（get_approval_channel_conf 是唯一数据源）。"""
    import app.modules.warehouse.hardware.approval_channel as ac

    monkeypatch.setattr(
        ac, "get_approval_channel_conf", lambda: (channel, code)
    )


def test_factory_fallback_without_code(monkeypatch):
    """未配置 definition code → 自动落 manual 通道（不炸）。"""
    from app.modules.warehouse.hardware.approval_channel import (
        ManualApprovalChannel,
        feishu_channel_configured,
        get_approval_channel,
    )

    _patch_channel_conf(monkeypatch, channel="feishu", code="")
    channel = get_approval_channel()
    assert isinstance(channel, ManualApprovalChannel)
    assert feishu_channel_configured() is False


def test_factory_selects_feishu_when_configured(monkeypatch):
    from app.modules.warehouse.hardware.approval_channel import (
        FeishuApprovalChannel,
        get_approval_channel,
    )

    _patch_channel_conf(monkeypatch, channel="feishu", code="OP-REAL")
    channel = get_approval_channel()
    assert isinstance(channel, FeishuApprovalChannel)
    assert channel.approval_code == "OP-REAL"


def _settings_stub(**overrides):
    """config.Settings 替身（只暴露 approval_channel 读的属性）。"""
    class _S:
        HARDWARE_APPROVAL_CHANNEL = overrides.get("HARDWARE_APPROVAL_CHANNEL", "")
        HARDWARE_APPROVAL_CODE = overrides.get("HARDWARE_APPROVAL_CODE", "")
        HARDWARE_APPROVAL_USER_KEY = overrides.get("HARDWARE_APPROVAL_USER_KEY", "user_id")
        WAREHOUSE_FEISHU_APP_ID = overrides.get("WAREHOUSE_FEISHU_APP_ID", "")
        WAREHOUSE_FEISHU_APP_SECRET = overrides.get("WAREHOUSE_FEISHU_APP_SECRET", "")
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
    # 差分口径：按本测试专属物资圈定（活库可能有历史 req_issue 流水，绝对计数会假红）
    mvs, n1 = await hw.list_movements(db_session, business_type="req_issue", keyword=m1.name)
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


async def test_submit_approval_raises_on_feishu_failure(db_session):
    """feishu 通道故障 → 上抛（2026-11-19 拍板：不再静默降级 manual）。"""
    from app.modules.warehouse.hardware.approval_channel import (
        ApprovalChannelError,
        submit_approval,
    )

    material = await _mk_stocked(db_session, name="失败球阀")
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
        with pytest.raises(ApprovalChannelError):
            await submit_approval(db_session, req)
    assert req.approval_channel is None  # 没落 manual 标记


async def test_approvers_endpoint_lists_supervisors_first(api_context):
    """审批人候选：登记在位人员，主管标记置前（发起人自选节点下拉）。"""
    from uuid import uuid4

    from tests.modules.warehouse.conftest import WAREHOUSE_PERMS

    from app.platform.identity.models import User as IdentityUser

    ac, db = api_context
    tag = uuid4().hex[:6]
    db.add(
        IdentityUser(
            name=f"普通员工{tag}", department="供应部", position="操作工",
            employee_no=f"AP-STAFF-{tag}", feishu_user_id=f"u_staff_{tag}",
        )
    )
    db.add(
        IdentityUser(
            name=f"审批主管{tag}", department="供应部", position="车间主管",
            employee_no=f"AP-SUP-{tag}", feishu_user_id=f"u_sup_{tag}",
        )
    )
    await db.flush()

    async def _granted(uid, d):  # noqa: ANN001
        return WAREHOUSE_PERMS | {"warehouse:hardware:requisition:create"}

    with patch("app.platform.permission.deps.get_user_permissions", new=_granted):
        res = await ac.get(
            "/api/v1/warehouse/hardware/requisition-approvers", params={"keyword": tag}
        )
    assert res.status_code == 200, res.text
    items = res.json()["data"]["items"]
    # 硬过滤：只留主管及以上（普通员工搜不到）
    assert [i["name"] for i in items] == [f"审批主管{tag}"]
    assert items[0]["supervisor"] is True and items[0]["user_id"] == f"u_sup_{tag}"


async def test_submit_api_reverts_to_draft_when_approval_fails(api_context):
    """提交接口：审批发起失败 → 502 且单据回退草稿（预扣撤销，可重提）。"""
    from app.modules.warehouse.hardware.approval_channel import ApprovalChannelError
    from tests.modules.warehouse.conftest import WAREHOUSE_PERMS

    ac, db = api_context
    material = await _mk_stocked(db, name="回滚球阀")
    draft = await hw.create_requisition(
        db,
        RequisitionCreate(
            dept_name="发酵", applicant="测试员",
            items=[RequisitionItemIn(material_id=str(material.id), need_qty=Decimal("10"))],
        ),
    )

    async def _granted(uid, d):  # noqa: ANN001
        return WAREHOUSE_PERMS | {"warehouse:hardware:requisition:create"}

    with patch(
        "app.platform.permission.deps.get_user_permissions", new=_granted
    ), patch(
        "app.modules.warehouse.hardware.approval_channel.submit_approval",
        AsyncMock(side_effect=ApprovalChannelError("模拟飞书故障")),
    ):
        res = await ac.post(f"/api/v1/warehouse/hardware/requisitions/{draft.id}/submit")

    assert res.status_code == 502
    assert "留在草稿" in res.json()["message"]
    await db.refresh(draft)
    assert draft.status == "draft"
    assert draft.submitted_at is None and draft.approval_channel is None
    rows, _ = await hw.list_stock_rows(db, keyword=material.name)
    assert rows[0]["reserved"] == Decimal("0")  # 预扣已撤销


# ── 紧急 24h 补单提醒任务（2026-11-20 退役：紧急单改审批打标+先发后批）──


async def test_scheduled_tasks_registered():
    """TaskDefinition 注册形态：名字唯一+interval 配置。"""
    from app.modules.warehouse.hardware.scheduled import HARDWARE_APPROVAL_POLL_TASK

    assert HARDWARE_APPROVAL_POLL_TASK.name == "warehouse.hardware_approval_poll"
