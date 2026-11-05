"""五金库 ERP 导入通道 A 档（三期 M8，设计 §六）。

文件上传（管理端）→ 解析器（**列映射可配置**：runtime_configs 键
``hardware_erp_column_mapping``，空/非法回落内置默认映射；ERP 样例文件到位
后只调映射不改代码）→ ``erp_doc_no`` 幂等去重（一期建表已有唯一约束）→
按单据号分组生成 ``source=erp_import`` 入库单（**status=draft 待核对**，
行走四级匹配挂主数据——matcher 复用，低置信标黄只标记不代改）→ 导入尾部
自动触发并存对账匹配（erp_reconcile）+ M9 自动入账评估（开关关=短路零副作用）。

B/C 档（定时取文件/API 直连）只留 adapter 接口骨架
（platform/integrations/erp/adapter.py），本文件不实现。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware import matcher as hw_matcher
from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import HardwareMaterial, HardwareReceipt
from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn
from app.modules.warehouse.ops_config.runtime_store import runtime_store

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")

#: 内置默认列映射（键=系统字段，值=ERP 导出列头；ERP 样例到位后 runtime 调整）
DEFAULT_ERP_COLUMN_MAPPING: dict[str, str] = {
    "doc_no": "单据号",
    "date": "日期",
    "supplier": "供应商",
    "material_code": "物料编码",
    "name": "品名",
    "spec": "规格型号",
    "quantity": "数量",
    "unit": "单位",
    "dept": "部门",
}

_MAPPING_FIELDS = tuple(DEFAULT_ERP_COLUMN_MAPPING)

#: runtime_configs 列映射键（runtime_registry 注册）
ERP_COLUMN_MAPPING_KEY = "hardware_erp_column_mapping"

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%Y%m%d")


def get_column_mapping() -> dict[str, str]:
    """列映射：runtime_configs 键（JSON）优先，空/非法回落内置默认。

    容错原则：映射只认 _MAPping_FIELDS 白名单键（防注入未知字段）；解析失败
    静默回落默认（导入是人工操作，错误提示由调用方给）。
    """
    try:
        raw = runtime_store.get_value(ERP_COLUMN_MAPPING_KEY)
    except Exception:  # noqa: BLE001 — 未知 key/DB 失败一律回落默认
        raw = None
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ERP 列映射 JSON 非法，回落内置默认映射")
            return dict(DEFAULT_ERP_COLUMN_MAPPING)
        if isinstance(parsed, dict) and parsed:
            merged = {
                k: str(v).strip()
                for k, v in parsed.items()
                if k in _MAPPING_FIELDS and str(v).strip()
            }
            if merged:
                return {**DEFAULT_ERP_COLUMN_MAPPING, **merged}
    return dict(DEFAULT_ERP_COLUMN_MAPPING)


@dataclass
class ErpRow:
    """ERP 导出文件单行（解析器输出）。"""

    doc_no: str
    date: str | None = None
    supplier: str | None = None
    material_code: str | None = None
    name: str = ""
    spec: str | None = None
    quantity: Decimal = ZERO
    unit: str | None = None
    dept: str | None = None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_quantity(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _parse_date_str(value: Any) -> str | None:
    """统一转 YYYY-MM-DD（openpyxl 日期对象/多种文本格式容错）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    import datetime as _dt

    if isinstance(value, _dt.date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text or None  # 无法解析原样保留（draft 待人工核对）


def _read_rows(data: bytes, filename: str) -> tuple[list[str], list[list[Any]]]:
    """读文件为 (表头, 行二维表)：xlsx（openpyxl）与 csv（utf-8-sig/gbk 容错）。"""
    lower = filename.lower()
    if lower.endswith(".csv"):
        for encoding in ("utf-8-sig", "gbk"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", errors="replace")
        reader = list(csv.reader(io.StringIO(text)))
        rows = [r for r in reader if any(str(c).strip() for c in r)]
        if not rows:
            return [], []
        return [str(c).strip() for c in rows[0]], rows[1:]
    if lower.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        matrix: list[list[Any]] = [
            [cell for cell in row] for row in ws.iter_rows(values_only=True)
        ]
        wb.close()
        rows = [r for r in matrix if any(c is not None and str(c).strip() for c in r)]
        if not rows:
            return [], []
        return [str(c).strip() if c is not None else "" for c in rows[0]], rows[1:]
    raise ValueError("仅支持 xlsx/csv 文件")


def parse_erp_file(
    data: bytes, filename: str, mapping: dict[str, str] | None = None
) -> list[ErpRow]:
    """ERP 导出文件 → 行列表（纯函数；列映射驱动，缺列=字段为空）。

    单据号/品名/数量任一缺失的行丢弃并计数（结构行/空行/小计行）。
    """
    col_map = mapping or get_column_mapping()
    headers, matrix = _read_rows(data, filename)
    header_index: dict[str, int] = {}
    for idx, h in enumerate(headers):
        header_index[h.strip()] = idx
    field_index = {
        f: header_index[col] for f, col in col_map.items() if col in header_index
    }

    rows: list[ErpRow] = []
    for raw in matrix:
        def cell(f: str) -> Any:
            idx = field_index.get(f)
            return raw[idx] if idx is not None and idx < len(raw) else None

        doc_no = _clean(cell("doc_no"))
        name = _clean(cell("name"))
        qty = _parse_quantity(cell("quantity"))
        if not doc_no or not name or qty is None or qty <= ZERO:
            continue
        rows.append(
            ErpRow(
                doc_no=doc_no,
                date=_parse_date_str(cell("date")),
                supplier=_clean(cell("supplier")),
                material_code=_clean(cell("material_code")),
                name=name,
                spec=_clean(cell("spec")),
                quantity=qty,
                unit=_clean(cell("unit")),
                dept=_clean(cell("dept")),
            )
        )
    return rows


async def import_erp_file(
    db: AsyncSession,
    *,
    data: bytes,
    filename: str,
    operator: str | None = None,
    mapping: dict[str, str] | None = None,
    auto_reconcile: bool = True,
) -> dict[str, Any]:
    """ERP 文件导入：去重 → 分组建 draft 单 → 对账匹配 → M9 评估。

    - erp_doc_no 幂等：库中已有（任何状态非删除）→ 该单整体 skip；
    - 行四级匹配挂主数据（unmatched 行 material_id=NULL 自由文本，draft 人工核对）；
    - mode 行级判定（全部行 direct=direct 单，否则 stocked——照 OCR 管线口径）；
    - auto_reconcile=True 尾部逐单触发并存对账（erp_reconcile.match_erp_receipt）；
    - M9 try_auto_accept_direct 尾部评估（开关关=短路返回 None）。
    """
    rows = parse_erp_file(data, filename, mapping)
    if not rows:
        raise hw_service.HardwareError("文件无有效数据行（须含 单据号/品名/数量 列）", status_code=422)

    doc_nos = sorted({r.doc_no for r in rows})
    existing = set(
        (
            await db.execute(
                select(HardwareReceipt.erp_doc_no).where(
                    HardwareReceipt.erp_doc_no.in_(doc_nos),
                    HardwareReceipt.is_deleted.is_(False),
                )
            )
        ).scalars().all()
    )

    materials = list(
        (
            await db.execute(
                select(HardwareMaterial).where(
                    HardwareMaterial.is_deleted.is_(False),
                    HardwareMaterial.active.is_(True),
                )
            )
        ).scalars().all()
    )

    by_doc: dict[str, list[ErpRow]] = {}
    for r in rows:
        by_doc.setdefault(r.doc_no, []).append(r)

    created: list[dict[str, Any]] = []
    skipped = 0
    for doc_no, doc_rows in sorted(by_doc.items()):
        if doc_no in existing:
            skipped += 1
            continue
        first = doc_rows[0]
        # 行四级匹配 + 行级 mode 判定（stocked/direct 边界=物资清单本身）
        items: list[ReceiptItemIn] = []
        match_summary: list[dict[str, Any]] = []
        matched_stocked = matched_direct = unmatched = 0
        for r in doc_rows:
            result = hw_matcher.match_one(
                code=r.material_code, name=r.name, spec=r.spec, materials=materials
            )
            items.append(
                ReceiptItemIn(
                    material_id=str(result.material.id) if result.material else None,
                    name=result.material.name if result.material else r.name,
                    spec=result.material.spec if result.material else r.spec,
                    unit=result.material.unit if result.material else r.unit,
                    quantity=r.quantity,
                    match_confidence=result.method,
                    match_score=result.score,
                )
            )
            if result.material and result.material.managed_class == "stocked":
                matched_stocked += 1
            elif result.material:
                matched_direct += 1
            else:
                unmatched += 1
            match_summary.append({
                "erp_name": r.name,
                "erp_spec": r.spec,
                "quantity": float(r.quantity),
                "matched": result.material.name if result.material else None,
                "method": result.method,
                "score": float(result.score),
                "low_confidence": result.low_confidence,
            })
        # mode 行级判定：只要有 stocked 物料行=stocked 单；否则 direct
        # （含 matched_direct 与 unmatched——direct 物料行与清单外行同属直发）
        mode = "stocked" if matched_stocked > 0 else "direct"
        arrived = None
        if first.date:
            try:
                arrived = datetime.strptime(first.date, "%Y-%m-%d").replace(tzinfo=CN_TZ)
            except ValueError:
                arrived = None

        payload = ReceiptCreate(
            source="erp_import",
            mode=mode,  # type: ignore[arg-type]
            erp_doc_no=doc_no,
            supplier_name=first.supplier,
            arrived_at=arrived or datetime.now(CN_TZ),
            target_dept=first.dept if mode == "direct" else None,
            remark=f"ERP 导入（{filename}）",
            items=items,
        )
        receipt = await hw_service.create_receipt(db, payload)
        receipt.erp_imported_at = datetime.now(CN_TZ)
        receipt.ocr_result = {
            "channel": "erp_import",
            "filename": filename,
            "match_summary": match_summary,
        }
        await db.flush()
        created.append({
            "receipt_id": str(receipt.id),
            "receipt_no": receipt.receipt_no,
            "erp_doc_no": doc_no,
            "mode": mode,
            "rows": len(doc_rows),
            "matched_stocked": matched_stocked,
            "matched_direct": matched_direct,
            "unmatched": unmatched,
        })

    # 尾部编排：并存对账 + M9 自动入账评估（逐单；失败不阻断导入主流程）
    reconcile_stats = {"matched": 0, "unmatched": 0}
    auto_accepted = 0
    if auto_reconcile:
        from app.modules.warehouse.hardware import erp_reconcile

        for entry in created:
            receipt = await db.get(HardwareReceipt, _uuid.UUID(entry["receipt_id"]))
            status = await erp_reconcile.match_erp_receipt(db, receipt)
            reconcile_stats["matched" if status == "verified" else "unmatched"] += 1
            entry["reconcile_status"] = status
    from app.modules.warehouse.hardware.service import try_auto_accept_direct

    for entry in created:
        receipt = await db.get(HardwareReceipt, _uuid.UUID(entry["receipt_id"]))
        auto = await try_auto_accept_direct(db, receipt.id, operator=operator or "erp_import")
        if auto is not None:
            auto_accepted += 1
            entry["auto_accepted"] = True

    logger.info(
        "ERP 文件导入完成: file=%s 单=%d skip=%d 对账匹配=%d auto=%d",
        filename, len(created), skipped, reconcile_stats["matched"], auto_accepted,
    )
    return {
        "created": len(created),
        "skipped": skipped,
        "receipts": created,
        "reconcile": reconcile_stats,
        "auto_accepted": auto_accepted,
    }
