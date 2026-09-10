"""每日 Excel 更新：解析（异构/简化）→ 匹配总表行 → 更新存量（新增自动建行）。

不回群、不通知。匹配键：部门+存放部位+物料名称（简化格式缺存放部位时退化为 部门+物料名称）。
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import xlrd  # type: ignore[import-untyped]

from app.modules.safety.chemical_inventory.excel_parser import (
    ParsedRecord,
    _clean_name,
    _detect_fayifaer_columns,
    _limit_to_tonnes,
    _norm_unit,
    _parse_fayifaer_by_header,
    _parse_package_spec,
    _read_sheets,
    parse_workbook,
)
from app.modules.safety.chemical_inventory.excel_parser import (
    _num as _xnum,
)
from app.modules.safety.chemical_inventory.rules import _normalize_to_tonnes
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.chemical_inventory_bitable_handler import (
    _DEPT_ENUM_TO_LABEL,
    _UNIT_ENUM_TO_LABEL,
    _get_inventory_table_id,
    _set_sync_ignore,
    _text,
)

# 部门单表文件名 → 部门枚举（sheet 名未识别时用文件名兜底）
_FILENAME_TO_DEPT: list[tuple[str, str]] = [
    ("仓库", "warehouse"),
    ("提二", "extraction_2b"),
    ("发一", "fermentation_1"),
    ("发二", "fermentation_2"),
    ("提炼一期", "extraction_1"),
    ("提炼一部", "extraction_1"),
    ("提炼二期", "extraction_2"),
    ("QC", "qc"),
    ("精制", "purification"),
    ("技术精进", "tech_refine"),
    ("精进中心", "tech_refine"),
    ("半合成", "semi_synth"),
    ("菌种", "strain"),
    ("环保", "env"),
]


def _detect_dept_from_filename(filename: str) -> str | None:
    for kw, dept in _FILENAME_TO_DEPT:
        if kw in (filename or ""):
            return dept
    return None


# 文件名兜底时可走 fayifaer 表头驱动解析的部门（发一/发二/菌种/环保/精制 同族表头；
# 菌种 09-02 起 sheet 名不识别曾静默落空，靠此兜住 sheet 改名）
_FAYIFAER_FAMILY_DEPTS = {"fermentation_1", "fermentation_2", "strain", "env", "purification"}


logger = logging.getLogger(__name__)


def _parse_simple_sheet(sh: xlrd.sheet.Sheet) -> list[ParsedRecord]:
    """简化汇总格式：部门|名称|现场物料总量|单位（部门向下合并）。"""
    out: list[ParsedRecord] = []
    cur_dept: str | None = None
    for r in range(1, sh.nrows):
        dept = str(sh.cell_value(r, 0)).strip()
        name = str(sh.cell_value(r, 1)).strip()
        total = _num(sh.cell_value(r, 2))
        unit = str(sh.cell_value(r, 3)).strip()
        if dept and dept != "部门":
            cur_dept = dept
        if not name or name in ("名称", "各类危化品总量"):
            continue
        enum_dept = _label_to_dept(cur_dept or "")
        if not enum_dept:
            continue
        out.append(ParsedRecord(
            department=enum_dept,
            storage_location=None,
            material_name=name,
            quantity=None,
            unit=unit or "T",
            total_quantity_t=total,
        ))
    return out


def _num(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).strip())
    except Exception:  # noqa: BLE001
        return None


def _label_to_dept(label: str) -> str | None:
    """中文部门名 → 枚举。"""
    mapping = {
        "仓储部": "warehouse", "提炼一部": "extraction_1",
        "提炼二期": "extraction_2", "提炼二部": "extraction_2b",
        "发酵一部": "fermentation_1", "发酵二部": "fermentation_2",
        "精制": "purification", "菌种中心": "strain", "QC": "qc",
        "环保": "env", "环保工程部": "env",
        "提炼半合成工程中心": "semi_synth", "提炼技术精进中心": "tech_refine",
        "提炼精进中心": "tech_refine",
    }
    for k, v in mapping.items():
        if k in label:
            return v
    return None


def _parse_tech_refine_daily(sh: Any, dept: str) -> list[ParsedRecord]:
    """提炼技术精进中心日报（08.26 起 Sheet1，8 列）。

    列位：存放部位|物料名称|包装规格|库存|库存量|中间列|库存上限|单位
    """
    out: list[ParsedRecord] = []
    cur_loc = None
    for r in range(2, sh.nrows):
        loc = _clean_name(sh.cell_value(r, 0))
        if loc:
            cur_loc = loc.replace("\n", "/")
        name = _clean_name(sh.cell_value(r, 1))
        if not name or name in ("物料名称", "名称"):
            continue
        spec = _parse_package_spec(sh.cell_value(r, 2))
        qty = _xnum(sh.cell_value(r, 4))  # 库存量
        unit = _norm_unit(sh.cell_value(r, 7))
        limit, limit_unit = _limit_to_tonnes(sh.cell_value(r, 6), unit)
        total = _normalize_to_tonnes(qty, unit, spec) if qty is not None else None
        out.append(ParsedRecord(
            department=dept, storage_location=cur_loc, material_name=name,
            package_spec=spec, quantity=qty, unit=unit, total_quantity_t=total,
            max_limit=limit, max_limit_unit=limit_unit,
        ))
    return out


def parse_daily_workbook(path: str, file_name: str | None = None) -> list[ParsedRecord]:
    """兼容异构明细（含部门单表 .xlsx / .xls）+ 简化汇总两种格式。"""
    records = parse_workbook(path)
    if records:
        return records
    # 部门单表兜底：sheet 名未识别时按文件名识别部门 + 列位解析
    if file_name:
        dept = _detect_dept_from_filename(file_name)
        if dept:
            sheets = _read_sheets(path)
            for _, sh in sheets:
                if sh.nrows <= 1:
                    continue
                if dept == "tech_refine":
                    return _parse_tech_refine_daily(sh, dept)
                if dept in _FAYIFAER_FAMILY_DEPTS:
                    detected = _detect_fayifaer_columns(sh)
                    if detected is not None:
                        return _parse_fayifaer_by_header(sh, dept, detected)
    # 简化汇总：取第一个 sheet 或「汇总」
    sheets = _read_sheets(path)
    names = [n for n, _ in sheets]
    target = "汇总" if "汇总" in names else (names[0] if names else None)
    if target is None:
        return []
    sh = dict(sheets)[target]
    return _parse_simple_sheet(sh)


async def _batch_update(client: SafetyBitableClient, payload: list[dict[str, Any]]) -> int:
    """飞书 batch_update（500/批），返回成功条数。"""
    import httpx

    if not payload:
        return 0
    token = await client._token()
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{client.app_token}"
        f"/tables/{client.table_id}/records/batch_update"
    )
    written = 0
    async with httpx.AsyncClient(timeout=120) as http:
        for i in range(0, len(payload), 500):
            chunk = payload[i : i + 500]
            resp = await http.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"records": chunk},
            )
            d = resp.json()
            if d.get("code") == 0:
                written += len(d.get("data", {}).get("records", []))
            else:
                logger.error("batch_update 失败: code=%s msg=%s", d.get("code"), d.get("msg"))
    return written


async def _batch_create(client: SafetyBitableClient, records: list[dict[str, Any]]) -> int:
    """飞书 batch_create（500/批），返回成功条数。"""
    import httpx

    if not records:
        return 0
    token = await client._token()
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{client.app_token}"
        f"/tables/{client.table_id}/records/batch_create"
    )
    created = 0
    async with httpx.AsyncClient(timeout=120) as http:
        for i in range(0, len(records), 500):
            chunk = records[i : i + 500]
            resp = await http.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"records": [{"fields": f} for f in chunk]},
            )
            d = resp.json()
            if d.get("code") == 0:
                created += len(d.get("data", {}).get("records", []))
            else:
                logger.error("batch_create 失败: code=%s msg=%s", d.get("code"), d.get("msg"))
    return created


async def apply_daily_workbook(path: str, app_token: str, file_name: str | None = None) -> dict[str, Any]:
    """解析当日 Excel 并按 部门+存放部位+物料名称 更新总表存量（批量写回）。"""
    records = parse_daily_workbook(path, file_name=file_name)
    table_id = _get_inventory_table_id()
    client = SafetyBitableClient(app_token=app_token, table_id=table_id)

    items = await client.list_all_records()
    # 建匹配索引：部门中文 + 部位 + 物料 → record_id
    idx_full: dict[tuple[str, str, str], str] = {}
    idx_dept_name: dict[tuple[str, str], list[str]] = {}
    for item in items:
        f = item.get("fields", {}) or {}
        dept = _text(f.get("部门") or "") or ""
        loc = _text(f.get("存放部位") or "") or ""
        name = _text(f.get("物料名称") or "") or ""
        rid = item.get("record_id", "")
        if not name or not rid:
            continue
        idx_full[(dept, loc, name)] = rid
        idx_dept_name.setdefault((dept, name), []).append(rid)

    updates: list[dict[str, Any]] = []
    creates: list[dict[str, Any]] = []
    for r in records:
        dept_label = _DEPT_ENUM_TO_LABEL.get(r.department, r.department)
        fields: dict[str, Any] = {}
        if r.total_quantity_t is not None:
            fields["现场物料总量(T)"] = float(r.total_quantity_t)
        if r.quantity is not None:
            fields["库存数量"] = float(r.quantity)
        if r.unit:
            fields["单位"] = _UNIT_ENUM_TO_LABEL.get(r.unit, r.unit)
        if r.max_limit is not None:
            fields["库存上限"] = float(r.max_limit)
        if not fields:
            continue

        rid = idx_full.get((dept_label, r.storage_location or "", r.material_name))
        if rid is None and not r.storage_location:
            candidates = idx_dept_name.get((dept_label, r.material_name), [])
            if len(candidates) == 1:
                rid = candidates[0]
        if rid:
            await _set_sync_ignore(rid)
            updates.append({"record_id": rid, "fields": fields})
        else:
            new_fields: dict[str, Any] = {
                "物料名称": r.material_name,
                "部门": dept_label,
            }
            if r.storage_location:
                new_fields["存放部位"] = r.storage_location
            if r.package_spec:
                new_fields["包装规格"] = r.package_spec
            new_fields.update(fields)
            creates.append(new_fields)

    updated = await _batch_update(client, updates)
    created = await _batch_create(client, creates)

    return {"parsed": len(records), "updated": updated, "created": created}
