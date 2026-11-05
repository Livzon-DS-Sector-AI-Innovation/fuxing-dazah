"""五金库 M8 验收测试：ERP A 档导入（fixture 驱动/幂等/列映射可配置）
+ OCR↔ERP 并存对账（匹配对/差异对判定/双向 verified/防双计闸/补录入账）。

设计依据：docs/DESIGN-五金库系统原生模块-20261104.md §六；spec
.scratch/hardware-store-p3/spec.md §4（ERP 单=对账载体，OCR 单是库存权威）。
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.modules.warehouse.hardware import erp_import as ei
from app.modules.warehouse.hardware import erp_reconcile as rc
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareReceipt,
    HardwareReceiptItem,
)

CN_TZ = ZoneInfo("Asia/Shanghai")

#: 内置默认列映射（与 erp_import.DEFAULT_ERP_COLUMN_MAPPING 一致——独立事实源防漂移）
_HEADERS = ["单据号", "日期", "供应商", "物料编码", "品名", "规格型号", "数量", "单位", "部门"]


# ── 造数工具 ──


async def _mk_material(db, *, name="ERP物料", spec="DN25", unit="个",
                       managed_class="stocked", price=Decimal("9.0000")):
    from app.modules.warehouse.hardware.models import HardwareMaterial

    material = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec=spec, unit=unit,
        category="金属阀门", managed_class=managed_class, safety_stock=Decimal("10"),
        no_expiry=True, unit_price=price,
    )
    db.add(material)
    await db.flush()
    return material


async def _mk_accepted_ocr(db, material, qty: Decimal, *, supplier="测试供应商",
                           arrived=None) -> HardwareReceipt:
    """accepted OCR/manual 单（对账匹配对「ocr 侧」）。"""
    from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn

    payload = ReceiptCreate(
        source="manual", mode="stocked", supplier_name=supplier,
        arrived_at=arrived,
        items=[ReceiptItemIn(
            material_id=str(material.id), name=material.name,
            spec=material.spec, unit=material.unit, quantity=qty,
            match_confidence="manual", unit_price=material.unit_price,
        )],
    )
    receipt = await hw.create_receipt(db, payload)
    return await hw.accept_receipt(
        db, receipt.id, inspected_by_warehouse="ou_w", inspected_by_dept="ou_d",
    )


def _erp_xlsx(rows: list[list[Any]], *, headers: list[str] | None = None) -> bytes:
    """现造 ERP 导出 xlsx fixture（测试自备数据，不依赖外部文件）。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "入库单"
    ws.append(headers or _HEADERS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _erp_csv(rows: list[list[Any]], *, headers: list[str] | None = None) -> bytes:
    import csv as _csv

    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(headers or _HEADERS)
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8")


def _erp_rows(material, *, doc_no: str, qty: str = "5", name: str | None = None,
              spec: str | None = None, supplier: str = "测试供应商") -> list[list[Any]]:
    return [[
        doc_no, "2026-11-04", supplier, "", name or material.name,
        spec or material.spec, qty, material.unit, "发酵",
    ]]


# ── A 档导入 ──


async def test_erp_import_xlsx_creates_draft(db_session):
    """fixture xlsx 导入 → erp_import 单（draft 待核对），行四级匹配挂主数据。"""
    m = await _mk_material(db_session, name="导入物料甲")
    data = _erp_xlsx(_erp_rows(m, doc_no=f"ERP-{uuid4().hex[:8].upper()}"))

    result = await ei.import_erp_file(
        db_session, data=data, filename="erp_test.xlsx", auto_reconcile=False
    )
    assert result["created"] == 1
    entry = result["receipts"][0]
    assert entry["matched_stocked"] == 1  # 名称精确匹配挂上主数据

    receipt = await db_session.get(HardwareReceipt, UUID(entry["receipt_id"]))
    assert receipt is not None
    assert receipt.source == "erp_import"
    assert receipt.status == "draft"  # 待核对（不自动入账）
    assert receipt.erp_doc_no == entry["erp_doc_no"]
    assert receipt.erp_imported_at is not None
    assert receipt.reconcile_status == "none"

    items = await hw.list_receipt_items(db_session, receipt.id)
    assert items[0].material_id == m.id
    assert items[0].match_confidence == "name_spec"


async def test_erp_import_csv_and_direct_mode(db_session):
    """csv 同样支持；全部行清单外=direct 单（出入双流水语义待 accept）。"""
    direct_m = await _mk_material(db_session, name="direct导入物", managed_class="direct")
    doc = f"ERP-D-{uuid4().hex[:8].upper()}"
    data = _erp_csv(_erp_rows(direct_m, doc_no=doc))

    result = await ei.import_erp_file(
        db_session, data=data, filename="erp_test.csv", auto_reconcile=False
    )
    assert result["created"] == 1
    assert result["receipts"][0]["mode"] == "direct"


async def test_erp_import_dedup_idempotent(db_session):
    """验收：同文件二次导入零新增（erp_doc_no 幂等去重）。"""
    m = await _mk_material(db_session, name="幂等物料")
    doc = f"ERP-{uuid4().hex[:8].upper()}"
    data = _erp_xlsx(_erp_rows(m, doc_no=doc))

    first = await ei.import_erp_file(db_session, data=data, filename="a.xlsx", auto_reconcile=False)
    assert first["created"] == 1 and first["skipped"] == 0

    second = await ei.import_erp_file(db_session, data=data, filename="a.xlsx", auto_reconcile=False)
    assert second["created"] == 0  # 零新增
    assert second["skipped"] == 1

    total = await db_session.scalar(
        select(func.count()).select_from(HardwareReceipt).where(
            HardwareReceipt.erp_doc_no == doc,
            HardwareReceipt.is_deleted.is_(False),
        )
    )
    assert total == 1


async def test_erp_column_mapping_runtime_override(db_session, monkeypatch):
    """验收：列映射改配置生效（runtime_configs 键驱动；非法 JSON 回落默认）。"""
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    m = await _mk_material(db_session, name="映射物料")
    # 自造文件：列头与内置默认不同（「单号」「货品名称」「件数」）
    custom_headers = ["单号", "货品名称", "件数", "往来单位"]
    doc = f"ERP-M-{uuid4().hex[:8].upper()}"
    data = _erp_xlsx(
        [[doc, m.name, "7", "供应商X"]],
        headers=custom_headers,
    )

    # 默认映射解析不了（品名列缺失→无有效行）
    with pytest.raises(hw.HardwareError, match="无有效数据行"):
        await ei.import_erp_file(db_session, data=data, filename="m.xlsx", auto_reconcile=False)

    # 改 runtime 配置（测试桩：体内后装覆盖 conftest 钉的两键之外自由）
    mapping = {"doc_no": "单号", "name": "货品名称", "quantity": "件数", "supplier": "往来单位"}
    original = runtime_store.get_value

    def _fake_get_value(key: str) -> Any:
        if key == ei.ERP_COLUMN_MAPPING_KEY:
            return json.dumps(mapping, ensure_ascii=False)
        return original(key)

    monkeypatch.setattr(runtime_store, "get_value", _fake_get_value)
    result = await ei.import_erp_file(db_session, data=data, filename="m.xlsx", auto_reconcile=False)
    assert result["created"] == 1
    entry = result["receipts"][0]
    assert entry["matched_stocked"] == 1

    # 非法 JSON 回落默认映射（不抛错）
    def _bad_value(key: str) -> Any:
        if key == ei.ERP_COLUMN_MAPPING_KEY:
            return "{不是json"
        return original(key)

    monkeypatch.setattr(runtime_store, "get_value", _bad_value)
    with pytest.raises(hw.HardwareError, match="无有效数据行"):
        await ei.import_erp_file(db_session, data=data, filename="m2.xlsx", auto_reconcile=False)


# ── 并存对账 ──


async def _mk_erp_receipt(db, material, *, supplier, qty=Decimal("5")) -> HardwareReceipt:
    """erp_import draft 单（对账「erp 侧」）。"""
    from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn

    payload = ReceiptCreate(
        source="erp_import", mode="stocked", supplier_name=supplier,
        erp_doc_no=f"ERP-{uuid4().hex[:8].upper()}",
        items=[ReceiptItemIn(
            material_id=str(material.id), name=material.name,
            spec=material.spec, unit=material.unit, quantity=qty,
            match_confidence="name_spec", match_score=Decimal("98"),
        )],
    )
    receipt = await hw.create_receipt(db, payload)
    receipt.erp_imported_at = datetime.now(CN_TZ)
    await db.flush()
    return receipt


async def test_reconcile_match_pair_verified(db_session):
    """验收：匹配对判定正确——同供应商∧±3天∧行对上 → 双向 verified 互指。"""
    m = await _mk_material(db_session, name="对账物料甲")
    ocr = await _mk_accepted_ocr(db_session, m, Decimal("5"), supplier="上海xx有限公司")
    erp = await _mk_erp_receipt(db_session, m, supplier="上海xx有限公司")  # 同供应商同行同量

    status = await rc.match_erp_receipt(db_session, erp)
    assert status == "verified"
    await db_session.refresh(erp)
    await db_session.refresh(ocr)
    assert erp.reconcile_status == "verified"
    assert ocr.reconcile_status == "verified"
    assert erp.matched_receipt_id == ocr.id
    assert ocr.matched_receipt_id == erp.id
    # 对账载体零动账：erp 单仍 draft（不入账，库存由 OCR 单承载）
    assert erp.status == "draft"
    erp_items = await hw.list_receipt_items(db_session, erp.id)
    assert erp_items
    assert all(i.remaining_quantity is None for i in erp_items)


async def test_reconcile_diff_pairs_two_columns(db_session):
    """验收：差异对判定正确 + 差异清单两栏数据正确（匹配对/差异对各 2）。"""
    # 匹配对 ×2（两个物料各自配对，数量须一致）
    m1 = await _mk_material(db_session, name="对账物料乙")
    m2 = await _mk_material(db_session, name="对账物料丙")
    ocr1 = await _mk_accepted_ocr(db_session, m1, Decimal("3"), supplier="供应商甲")
    erp1 = await _mk_erp_receipt(db_session, m1, supplier="供应商甲", qty=Decimal("3"))
    ocr2 = await _mk_accepted_ocr(db_session, m2, Decimal("4"), supplier="供应商乙")
    erp2 = await _mk_erp_receipt(db_session, m2, supplier="供应商乙", qty=Decimal("4"))
    assert await rc.match_erp_receipt(db_session, erp1) == "verified"
    assert await rc.match_erp_receipt(db_session, erp2) == "verified"

    # 差异对 ×2：erp 有 ocr 无（供应商无对应 ocr 单）+ ocr 有 erp 无
    m3 = await _mk_material(db_session, name="对账物料丁")
    erp3 = await _mk_erp_receipt(db_session, m3, supplier="孤儿供应商")  # 无对应 ocr
    assert await rc.match_erp_receipt(db_session, erp3) == "unmatched"
    m4 = await _mk_material(db_session, name="对账物料戊")
    ocr4 = await _mk_accepted_ocr(db_session, m4, Decimal("9"), supplier="孤儿ocr供应商")

    diffs = await rc.list_reconcile_diffs(db_session, days=30)
    erp_ids = {d["receipt_id"] for d in diffs["erp_only"]}
    ocr_ids = {d["receipt_id"] for d in diffs["ocr_only"]}
    assert str(erp1.id) not in erp_ids and str(erp2.id) not in erp_ids  # 匹配对不进差异
    assert str(erp3.id) in erp_ids                                      # erp 有 ocr 无
    assert str(ocr4.id) in ocr_ids                                      # ocr 有 erp 无
    assert str(ocr1.id) not in ocr_ids                                  # 已 verified 不进差异


async def test_verified_erp_cannot_accept_against_double_count(db_session):
    """防双计红线：verified ERP 单 accept_receipt 被拦截；unmatched 可补录入账。"""
    m = await _mk_material(db_session, name="双计物料")
    ocr = await _mk_accepted_ocr(db_session, m, Decimal("5"), supplier="双计供应商")
    erp = await _mk_erp_receipt(db_session, m, supplier="双计供应商")
    await rc.match_erp_receipt(db_session, erp)
    await db_session.refresh(erp)
    assert erp.reconcile_status == "verified"

    with pytest.raises(hw.HardwareError, match="不可重复入账"):
        await hw.accept_receipt(
            db_session, erp.id, inspected_by_warehouse="ou_w", inspected_by_dept="ou_d"
        )

    # unmatched ERP 单（无 OCR 对应）→ 人工确认=补录入账（生成批次，正常路径）
    m2 = await _mk_material(db_session, name="补录物料")
    erp2 = await _mk_erp_receipt(db_session, m2, supplier="无对供应商", qty=Decimal("8"))
    await rc.match_erp_receipt(db_session, erp2)
    await db_session.refresh(erp2)
    assert erp2.reconcile_status == "unmatched"
    accepted = await hw.accept_receipt(
        db_session, erp2.id, inspected_by_warehouse="ou_w", inspected_by_dept="ou_d"
    )
    assert accepted.status == "accepted"
    detail = await hw.get_material_stock(db_session, m2.id)
    assert detail["on_hand"] == Decimal("8")  # 补录批次占库存
