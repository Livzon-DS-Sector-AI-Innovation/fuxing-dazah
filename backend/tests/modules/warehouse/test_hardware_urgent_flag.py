"""紧急领料审批打标链路测试（2026-11-20 改版：审批单据即闭环，先发后批）。

覆盖：表单解析（是否紧急/紧急原因 双形态）、平台代发表单写入、schema 必填
校验、摄取建 urgent 单+仓管加急卡、状态机（pending→approve+issue 与普通单
同轨；issued 先发后批闭环/驳回留痕不回退）。通知全打桩。
先例=test_hardware_ingest.py / 原 test_hardware_urgent_flow.py（独立链已退役）。
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import get_settings
from app.modules.warehouse.hardware import approval_channel as ac
from app.modules.warehouse.hardware import approval_ingest as ai
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware import urgent_flow
from app.modules.warehouse.hardware.models import HardwareMovement
from app.modules.warehouse.hardware.schemas import (
    RequisitionCreate,
    RequisitionItemIn,
)
from tests.modules.warehouse.test_hardware_ingest import APPROVAL_CODE, _mk_material

KEEPER = "ou_keeper_001"


@pytest.fixture
def approval_code(monkeypatch):
    # 审批配置已迁系统配置（2026-11-26）：patch runtime_store 的 DB 层
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    original = runtime_store.get_value

    def _get_value(key: str):
        if key == "hardware_approval_code":
            return APPROVAL_CODE
        return original(key)

    monkeypatch.setattr(runtime_store, "get_value", _get_value)
    return APPROVAL_CODE


@pytest.fixture
def notify_targets(monkeypatch):
    monkeypatch.setattr(
        get_settings(), "HARDWARE_URGENT_NOTIFY_TARGETS", KEEPER, raising=False
    )
    return [KEEPER]


@pytest.fixture
def sent_cards(monkeypatch):
    """加急卡桩：采集 send_card_to_target 投递。"""
    box: list[tuple[str, dict]] = []

    async def fake_target(target, card):
        box.append((target, card))

    monkeypatch.setattr(urgent_flow, "send_card_to_target", fake_target)
    return box


async def _mk_urgent_pending(db, m, qty=Decimal("5")):
    req = await hw.create_requisition(
        db,
        RequisitionCreate(
            dept_name="动力机修",
            applicant="王抢修",
            applicant_open_id="ou_app_001",
            purpose="泵体抢修",
            req_type="urgent",
            urgent_reason="3#泵体抢修急需",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=str(qty))],
        ),
    )
    await hw.submit_requisition(db, req.id)
    return req


def _urgent_instance(name: str, spec: str, *, urgent="是", reason="泵体抢修急需") -> dict:
    """合成紧急领料审批实例（是否紧急/紧急原因顶层控件，双明细表在场）。"""
    form = [
        {"id": ai.KIND_WIDGET_ID, "type": "radioV2", "name": "领/退料",
         "value": "五金库领料"},
        {"id": ai.URGENT_WIDGET_ID, "type": "radioV2", "name": "是否紧急",
         "value": urgent},
        {"id": ai.URGENT_REASON_WIDGET_ID, "type": "input", "name": "紧急原因",
         "value": reason},
        {"id": ai.DETAIL_WIDGET_ID, "type": "fieldList", "name": "五金库领料明细",
         "value": [[
             {"name": "类别", "value": "金属阀门"},
             {"name": "物资名称", "value": name},
             {"name": "规格型号", "value": spec},
             {"name": "计量单位", "value": "个"},
             {"name": "可领量", "value": "100"},
             {"name": "领料量", "value": "5"},
         ]]},
        {"id": "widget17950492860480001", "type": "fieldList", "name": "五金库退料明细",
         "value": []},
    ]
    return {
        "approval_code": APPROVAL_CODE,
        "status": "PENDING",
        "form": json.dumps(form, ensure_ascii=False),
        "start_user_id": "ingest_tester_001",
    }


# ── 表单解析 ──


def test_parse_form_urgent_flag_shapes():
    """是否紧急读回文本「是」与选项 value 双形态；否/缺省=False。"""
    base = _urgent_instance("球阀A", "DN25")
    parsed = ai.parse_form(base["form"])
    assert parsed.urgent is True and parsed.urgent_reason == "泵体抢修急需"

    value_shape = _urgent_instance(
        "球阀A", "DN25", urgent=ai.URGENT_VALUE_YES, reason="",
    )
    parsed_v = ai.parse_form(value_shape["form"])
    assert parsed_v.urgent is True  # 选项 value 形态也识别
    assert parsed_v.urgent_reason == ""

    no = _urgent_instance("球阀A", "DN25", urgent="否")
    parsed_no = ai.parse_form(no["form"])
    assert parsed_no.urgent is False

    # 缺省（旧实例/退料分支无该控件）→ False
    plain = ai.parse_form(json.dumps([
        {"id": ai.KIND_WIDGET_ID, "type": "radioV2", "name": "领/退料",
         "value": "五金库领料"},
    ]))
    assert plain.urgent is False and plain.urgent_reason == ""


# ── 平台代发表单 ──


def _one_item() -> list[dict]:
    return [{
        "material_name": "球阀A", "spec": "DN25", "unit": "个",
        "category": "金属阀门", "need_qty": 5.0, "available": 95.0,
    }]


def test_build_platform_form_default_writes_no():
    """非紧急代发：显式写「是否紧急=否」（必填控件不写有被拒收风险）。"""
    form = ac.build_platform_form(_one_item())
    urgent = [w for w in form if w["id"] == ac.URGENT_WIDGET_ID]
    assert urgent and urgent[0]["value"] == ac.URGENT_VALUE_NO
    assert all(w["id"] != ac.URGENT_REASON_WIDGET_ID for w in form)


def test_build_platform_form_urgent_writes_yes_and_reason():
    form = ac.build_platform_form(_one_item(), urgent=True, urgent_reason="泵体抢修")
    values = {w["id"]: w["value"] for w in form}
    assert values[ac.URGENT_WIDGET_ID] == ac.URGENT_VALUE_YES
    assert values[ac.URGENT_REASON_WIDGET_ID] == "泵体抢修"


def test_build_platform_form_urgent_requires_reason():
    with pytest.raises(ac.ApprovalChannelError, match="紧急原因"):
        ac.build_platform_form(_one_item(), urgent=True, urgent_reason="  ")


# ── schema 必填校验 ──


def test_schema_urgent_reason_required():
    with pytest.raises(ValidationError, match="紧急原因"):
        RequisitionCreate(
            dept_name="动力机修", applicant="王抢修", req_type="urgent",
            items=[RequisitionItemIn(material_id="00000000-0000-0000-0000-000000000000",
                                     need_qty="1")],
        )


# ── 摄取：紧急标建单 + 加急卡 ──


async def test_ingest_urgent_creates_order_and_notice(
    db_session, approval_code, notify_targets, sent_cards
):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    inst = _urgent_instance(m.name, m.spec)
    result = await ai.ingest_instance(db_session, f"inst-urgent-{m.id}", instance=inst)
    assert result["action"] == "ingested"

    req = (
        await db_session.execute(
            select(hw.HardwareRequisition).where(
                hw.HardwareRequisition.approval_instance_code == f"inst-urgent-{m.id}"
            )
        )
    ).scalars().one()
    assert req.req_type == "urgent" and req.urgent_reason == "泵体抢修急需"
    assert req.status == "pending"  # 预扣生效
    # 仓管加急卡：目标各一张，文案含紧急原因与先发后批提示
    assert len(sent_cards) == len(notify_targets)
    text = str(sent_cards[0][1])
    assert "紧急" in text and "泵体抢修急需" in text


async def test_ingest_normal_urgent_no_notice(
    db_session, approval_code, notify_targets, sent_cards
):
    """非紧急实例：不建 urgent 单也不发加急卡。"""
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    inst = _urgent_instance(m.name, m.spec, urgent="否")
    result = await ai.ingest_instance(db_session, f"inst-normal-{m.id}", instance=inst)
    assert result["action"] == "ingested"
    req = (
        await db_session.execute(
            select(hw.HardwareRequisition).where(
                hw.HardwareRequisition.approval_instance_code == f"inst-normal-{m.id}"
            )
        )
    ).scalars().one()
    assert req.req_type == "normal"
    assert sent_cards == []


# ── 状态机：与普通单同轨 + 先发后批闭环 ──


async def _movement_count(db, req) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(HardwareMovement).where(
                HardwareMovement.ref_table == "hardware_requisitions",
                HardwareMovement.ref_id == req.id,
            )
        )
    ).scalar_one()


async def test_pending_urgent_approved_auto_issue(db_session):
    """pending 紧急单收 APPROVED → approve+issue（与普通单同轨）。"""
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    req = await _mk_urgent_pending(db_session, m)
    await ai._apply_status(db_session, req, "APPROVED")
    assert req.status == "issued" and req.approval_status == "approved"
    assert await _movement_count(db_session, req) == 1


async def test_issued_urgent_approved_closes_without_double_issue(db_session):
    """先发后批闭环：仓管已发料的紧急单收 APPROVED → 只落审批结论，不二次扣。"""
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    req = await _mk_urgent_pending(db_session, m)
    await hw.issue_requisition(db_session, req.id, issued_by="仓管甲", received_by="王抢修")
    assert req.status == "issued"
    count_before = await _movement_count(db_session, req)

    await ai._apply_status(db_session, req, "APPROVED")
    assert req.status == "issued"  # 不回退
    assert req.approval_status == "approved"
    assert req.approved_by == "飞书审批"
    assert await _movement_count(db_session, req) == count_before  # 零二次发料


async def test_issued_urgent_rejected_flagged(db_session):
    """已发料紧急单被驳回：不回退不释放，approval_status 留痕提示退料。"""
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    req = await _mk_urgent_pending(db_session, m)
    await hw.issue_requisition(db_session, req.id, issued_by="仓管甲", received_by="王抢修")

    await ai._apply_status(db_session, req, "REJECTED")
    assert req.status == "issued"
    assert req.approval_status == "rejected"
    assert "退料" in (req.remark or "")


async def test_notice_card_shape(notify_targets):
    """加急卡：红头 + 单号/紧急原因/先发后批提示；非紧急单不发。"""
    req = hw.HardwareRequisition(
        req_no="WJK-LY-T-000001", dept_name="动力机修", applicant="王抢修",
        req_type="urgent", urgent_reason="3#泵体抢修", status="pending",
    )
    card = urgent_flow.build_urgent_notice_card(req, "· 球阀A DN25 x5 个")
    assert card["header"]["template"] == "red"
    text = str(card)
    assert "WJK-LY-T-000001" in text and "3#泵体抢修" in text and "审批" in text

    req.req_type = "normal"
    assert await urgent_flow.send_urgent_notice(None, req) == 0  # 非 urgent 前置短路，不触 db
