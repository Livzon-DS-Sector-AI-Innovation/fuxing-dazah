# ruff: noqa: E402, E501
"""
将 Excel 设备台账导入到 equipment.equipments 表。

规则：
- 设备编号：以 xlsx 第一列为准；为空时自动生成（EQ-IMP-日期-序号）并警告
- 设备分类：填名称，按 (名称, 部门) 匹配；不存在则自动创建，编号暂设为临时值
- 设备位置：同上
- 归属部门：填名称，按名称匹配 identity.departments；找不到则报错
- 负责人：填姓名，按姓名匹配 identity.users；找不到则留空并警告
- 设备状态 / 重要性：不在允许值范围内时使用默认值（在用 / 低），不阻断导入

用法：在 dazah-backend 目录下执行
    uv run python -X utf8 scripts/import_data/import_equipment.py

    指定文件：
    uv run python -X utf8 scripts/import_data/import_equipment.py "设备台账.xlsx"
"""

import asyncio
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

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
from app.platform.identity.models import Department, User

# ── 列映射（0-based），对应 xlsx 模板：设备编号 | 设备名称 | 设备分类 | … | 负责人 ──
COL_EQUIPMENT_NO = 0
COL_NAME = 1
COL_CATEGORY_NAME = 2
COL_LOCATION_NAME = 3
COL_DEPARTMENT_NAME = 4
COL_STATUS = 5
COL_MODEL = 6
COL_SPECIFICATION = 7
COL_MANUFACTURER = 8
COL_SUPPLIER = 9
COL_PRODUCTION_DATE = 10
COL_COMMISSIONING_DATE = 11
COL_DESCRIPTION = 12
COL_IMPORTANCE = 13
COL_WARRANTY_EXPIRE = 14
COL_ASSET_VALUE = 15
COL_DEPRECIATION_YEARS = 16
COL_RESPONSIBLE_PERSON = 17

VALID_STATUSES = {"在用", "备用", "维修中", "停用", "报废"}
VALID_IMPORTANCE = {"高", "中", "低"}


def _cell_str(row, col: int) -> str | None:
    val = row[col] if col < len(row) else None
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _col_val(row, col: int):
    return row[col] if col < len(row) else None


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _tmp_code(prefix: str) -> str:
    """生成临时编号：IMP_CAT_xxxxxxxx"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def import_equipment(excel_path: str):
    wb = openpyxl.load_workbook(excel_path)
    ws = wb["设备台账"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    report = {"imported": 0, "skipped": 0, "errors": 0}
    error_lines: list[str] = []
    warnings: list[str] = []
    today_str = datetime.now().strftime("%Y%m%d")

    async with async_session_factory() as db:
        # ── 预加载 ————————————————
        # 已有设备编号
        existing_nos_result = await db.execute(
            select(Equipment.equipment_no).where(
                Equipment.is_deleted == False,  # noqa: E712
            )
        )
        existing_nos: set[str] = {r[0] for r in existing_nos_result.all()}

        # 部门名称 → (id, name)
        dept_result = await db.execute(
            select(Department.id, Department.name).where(
                Department.is_deleted == False,  # noqa: E712
                Department.status_is_deleted.isnot(True),
            )
        )
        dept_map: dict[str, uuid.UUID] = {name: did for did, name in dept_result.all()}

        # 用户姓名 → id
        user_result = await db.execute(
            select(User.id, User.name).where(
                User.is_deleted == False,  # noqa: E712
            )
        )
        user_map: dict[str, uuid.UUID] = {name: uid for uid, name in user_result.all()}

        # 已有分类 (name, department_id) → id
        cat_result = await db.execute(
            select(EquipmentCategory.name, EquipmentCategory.department_id,
                   EquipmentCategory.id).where(
                EquipmentCategory.is_deleted == False,  # noqa: E712
            )
        )
        cat_cache: dict[tuple[str, str | None], uuid.UUID] = {}
        for cat_name, cat_dept, cat_id in cat_result.all():
            key = (cat_name, str(cat_dept) if cat_dept else "__none__")
            cat_cache[key] = cat_id

        # 已有位置 (name, department_id) → id
        loc_result = await db.execute(
            select(Location.name, Location.department_id, Location.id).where(
                Location.is_deleted == False,  # noqa: E712
            )
        )
        loc_cache: dict[tuple[str, str | None], uuid.UUID] = {}
        for loc_name, loc_dept, loc_id in loc_result.all():
            key = (loc_name, str(loc_dept) if loc_dept else "__none__")
            loc_cache[key] = loc_id

        # ── 序号计数器 ──
        seq = 1

        for row_num, row in enumerate(rows, start=2):
            try:
                name = _cell_str(row, COL_NAME)
                cat_name = _cell_str(row, COL_CATEGORY_NAME)
                loc_name = _cell_str(row, COL_LOCATION_NAME)
                dept_name = _cell_str(row, COL_DEPARTMENT_NAME)

                # 空行跳过
                if not name and not cat_name and not loc_name and not dept_name:
                    continue

                # 必填校验
                missing = []
                if not name:
                    missing.append("设备名称")
                if not cat_name:
                    missing.append("设备分类")
                if not loc_name:
                    missing.append("设备位置")
                if not dept_name:
                    missing.append("归属部门")
                if missing:
                    raise ValueError(f"缺少必填项: {', '.join(missing)}")

                assert name and cat_name and loc_name and dept_name

                # 解析归属部门
                department_id = dept_map.get(dept_name)
                if not department_id:
                    available = "、".join(sorted(dept_map.keys())[:10])
                    hint = f"（系统已有: {available}...）" if available else ""
                    raise ValueError(f"部门 '{dept_name}' 在系统中不存在{hint}")

                # 解析/创建分类
                cat_key = (cat_name, str(department_id))
                category_id = cat_cache.get(cat_key)
                if not category_id:
                    new_cat = EquipmentCategory(
                        name=cat_name,
                        code=_tmp_code("IMP_CAT"),
                        department_id=department_id,
                    )
                    db.add(new_cat)
                    await db.flush()
                    category_id = new_cat.id
                    cat_cache[cat_key] = category_id
                    warnings.append(
                        f"第{row_num}行: 自动创建分类「{cat_name}」"
                        f"（编号 {new_cat.code}），请后续补填正式编号"
                    )

                # 解析/创建位置
                loc_key = (loc_name, str(department_id))
                location_id = loc_cache.get(loc_key)
                if not location_id:
                    new_loc = Location(
                        name=loc_name,
                        code=_tmp_code("IMP_LOC"),
                        department_id=department_id,
                    )
                    db.add(new_loc)
                    await db.flush()
                    location_id = new_loc.id
                    loc_cache[loc_key] = location_id
                    warnings.append(
                        f"第{row_num}行: 自动创建位置「{loc_name}」"
                        f"（编号 {new_loc.code}），请后续补填正式编号"
                    )

                # 解析负责人（选填）
                person_name = _cell_str(row, COL_RESPONSIBLE_PERSON)
                responsible_person_id = None
                if person_name:
                    responsible_person_id = user_map.get(person_name)
                    if not responsible_person_id:
                        warnings.append(
                            f"第{row_num}行: 负责人「{person_name}」在系统中未找到，已留空"
                        )

                # 校验状态，不合规则用默认值
                status = _cell_str(row, COL_STATUS) or "在用"
                if status not in VALID_STATUSES:
                    warnings.append(
                        f"第{row_num}行: 设备状态「{status}」不在允许值范围内"
                        f"（{'/'.join(sorted(VALID_STATUSES))}），已默认设为「在用」"
                    )
                    status = "在用"

                # 校验重要性，不合规则用默认值
                importance = _cell_str(row, COL_IMPORTANCE) or "低"
                if importance not in VALID_IMPORTANCE:
                    warnings.append(
                        f"第{row_num}行: 重要性「{importance}」不在允许值范围内"
                        f"（{'/'.join(sorted(VALID_IMPORTANCE))}），已默认设为「低」"
                    )
                    importance = "低"

                # 设备编号：以 xlsx 为准；缺失时自动生成并警告
                eq_no = _cell_str(row, COL_EQUIPMENT_NO)
                if not eq_no:
                    eq_no = f"EQ-IMP-{today_str}-{seq:04d}"
                    seq += 1
                    while eq_no in existing_nos:
                        eq_no = f"EQ-IMP-{today_str}-{seq:04d}"
                        seq += 1
                    warnings.append(
                        f"第{row_num}行: 设备编号为空，已自动生成「{eq_no}」"
                    )
                else:
                    # 检查编号是否已存在
                    if eq_no in existing_nos:
                        raise ValueError(
                            f"设备编号「{eq_no}」已存在，请检查是否重复导入"
                        )

                equipment = Equipment(
                    equipment_no=eq_no,
                    name=name,
                    location_id=location_id,
                    status=status,
                    model=_cell_str(row, COL_MODEL),
                    specification=_cell_str(row, COL_SPECIFICATION),
                    manufacturer=_cell_str(row, COL_MANUFACTURER),
                    supplier=_cell_str(row, COL_SUPPLIER),
                    production_date=parse_date(_col_val(row, COL_PRODUCTION_DATE)),
                    commissioning_date=parse_date(_col_val(row, COL_COMMISSIONING_DATE)),
                    description=_cell_str(row, COL_DESCRIPTION),
                    importance=importance,
                    warranty_expire_date=parse_date(_col_val(row, COL_WARRANTY_EXPIRE)),
                    asset_value=parse_float(_col_val(row, COL_ASSET_VALUE)),
                    depreciation_years=parse_int(_col_val(row, COL_DEPRECIATION_YEARS)),
                    department_id=department_id,
                    responsible_person_id=responsible_person_id,
                )
                db.add(equipment)
                await db.flush()

                # 关联分类
                db.add(EquipmentCategoryLink(
                    equipment_id=equipment.id,
                    category_id=category_id,
                ))
                await db.flush()

                await db.commit()
                existing_nos.add(eq_no)
                report["imported"] += 1

            except Exception as e:
                report["errors"] += 1
                await db.rollback()
                err_msg = f"第{row_num}行: {e}"
                error_lines.append(err_msg)
                print(f"[!] {err_msg}")

    # ── 打印报告 ──
    if warnings:
        print()
        print("--- 警告 ---")
        for w in warnings:
            print(f"  [!] {w}")

    print()
    print("=== 导入完成 ===")
    print(f"总行数（数据行）: {len(rows)}")
    print(f"导入成功: {report['imported']}")
    print(f"跳过: {report['skipped']}")
    print(f"失败: {report['errors']}")
    if error_lines:
        print()
        print("--- 失败明细 ---")
        for line in error_lines:
            print(f"  {line}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        # ponytail: 默认扫描 assets/equipment/ 下第一个 xlsx，兜底回模板
        equipment_dir = PROJECT_ROOT / "assets" / "equipment"
        xlsx_files = sorted(equipment_dir.glob("*.xlsx")) if equipment_dir.exists() else []
        # 排除临时文件（~$ 开头）
        xlsx_files = [f for f in xlsx_files if not f.name.startswith("~$")]
        if xlsx_files:
            file_path = str(xlsx_files[0])
        else:
            file_path = str(PROJECT_ROOT / "assets" / "设备台账导入模板.xlsx")

    if not Path(file_path).exists():
        print(f"[!] 文件不存在: {file_path}")
        sys.exit(1)

    asyncio.run(import_equipment(file_path))
