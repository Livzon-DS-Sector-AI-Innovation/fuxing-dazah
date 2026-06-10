"""
从 assets/设备清单.xlsx 导入设备数据到 equipment.equipments 表。
已存在的设备（按 equipment_no 判断）自动跳过。

用法：在 dazah-backend 目录下执行
    uv run python -X utf8 scripts/tmp/import_equipment.py
"""

import asyncio
import sys
import uuid
from datetime import date
from pathlib import Path

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import openpyxl
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.equipment.models.equipment import (
    Equipment,
    EquipmentCategory,
    EquipmentCategoryLink,
    Location,
)

EXCEL_PATH = PROJECT_ROOT / "assets" / "设备清单.xlsx"
DEFAULT_CATEGORY_NAME = "动力部设备"

# ── Excel 列映射 ──
COL_SEQ = 0        # 序号
COL_ASSET_NO = 1   # 固资编号
COL_EQ_NO = 2      # 设备编号
COL_NAME = 3       # 设备名称
COL_SPEC = 4       # 规格型号
COL_MFR = 5        # 制造单位
COL_FACTORY_NO = 6 # 出厂编号
COL_IN_DATE = 7    # 入厂日期
COL_VALUE = 8      # 设备原值
COL_LOCATION = 9   # 安装地点
COL_POWER = 10     # 功率/电流
COL_STATUS = 11    # 未报废


def parse_date(value) -> date | None:
    """解析 Excel 中的日期：支持 2025.11 / 2005.10.25 / datetime 等格式"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    s = str(value).strip()
    if not s or s in ("/", "-", "暂未编号", "待转固"):
        return None
    for fmt in ("%Y.%m.%d", "%Y.%m", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_float(value) -> float | None:
    """解析数字"""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


async def import_equipment():
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active

    # 解析数据行（跳过标题行和表头行）
    rows = list(ws.iter_rows(min_row=3, values_only=True))

    async with async_session_factory() as db:
        # ── 确保默认分类存在 ──
        cat_result = await db.execute(
            select(EquipmentCategory).where(
                EquipmentCategory.name == DEFAULT_CATEGORY_NAME,
                EquipmentCategory.is_deleted == False,  # noqa: E712
            )
        )
        default_category = cat_result.scalar_one_or_none()
        if not default_category:
            default_category = EquipmentCategory(
                name=DEFAULT_CATEGORY_NAME,
                code="power_equipment",
                description="从设备清单导入",
            )
            db.add(default_category)
            await db.flush()
            print(f"[+] 创建分类: {DEFAULT_CATEGORY_NAME}")
        category_id = default_category.id

        # ── 获取已有设备编号 ──
        existing_eqs = await db.execute(
            select(Equipment.equipment_no).where(Equipment.is_deleted == False)  # noqa: E712
        )
        existing_nos: set[str] = {r[0] for r in existing_eqs.all()}

        # ── 缓存已创建的位置 ──
        loc_cache: dict[str, uuid.UUID] = {}
        locs_result = await db.execute(
            select(Location.name, Location.id).where(Location.is_deleted == False)  # noqa: E712
        )
        for loc_name, loc_id in locs_result.all():
            loc_cache[loc_name] = loc_id

        imported = 0
        skipped = 0
        errors = 0

        for row in rows:
            eq_no = str(row[COL_EQ_NO]).strip() if row[COL_EQ_NO] else None
            name = str(row[COL_NAME]).strip() if row[COL_NAME] else None

            if not eq_no or not name:
                continue

            # 跳过重复
            if eq_no in existing_nos:
                skipped += 1
                continue

            # 位置：自动创建不存在的，空值归入默认
            loc_name = str(row[COL_LOCATION]).strip().replace("\n", "") if row[COL_LOCATION] else None
            if not loc_name:
                loc_name = "未指定位置"
            location_id = None
            if loc_name:
                if loc_name in loc_cache:
                    location_id = loc_cache[loc_name]
                else:
                    new_loc = Location(name=loc_name, code=f"imp_{loc_name[:20]}")
                    db.add(new_loc)
                    await db.flush()
                    loc_cache[loc_name] = new_loc.id
                    location_id = new_loc.id
                    print(f"[+] 创建位置: {loc_name}")

            # 技术参数
            tech_params = {}
            factory_no = str(row[COL_FACTORY_NO]).strip() if row[COL_FACTORY_NO] and str(row[COL_FACTORY_NO]).strip() != "/" else None
            power_info = str(row[COL_POWER]).strip().replace("\n", " ") if row[COL_POWER] else None
            asset_no = str(row[COL_ASSET_NO]).strip() if row[COL_ASSET_NO] else None
            if factory_no:
                tech_params["出厂编号"] = factory_no
            if power_info and power_info != "/":
                tech_params["功率/电流"] = power_info
            if asset_no and asset_no != "暂未编号":
                tech_params["固资编号"] = asset_no
            if not tech_params:
                tech_params = {}

            try:
                equipment = Equipment(
                    equipment_no=eq_no,
                    name=name,
                    model=str(row[COL_SPEC]).strip().replace("\n", " ") if row[COL_SPEC] else None,
                    manufacturer=str(row[COL_MFR]).strip() if row[COL_MFR] else None,
                    production_date=parse_date(row[COL_IN_DATE]),
                    asset_value=parse_float(row[COL_VALUE]),
                    location_id=location_id,
                    technical_params=tech_params if tech_params else None,
                    status="在用",
                    importance="低",
                )
                db.add(equipment)
                await db.flush()

                # 关联分类
                db.add(EquipmentCategoryLink(
                    equipment_id=equipment.id,
                    category_id=category_id,
                ))
                await db.flush()

                # 逐条提交，单条失败不影响其他
                await db.commit()
                existing_nos.add(eq_no)
                imported += 1

            except Exception as e:
                errors += 1
                await db.rollback()
                print(f"[!] 导入失败 {eq_no} {name}: {e}")

    print()
    print(f"=== 导入完成 ===")
    print(f"总行数: {len(rows)}")
    print(f"导入: {imported}")
    print(f"跳过（已存在）: {skipped}")
    print(f"失败: {errors}")


if __name__ == "__main__":
    asyncio.run(import_equipment())
