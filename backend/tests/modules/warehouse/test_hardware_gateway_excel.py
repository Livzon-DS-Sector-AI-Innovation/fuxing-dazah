"""五金库对话式 Excel 入库 + 出库导出工具测试（2026-11-13 机器人接入）。

gateway 意图判定纯函数 / process_hardware_excel 全链（mock 下载与发送）/
export_hardware_requisitions 工具（mock 文件发送）。确认卡机制（scene=
hardware_receipt）复用既有 M2 测试覆盖，不重复。
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.warehouse.agent.gateway import _is_hardware_inbound_intent
from app.modules.warehouse.agent.tools.hardware import export_hardware_requisitions
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.gateway_excel import sniff_excel_filename
from app.modules.warehouse.hardware.models import HardwareMaterial
from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn


def _xlsx_bytes(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["物资名称", "规格型号", "数量", "单位", "供应商", "送货单号", "备注"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 意图判定（纯函数）──


def test_hardware_inbound_intent():
    assert _is_hardware_inbound_intent("五金入库")
    assert _is_hardware_inbound_intent("五金模板")
    assert _is_hardware_inbound_intent("我要五金入库登记")
    assert _is_hardware_inbound_intent("五金入库模板发我")
    assert not _is_hardware_inbound_intent("五金 DN25 球阀还有多少")  # 查库存走 Runner
    assert not _is_hardware_inbound_intent("五金库存预警")
    assert not _is_hardware_inbound_intent("成品入库 达托霉素 100kg")  # 非五金
    assert not _is_hardware_inbound_intent("导出五金出库")  # 导出走 Runner 工具


def test_sniff_excel_filename():
    assert sniff_excel_filename("入库.xlsx")
    assert sniff_excel_filename("入库.XLSX")
    assert sniff_excel_filename("r.csv")
    assert sniff_excel_filename("r.xlsm")
    assert not sniff_excel_filename("photo.jpg")
    assert not sniff_excel_filename("doc.pdf")


# ── Excel 入库全链（mock 下载）──


async def test_process_hardware_excel_creates_draft(db_session, monkeypatch):
    """文件→解析→source=excel 草稿→AgentDraft（确认卡发送 mock 断言）。"""
    from app.modules.warehouse.agent.pipeline import draft_flow
    from app.modules.warehouse.hardware import gateway_excel

    m = HardwareMaterial(
        name=f"304不锈钢球阀·X{uuid4().hex[:4].upper()}", spec="DN25", unit="个",
        category="金属阀门", managed_class="stocked",
        safety_stock=Decimal("0"), no_expiry=True,
    )
    db_session.add(m)
    await db_session.flush()
    # AgentDraft 挂独立会话工厂——monkeypatch 掉确认卡发送避免双会话真写
    sent_cards: list[dict] = []

    async def fake_send_confirm_card(db, draft, *, chat_id="", open_id=""):
        sent_cards.append({"draft": draft.draft_no, "chat_id": chat_id})
        return None

    monkeypatch.setattr(draft_flow, "send_confirm_card", fake_send_confirm_card)

    # db_session 是回滚会话，而 process_hardware_excel 自管 async_session_factory——
    # 单测改走内部函数级组装：直接调解析+建单+草稿段（下载 mock 掉）
    async def fake_download(message_id, file_key):
        return _xlsx_bytes([
            [m.name, "DN25", 8, "个", "供应商X", "SH-X1", ""],
            [m.name, "DN25", "abc", "个", "", "", ""],  # 数量非法行
        ])

    monkeypatch.setattr(gateway_excel.media, "download_im_file", fake_download)

    # 走真实函数但替换会话工厂为当前测试会话（自管提交段 mock 成 no-op）
    class _FakeFactory:
        def __call__(self):
            return _FakeCtx(db_session)

    class _FakeCtx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "app.core.database.async_session_factory", _FakeFactory(), raising=False
    )
    await gateway_excel.process_hardware_excel(
        chat_id="oc_test", chat_type="p2p", open_id="ou_test",
        message_id="om_test", file_key="fk_test", file_name="入库.xlsx",
    )
    # source=excel 草稿已建（回滚会话内可见）
    from sqlalchemy import select

    from app.modules.warehouse.hardware.models import HardwareReceipt

    receipts = (
        await db_session.execute(
            select(HardwareReceipt).where(HardwareReceipt.source == "excel")
        )
    ).scalars().all()
    # 差分口径：dev 库可能有历史 excel 单——按测试专属供应商锁定本次行
    mine = [r for r in receipts if r.supplier_name == "供应商X"]
    assert mine, "本次测试的 source=excel 草稿未落库"
    assert receipts[0].ocr_result is not None  # excel_result 留痕复用 ocr_result 列
    # 确认卡发送已 mock 命中
    assert len(sent_cards) == 1


async def test_process_hardware_excel_groups_by_erp_doc_no(db_session, monkeypatch):
    """ERP 多单文件按「入库单号」分单：每张 ERP 单一张草稿+一张确认卡。"""
    from openpyxl import Workbook

    from app.modules.warehouse.agent.pipeline import draft_flow
    from app.modules.warehouse.hardware import gateway_excel

    m = HardwareMaterial(
        name=f"UPVC对夹蝶阀·E{uuid4().hex[:4].upper()}", spec="dn200", unit="个",
        category="塑料阀门", managed_class="stocked",
        safety_stock=Decimal("0"), no_expiry=True,
    )
    db_session.add(m)
    await db_session.flush()

    sent_cards: list[str] = []

    async def fake_send_confirm_card(db, draft, *, chat_id="", open_id=""):
        sent_cards.append(draft.draft_no)
        return None

    monkeypatch.setattr(draft_flow, "send_confirm_card", fake_send_confirm_card)

    # 随机单号（差分口径）：process 内显式 commit 会真落库，固定单号会被
    # 历史失败轮残留撞计数
    doc_a = f"CGRK-{uuid4().hex[:6].upper()}"
    doc_b = f"CGRK-{uuid4().hex[:6].upper()}"
    wb = Workbook()
    ws = wb.active
    ws.append(["入库单号", "入库日期", "物料名称", "主计量单位", "入库数量"])
    ws.append([doc_a, "2026-11-19", m.name, "个", 3])
    ws.append([doc_a, "2026-11-19", m.name, "个", 2])
    ws.append([doc_b, "2026-11-19", m.name, "个", 7])
    buf = io.BytesIO()
    wb.save(buf)

    async def fake_download(message_id, file_key):
        return buf.getvalue()

    monkeypatch.setattr(gateway_excel.media, "download_im_file", fake_download)

    class _FakeFactory:
        def __call__(self):
            return _FakeCtx(db_session)

    class _FakeCtx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "app.core.database.async_session_factory", _FakeFactory(), raising=False
    )
    await gateway_excel.process_hardware_excel(
        chat_id="oc_test", chat_type="p2p", open_id="ou_test",
        message_id="om_test", file_key="fk_test", file_name="erp导出.xlsx",
    )
    from sqlalchemy import select

    from app.modules.warehouse.hardware.models import HardwareReceipt

    receipts = (
        await db_session.execute(
            select(HardwareReceipt).where(
                HardwareReceipt.source == "excel",
                HardwareReceipt.delivery_note_no.in_([doc_a, doc_b]),
            )
        )
    ).scalars().all()
    assert len(receipts) == 2  # 两张 ERP 单 = 两张草稿
    by_doc = {r.delivery_note_no: r for r in receipts}
    from app.modules.warehouse.hardware.models import HardwareReceiptItem

    async def _row_count(receipt_id) -> int:
        rows_ = (
            await db_session.execute(
                select(HardwareReceiptItem).where(
                    HardwareReceiptItem.receipt_id == receipt_id
                )
            )
        ).scalars().all()
        return len(rows_)

    assert await _row_count(by_doc[doc_a].id) == 2
    assert await _row_count(by_doc[doc_b].id) == 1
    assert len(sent_cards) == 2  # 每张草稿一张确认卡


# ── 出库导出工具（mock 文件发送）──


async def test_export_hardware_requisitions_tool(db_session, monkeypatch):
    """导出工具：建两单→工具生成 Excel→发送命中→结果含单数与文件名。"""
    from app.modules.warehouse.agent.tools import hardware as hw_tools

    m = HardwareMaterial(
        name=f"对账阀·E{uuid4().hex[:4].upper()}", spec="DN25", unit="个",
        category="金属阀门", managed_class="stocked",
        safety_stock=Decimal("0"), no_expiry=True,
    )
    db_session.add(m)
    await db_session.flush()
    for _ in range(2):
        payload = ReceiptCreate(
            source="manual", mode="stocked",
            items=[ReceiptItemIn(material_id=str(m.id), name=m.name,
                                 spec=m.spec, unit=m.unit, quantity=Decimal("10"),
                                 match_confidence="manual")],
        )
        receipt = await hw.create_receipt(db_session, payload)
        await hw.accept_receipt(
            db_session, receipt.id,
            inspected_by_warehouse="ou_wh", inspected_by_dept="ou_dept",
        )
        req = await hw.create_requisition(
            db_session,
            __import__(
                "app.modules.warehouse.hardware.schemas", fromlist=["RequisitionCreate"]
            ).RequisitionCreate(
                dept_name="发酵", applicant="张三",
                items=[__import__(
                    "app.modules.warehouse.hardware.schemas", fromlist=["RequisitionItemIn"]
                ).RequisitionItemIn(material_id=str(m.id), need_qty=Decimal("3"))],
            ),
        )
        await hw.submit_requisition(db_session, req.id)

    # 注入测试会话 + mock 文件发送（_db_session 是 @asynccontextmanager 函数）
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_ctx_db():
        yield db_session

    sent: list[tuple[str, str]] = []

    async def fake_send(chat_id, file_bytes, file_name, **kw):
        sent.append((chat_id, file_name))
        assert file_bytes[:2] == b"PK"  # xlsx 魔数
        return True

    monkeypatch.setattr(hw_tools, "_db_session", _fake_ctx_db)
    from app.modules.warehouse.feishu import media as _media

    monkeypatch.setattr(_media, "send_file_to_chat", fake_send)

    result = await export_hardware_requisitions(
        status="pending", _ctx={"chat_id": "oc_test", "open_id": "ou_test"}
    )
    assert result.get("sent") is True
    assert result["requisitions"] >= 2
    assert "五金库领料出库台账_" in sent[0][1]
    assert sent[0][0] == "oc_test"


async def test_export_tool_requires_chat_id():
    result = await export_hardware_requisitions(_ctx={})
    assert "error" in result
