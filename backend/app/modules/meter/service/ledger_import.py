"""Excel 台账导入：按资产/产品编号 upsert，旧记录软删除。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter import repository as repo
from app.modules.meter.models import GasDetectorRecord, InstrumentRecord
from app.modules.meter.service.ledger_parsing import (
    GAS_DETECTOR_COLUMN_MAP,
    INSTRUMENT_COLUMN_MAP,
    _map_and_convert_rows,
    _parse_workbook_xlrd,
    _parse_workbook_xlsx,
)

logger = logging.getLogger(__name__)

async def _upsert_ledger_rows(
    db: AsyncSession,
    model: type[InstrumentRecord | GasDetectorRecord],
    key_field: str,
    rows: list[dict[str, Any]],
    *,
    preserve_keys: set[str] | None = None,
) -> tuple[int, int, int]:
    """按 key_field（asset_number / product_number）upsert 台账行。

    - key 命中旧记录 → 更新字段（保留 id，报告关联不断链）；文件中重复出现的
      同一 key，首个更新旧记录、其余按新行插入（与旧版「一行一记录」语义一致）
    - key 为新的 → 插入
    - 旧台账中文件未出现的记录（含 key 为空、历史重复 key 的记录）→ 软删除；
      preserve_keys 中的 key 即使文件未映射成功也不删除（行被必填过滤跳过时用）
    返回 (updated, inserted, deleted)。
    """
    from sqlalchemy import select as sa_select
    from sqlalchemy import update as sa_update

    key_col = getattr(model, key_field)
    existing_rows = (
        await db.execute(
            sa_select(model.id, key_col).where(model.is_deleted == False)  # noqa: E712
        )
    ).all()

    existing_map: dict[str, uuid.UUID] = {}
    stale_ids: list[uuid.UUID] = []
    for rid, key in existing_rows:
        if not key or key in existing_map:
            stale_ids.append(rid)  # key 为空或历史重复的旧记录一并移除
        else:
            existing_map[key] = rid

    seen_keys: set[str] = set()
    insert_rows: list[dict[str, Any]] = []
    updated = 0
    for row in rows:
        key = row.get(key_field)
        if key and key in existing_map and key not in seen_keys:
            stmt = sa_update(model).where(model.id == existing_map[key]).values(**row)
            await db.execute(stmt)
            updated += 1
            seen_keys.add(key)
        else:
            insert_rows.append(row)

    for i in range(0, len(insert_rows), 500):
        batch = insert_rows[i:i + 500]
        await db.execute(insert(model).values(batch))

    for key, rid in existing_map.items():
        if key not in seen_keys and not (preserve_keys and key in preserve_keys):
            stale_ids.append(rid)

    deleted = 0
    if stale_ids:
        result = await db.execute(
            sa_update(model)
            .where(model.id.in_(stale_ids), model.is_deleted == False)  # noqa: E712
            .values(is_deleted=True)
        )
        deleted = result.rowcount or 0  # type: ignore[attr-defined]

    return updated, len(insert_rows), deleted


async def import_instrument_ledger(
    db: AsyncSession, file_content: bytes, filename: str
) -> dict[str, Any]:
    """导入标准计量器具台账 Excel。

    流程：解析文件 → 按资产编号 upsert（命中旧记录则更新保留 id，
    新编号插入，文件中未出现的旧记录软删除）。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    # 1. 解析文件
    if ext in ("et", "xls"):
        sheets_data, parse_errors = _parse_workbook_xlrd(file_content)
        datemode = sheets_data[0]["datemode"] if sheets_data else 0
    elif ext == "xlsx":
        sheets_data, parse_errors = _parse_workbook_xlsx(file_content)
        datemode = 0
    else:
        raise ValueError(f"不支持的文件格式: .{ext}，请上传 .et 或 .xlsx 文件")

    if parse_errors:
        logger.warning(f"Parse errors during file import: {parse_errors}")

    # 2. 过滤：跳过探测器 sheet
    instrument_sheets = []
    detector_keywords = ["可燃", "有毒", "探测器", "气体检测"]
    for sheet in sheets_data:
        is_detector = any(kw in sheet["name"] for kw in detector_keywords)
        if not is_detector:
            instrument_sheets.append(sheet)

    if not instrument_sheets:
        raise ValueError("未找到标准计量器具数据 sheet（已跳过探测器 sheet）")

    # 3. 映射和转换（名称/资产编号/出厂编号任一为空的行跳过；
    #    被跳过的行若带资产编号，其旧记录不参与「文件未出现即软删除」清理）
    mapped_rows, map_warnings, skipped_keys = _map_and_convert_rows(
        instrument_sheets, INSTRUMENT_COLUMN_MAP, datemode, use_sheet_name_as_dept=True,
        required_fields=("instrument_name", "asset_number", "serial_number"),
    )

    if not mapped_rows:
        raise ValueError("文件中未找到有效的计量器具数据")

    # 按 Excel 解析顺序赋予全局 sort_order
    for idx, row in enumerate(mapped_rows):
        row["sort_order"] = idx

    # 4. upsert：资产编号命中旧记录 → 更新字段（保留 id，报告关联不断链）；
    #    新编号 → 插入；文件未出现的旧记录 → 软删除
    # 确定所有去重后行的字段并集，填充缺失字段为 None
    all_keys: set[str] = set()
    for row in mapped_rows:
        all_keys.update(row.keys())
    # anomaly_flags 有 server_default，不能设 None；统一设 {}
    all_keys.discard("anomaly_flags")
    for row in mapped_rows:
        for key in all_keys:
            if key not in row:
                row[key] = None
        # anomaly_flags 始终为空 dict，让 server_default 也能正常工作
        if "anomaly_flags" not in row or row.get("anomaly_flags") is None:
            row["anomaly_flags"] = {}

    updated_count, inserted_count, deleted_count = await _upsert_ledger_rows(
        db, InstrumentRecord, "asset_number", mapped_rows, preserve_keys=skipped_keys
    )

    # 6. 同步部门到 departments 表
    dept_names: set[str] = {r["department"] for r in mapped_rows if r.get("department")}
    synced = await repo.sync_departments(db, "instrument", dept_names)
    logger.info(f"Sync departments (instrument): {synced} new from {len(dept_names)} unique")

    # 7. 构建 sheet 详情
    sheet_details: list[dict[str, Any]] = []
    for sheet in instrument_sheets:
        # 标准器具用 sheet 名称作为部门名，与写入 DB 数据保持一致
        dept = sheet["name"].strip()
        # 统计该 sheet 的去重后行数
        sheet_rows = sum(
            1 for r in mapped_rows
            if r.get("sheet_name") == sheet["name"]
        )
        if sheet_rows > 0:
            sheet_details.append({
                "sheet_name": sheet["name"],
                "department": dept,
                "rows": sheet_rows,
            })

    await db.commit()

    return {
        "deleted_count": deleted_count,
        "imported_count": inserted_count,
        "updated_count": updated_count,
        "sheet_count": len(sheet_details),
        "sheet_details": sheet_details,
        "warnings": list(map_warnings)[:200],
    }


async def import_gas_detector_ledger(
    db: AsyncSession, file_content: bytes, filename: str
) -> dict[str, Any]:
    """导入有毒有害探测器台账 Excel。

    只处理 Sheet 0（探测器 sheet）。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    # 1. 解析文件
    if ext in ("et", "xls"):
        sheets_data, parse_errors = _parse_workbook_xlrd(file_content)
        datemode = sheets_data[0]["datemode"] if sheets_data else 0
    elif ext == "xlsx":
        sheets_data, parse_errors = _parse_workbook_xlsx(file_content)
        datemode = 0
    else:
        raise ValueError(f"不支持的文件格式: .{ext}，请上传 .et 或 .xlsx 文件")

    if parse_errors:
        logger.warning(f"Parse errors during detector import: {parse_errors}")

    # 2. 找到探测器 sheet
    detector_keywords = ["可燃", "有毒", "探测器", "气体检测"]
    detector_sheet = None
    for sheet in sheets_data:
        if any(kw in sheet["name"] for kw in detector_keywords):
            detector_sheet = sheet
            break

    if detector_sheet is None:
        # 如果没有匹配的 sheet 名，尝试使用第一个 sheet 作为探测器 sheet
        if sheets_data:
            detector_sheet = sheets_data[0]
        else:
            raise ValueError("文件中未找到任何数据 sheet")

    # 3. 映射和转换
    mapped_rows, map_warnings, _skipped_keys = _map_and_convert_rows(
        [detector_sheet], GAS_DETECTOR_COLUMN_MAP, datemode
    )

    if not mapped_rows:
        raise ValueError("文件中未找到有效的探测器数据")

    # 按 Excel 解析顺序赋予全局 sort_order
    for idx, row in enumerate(mapped_rows):
        row["sort_order"] = idx

    # 4. upsert：产品编号命中旧记录 → 更新字段（保留 id，报告关联不断链）；
    #    新编号 → 插入；文件未出现的旧记录 → 软删除
    # 确定所有去重后行的字段并集，填充缺失字段为 None
    all_keys_gd: set[str] = set()
    for row in mapped_rows:
        all_keys_gd.update(row.keys())
    all_keys_gd.discard("anomaly_flags")
    for row in mapped_rows:
        for key in all_keys_gd:
            if key not in row:
                row[key] = None
        if "anomaly_flags" not in row or row.get("anomaly_flags") is None:
            row["anomaly_flags"] = {}

    updated_count, inserted_count, deleted_count = await _upsert_ledger_rows(
        db, GasDetectorRecord, "product_number", mapped_rows
    )

    # 6. 同步部门到 departments 表
    dept_names: set[str] = {r["department"] for r in mapped_rows if r.get("department")}
    synced = await repo.sync_departments(db, "gas_detector", dept_names)
    logger.info(f"Sync departments (gas_detector): {synced} new from {len(dept_names)} unique")

    # 7. sheet 详情
    sheet_details: list[dict[str, Any]] = [{
        "sheet_name": detector_sheet["name"],
        "department": detector_sheet.get("dept"),
        "rows": len(mapped_rows),
    }]

    await db.commit()

    return {
        "deleted_count": deleted_count,
        "imported_count": inserted_count,
        "updated_count": updated_count,
        "sheet_count": 1,
        "sheet_details": sheet_details,
        "warnings": list(map_warnings)[:200],
    }


# ═══════════════════════════════════════════
# 全局设置
# ═══════════════════════════════════════════
