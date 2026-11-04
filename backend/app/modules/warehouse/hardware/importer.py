"""五金库清单/编码表导入器（P2 定案口径）。

- 492 项物资清单：行1=标题、行2=表头、行3 起数据。类别/名称/规格/单位 +
  安全库存 + 5 部门月需求(monthly_demands JSON) + 采购周期；code 全留空。
  现清单月需求/安全库存/采购周期列为空 → 按 0/空 dict/NULL 落库。
- 编码表回填（通道保留，待采购部《福兴采购组织物料编码表》Excel）：
  名称+规格匹配主数据回填 code；未匹配的自动沉淀新行（managed_class 由
  参数决定，默认 stocked）。

幂等：按 (name, spec) 唯一索引 upsert——重复导入更新非空字段不重复建行。
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware.models import DEMAND_DEPARTMENTS, HardwareMaterial

logger = logging.getLogger(__name__)

# 清单列位（0 基）：行2 表头 序号/类别/物资编码/物资名称/规格型号/单位/
# 发酵/提炼一期/提炼二期/精制机修/动力机修/月需求合计/安全库存量/
# 当月25日库存量/月度采购量/采购周期
COL_CATEGORY = 1
COL_CODE = 2
COL_NAME = 3
COL_SPEC = 4
COL_UNIT = 5
COL_DEMAND_START = 6  # 5 部门需求列 6..10
COL_SAFETY = 12
COL_LEAD_TIME = 15
DATA_START_ROW = 3


def _cell_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cell_decimal(value: Any) -> Decimal | None:
    text = _cell_text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _cell_int(value: Any) -> int | None:
    dec = _cell_decimal(value)
    if dec is None:
        return None
    try:
        return int(dec)
    except (ValueError, ArithmeticError):
        return None


def parse_materials_workbook(path: str | Path) -> list[dict[str, Any]]:
    """解析物资清单 xlsx → 行 dict 列表（不落库，供预览/校验/导入）。"""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows: list[dict[str, Any]] = []
        for row in ws.iter_rows(min_row=DATA_START_ROW, values_only=True):
            name = _cell_text(row[COL_NAME]) if len(row) > COL_NAME else None
            if not name:
                continue
            demands: dict[str, Decimal] = {}
            for i, dept in enumerate(DEMAND_DEPARTMENTS):
                qty = _cell_decimal(row[COL_DEMAND_START + i]) if len(row) > COL_DEMAND_START + i else None
                if qty is not None and qty > 0:
                    demands[dept] = qty
            safety = _cell_decimal(row[COL_SAFETY]) if len(row) > COL_SAFETY else None
            lead = _cell_int(row[COL_LEAD_TIME]) if len(row) > COL_LEAD_TIME else None
            rows.append(
                {
                    # code 留空（P2：编码权威在采购部编码表，导入回填）
                    "code": _cell_text(row[COL_CODE]) if len(row) > COL_CODE else None,
                    "name": name,
                    "spec": _cell_text(row[COL_SPEC]) if len(row) > COL_SPEC else None,
                    "unit": _cell_text(row[COL_UNIT]) if len(row) > COL_UNIT else None,
                    "category": _cell_text(row[COL_CATEGORY]) if len(row) > COL_CATEGORY else None,
                    "safety_stock": safety or Decimal("0"),
                    "monthly_demands": demands,
                    "lead_time_days": lead,
                }
            )
        return rows
    finally:
        wb.close()


async def import_materials(
    db: AsyncSession, path: str | Path, *, user_id: Any = None
) -> dict[str, Any]:
    """导入物资清单：幂等 upsert（name+spec 命中则更新非空字段）。"""
    rows = parse_materials_workbook(path)
    created = updated = skipped = 0
    errors: list[str] = []
    for row in rows:
        name, spec = row["name"], row["spec"]
        if not row["unit"] or not row["category"]:
            errors.append(f"跳过 {name}：单位或类别为空")
            skipped += 1
            continue
        existing = (
            await db.execute(
                select(HardwareMaterial).where(
                    HardwareMaterial.name == name,
                    (HardwareMaterial.spec == spec)
                    if spec
                    else or_(HardwareMaterial.spec.is_(None), HardwareMaterial.spec == ""),
                    HardwareMaterial.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                HardwareMaterial(
                    code=row["code"] or None,  # 清单编码列全空=正常，编码表到位后回填
                    name=name,
                    spec=spec,
                    unit=row["unit"],
                    category=row["category"],
                    managed_class="stocked",  # 清单内 492 项=共用类（两类边界=清单本身）
                    safety_stock=row["safety_stock"],
                    monthly_demands=row["monthly_demands"] or None,
                    lead_time_days=row["lead_time_days"],
                    no_expiry=True,  # 五金件无效期（设计 §2.1）
                    created_by=user_id,
                )
            )
            created += 1
        else:
            # 幂等重导：只补空不覆盖已填（如已回填 code 不被空值冲掉）
            if row["code"] and not existing.code:
                existing.code = row["code"]
            if row["safety_stock"]:
                existing.safety_stock = row["safety_stock"]
            if row["monthly_demands"]:
                merged = dict(existing.monthly_demands or {})
                merged.update(row["monthly_demands"])
                existing.monthly_demands = merged
            if row["lead_time_days"] is not None and existing.lead_time_days is None:
                existing.lead_time_days = row["lead_time_days"]
            updated += 1
    await db.flush()
    return {
        "total_rows": len(rows),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


# ── 编码表回填（通道保留：待《福兴采购组织物料编码表》Excel 文件）──

# 编码表列位（0 基，默认按采购编码表惯例：物料编码/物料名称/规格型号/单位）
_CODE_COL = 0
_CODE_NAME_COL = 1
_CODE_SPEC_COL = 2


def parse_code_workbook(path: str | Path) -> list[dict[str, str | None]]:
    """解析采购编码表 xlsx（首行表头，数据从行2）→ [{code, name, spec}]。"""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows: list[dict[str, str | None]] = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            code = _cell_text(row[_CODE_COL]) if len(row) > _CODE_COL else None
            name = _cell_text(row[_CODE_NAME_COL]) if len(row) > _CODE_NAME_COL else None
            if not code or not name:
                continue
            spec = _cell_text(row[_CODE_SPEC_COL]) if len(row) > _CODE_SPEC_COL else None
            rows.append({"code": code, "name": name, "spec": spec})
        return rows
    finally:
        wb.close()


async def backfill_codes(
    db: AsyncSession, path: str | Path, *, user_id: Any = None
) -> dict[str, Any]:
    """编码表回填主数据：名称+规格匹配 → 回填 code；未匹配沉淀新行。

    （P2 通道：文件到位后 `python -m app.modules.warehouse.hardware.importer
    <编码表.xlsx>` 执行回填。）
    """
    rows = parse_code_workbook(path)
    matched = backfilled = new_materials = 0
    errors: list[str] = []
    for row in rows:
        spec = row["spec"]
        existing = (
            await db.execute(
                select(HardwareMaterial).where(
                    HardwareMaterial.name == row["name"],
                    (HardwareMaterial.spec == spec)
                    if spec
                    else or_(HardwareMaterial.spec.is_(None), HardwareMaterial.spec == ""),
                    HardwareMaterial.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            matched += 1
            if not existing.code:
                existing.code = row["code"]
                backfilled += 1
        else:
            # 未建档沉淀新行（默认 direct：清单外物料多为车间单独需求类）
            db.add(
                HardwareMaterial(
                    code=row["code"],
                    name=row["name"],
                    spec=spec,
                    unit="个",  # 编码表无单位列时占位，主数据维护页可改
                    category="其他",
                    managed_class="direct",
                    created_by=user_id,
                )
            )
            new_materials += 1
    await db.flush()
    return {
        "total_rows": len(rows),
        "matched": matched,
        "backfilled": backfilled,
        "new_materials": new_materials,
        "errors": errors,
    }


if __name__ == "__main__":
    # CLI：编码表回填通道（python -m app.modules.warehouse.hardware.importer <file>）
    import asyncio
    import sys

    from app.core.database import async_session_factory

    async def _main() -> None:
        if len(sys.argv) < 2:
            print("用法: python -m app.modules.warehouse.hardware.importer <编码表.xlsx>")
            sys.exit(1)
        async with async_session_factory() as session:
            stats = await backfill_codes(session, sys.argv[1])
            await session.commit()
        print(stats)

    asyncio.run(_main())
