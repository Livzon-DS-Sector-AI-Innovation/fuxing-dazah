"""Excel 全量导入多维表格：清空 → 解析 → 去重合并 → 写入飞书 → 同步 DB → 规则回填。"""
from __future__ import annotations

import logging
from collections import OrderedDict
from decimal import Decimal
from typing import Any

from app.modules.safety.chemical_inventory.excel_parser import (
    ParsedRecord,
    parse_workbook,
)
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.chemical_inventory_bitable_handler import (
    _DEPT_ENUM_TO_LABEL,
    _HAZARD_ENUM_TO_LABEL,
    _UNIT_ENUM_TO_LABEL,
    _get_inventory_table_id,
)

logger = logging.getLogger(__name__)


def _merge_records(records: list[ParsedRecord]) -> list[dict[str, Any]]:
    """按 部门+存放部位+物料名称 去重合并（总量相加、危险性并集、规格拼接）。"""
    merged: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
    for r in records:
        key = (r.department, r.storage_location or "", r.material_name)
        if key not in merged:
            merged[key] = {
                "department": r.department,
                "storage_location": r.storage_location,
                "material_name": r.material_name,
                "package_specs": [r.package_spec] if r.package_spec else [],
                "total": r.total_quantity_t or Decimal("0"),
                "hazards": set(r.hazard_classes),
                "max_limit": r.max_limit,
                "max_limit_unit": r.max_limit_unit,
                "category": r.category,
                "quantity": r.quantity if r.unit else None,
                "unit": r.unit,
            }
        else:
            m = merged[key]
            m["total"] += r.total_quantity_t or Decimal("0")
            m["hazards"].update(r.hazard_classes)
            if r.package_spec and r.package_spec not in m["package_specs"]:
                m["package_specs"].append(r.package_spec)
            if r.max_limit is not None:
                m["max_limit"] = r.max_limit
                m["max_limit_unit"] = r.max_limit_unit
            if r.unit and m["unit"] and r.unit != m["unit"]:
                m["quantity"] = None  # 混合单位：只保留总量
                m["unit"] = None

    out: list[dict[str, Any]] = []
    for m in merged.values():
        out.append({
            "department": m["department"],
            "storage_location": m["storage_location"],
            "material_name": m["material_name"],
            "package_spec": "、".join(m["package_specs"]) or None,
            "quantity": m["quantity"],
            "unit": m["unit"],
            "total_quantity_t": m["total"],
            "max_limit": m["max_limit"],
            "max_limit_unit": m["max_limit_unit"],
            "hazard_classes": sorted(m["hazards"]),
            "category": m["category"],
        })
    return out


def _to_bitable_fields(m: dict[str, Any]) -> dict[str, Any]:
    """DB 枚举 → 飞书中文字段。"""
    fields: dict[str, Any] = {
        "物料名称": m["material_name"],
        "部门": _DEPT_ENUM_TO_LABEL.get(m["department"], m["department"]),
    }
    if m["storage_location"]:
        fields["存放部位"] = m["storage_location"]
    if m["package_spec"]:
        fields["包装规格"] = m["package_spec"]
    if m["quantity"] is not None:
        fields["库存数量"] = float(m["quantity"])
    if m["unit"]:
        fields["单位"] = _UNIT_ENUM_TO_LABEL.get(m["unit"], m["unit"])
    if m["total_quantity_t"] is not None:
        fields["现场物料总量(T)"] = float(m["total_quantity_t"])
    if m["max_limit"] is not None:
        fields["库存上限"] = float(m["max_limit"])
    if m["max_limit_unit"]:
        fields["上限单位"] = _UNIT_ENUM_TO_LABEL.get(m["max_limit_unit"], m["max_limit_unit"])
    if m["hazard_classes"]:
        fields["危险性"] = [_HAZARD_ENUM_TO_LABEL.get(h, h) for h in m["hazard_classes"]]
    if m["category"]:
        fields["品类"] = m["category"]
    return fields


async def _batch_delete(client: SafetyBitableClient, record_ids: list[str]) -> int:
    """飞书 batch_delete（500/批）批量删记录。"""
    import httpx

    if not record_ids:
        return 0
    token = await client._token()
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{client.app_token}"
        f"/tables/{client.table_id}/records/batch_delete"
    )
    deleted = 0
    async with httpx.AsyncClient(timeout=120) as http:
        for i in range(0, len(record_ids), 500):
            chunk = record_ids[i : i + 500]
            resp = await http.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"records": chunk},
            )
            data = resp.json()
            if data.get("code") == 0:
                deleted += len(data.get("data", {}).get("records", []))
            else:
                logger.error("batch_delete 失败: code=%s msg=%s", data.get("code"), data.get("msg"))
    return deleted


async def _batch_create(client: SafetyBitableClient, records: list[dict[str, Any]]) -> int:
    """飞书 batch_create（500/批）批量建记录。返回成功条数。"""
    import httpx

    token = await client._token()
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{client.app_token}"
        f"/tables/{client.table_id}/records/batch_create"
    )
    created = 0
    async with httpx.AsyncClient(timeout=120) as http:
        for i in range(0, len(records), 500):
            chunk = records[i : i + 500]
            payload = {"records": [{"fields": f} for f in chunk]}
            resp = await http.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            data = resp.json()
            if data.get("code") == 0:
                created += len(data.get("data", {}).get("records", []))
            else:
                logger.error("batch_create 失败: code=%s msg=%s", data.get("code"), data.get("msg"))
    return created


async def import_workbook_to_bitable(path: str, app_token: str) -> dict[str, Any]:
    """清空多维表 + 按 Excel 全量重建。"""
    records = parse_workbook(path)
    merged = _merge_records(records)

    table_id = _get_inventory_table_id()
    client = SafetyBitableClient(app_token=app_token, table_id=table_id)

    # 1. 清空现有记录（批量删除）
    existing = await client.list_all_records()
    deleted = await _batch_delete(client, [i.get("record_id", "") for i in existing if i.get("record_id")])

    # 2. 批量写入
    created = await _batch_create(client, [_to_bitable_fields(m) for m in merged])

    return {
        "parsed": len(records),
        "merged": len(merged),
        "deleted": deleted,
        "created": created,
        "failed": len(merged) - created,
    }
