"""refresh_hardware_catalog.py — 五金库物资目录翻新（按《编码库位》清单）。

用途：以业务给的《五金库物资清单编码库位.xlsx》为权威刷新 hardware_materials：
- 匹配键：名称+规格（与 DB 唯一索引 uq_hardware_materials_name_spec、现有
  importer 同口径；规格空值归一为 NULL 语义）；
- Excel 有 / 平台无 → 新建（stocked + no_expiry，含编码/位号）；
- 两边都有 → 编码/位号**非空覆盖**（空值不动，防误清空）；类别/单位/月需求/
  安全库存/采购周期维持现有导入器的"只补空"口径；
- 平台有（在册 stocked 且启用）/ Excel 无 → 停用（active=false，软；批次/
  单据历史不动）；
- 按表头名取列（行2为表头；行1是大类合并标题），不依赖固定列位。

用法（backend 下）：
    .venv/bin/python -m scripts.refresh_hardware_catalog <清单.xlsx>            # 预演
    .venv/bin/python -m scripts.refresh_hardware_catalog <清单.xlsx> --apply    # 真跑

本地与生产各跑一遍（生产先部署含本列的版本并 upgrade）。
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEPT_COLUMNS = {"发酵", "提炼一期", "提炼二期", "精制机修", "动力机修"}
# 沉淀类等非 stocked 物资不在清单职责内，永不因翻新停用
DEACTIVATE_SCOPE = "stocked"


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _dec(v: Any) -> Decimal | None:
    t = _s(v)
    if not t:
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def load_rows(path: Path) -> list[dict[str, Any]]:
    import openpyxl

    # 非 read_only 模式：位号列用纵向合并单元格（一个位号覆盖多行物资），
    # 只有合并区首行有值、其余行读空，必须读 merged_cells 把值展开到覆盖行
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    # 表头定位：前 3 行内找含"物资名称"的行
    header_idx = next(
        i for i, r in enumerate(rows[:3]) if any("物资名称" in _s(c) for c in r)
    )
    header = [_s(c) for c in rows[header_idx]]
    col = {name: j for j, name in enumerate(header) if name}
    for required in ("物资名称", "位号"):
        if required not in col:
            raise SystemExit(f"✗ 表头缺少「{required}」列；实际表头: {header}")

    # 位号合并区 → 行号（1 基）到位号的展开映射
    loc_col_1based = col["位号"] + 1
    loc_by_row: dict[int, str] = {}
    for rng in ws.merged_cells.ranges:
        if rng.min_col == loc_col_1based and rng.max_col == loc_col_1based:
            value = _s(ws.cell(row=rng.min_row, column=rng.min_col).value)
            if value:
                for row_no in range(rng.min_row, rng.max_row + 1):
                    loc_by_row[row_no] = value

    out: list[dict[str, Any]] = []
    for row_idx, r in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        def cell(name: str) -> Any:
            j = col.get(name)
            return r[j] if j is not None and j < len(r) else None

        name = _s(cell("物资名称"))
        if not name:
            continue
        demands = {
            dept: _dec(cell(dept)) for dept in DEPT_COLUMNS if _dec(cell(dept)) is not None
        }
        out.append({
            "name": name,
            "spec": _s(cell("规格型号")) or None,
            "unit": _s(cell("单位")) or None,
            "category": _s(cell("类别")) or None,
            "code": _s(cell("物资编码")) or None,
            "location_no": _s(cell("位号")) or loc_by_row.get(row_idx) or None,
            "demands": demands or None,
            "safety": _dec(cell("安全库存量")),
            "lead_days": int(_dec(cell("采购周期")) or 0) or None,
        })
    return out


async def run(path: Path, *, apply: bool) -> None:
    from app.core.database import async_session_factory
    from app.modules.warehouse.hardware.models import HardwareMaterial

    sheet = load_rows(path)
    print(f"清单: {path.name} | 有效行 {len(sheet)}")
    by_key: dict[tuple[str, str | None], dict[str, Any]] = {}
    conflicts: list[str] = []
    for row in sheet:
        key = (row["name"], row["spec"])
        if key in by_key:
            conflicts.append(f"{row['name']} / {row['spec'] or '-'}")
        else:
            by_key[key] = row
    if conflicts:
        raise SystemExit(f"✗ 清单内名称+规格重复 {len(conflicts)} 行：{conflicts[:5]}")

    created: list[str] = []
    updated: list[str] = []
    code_clashes: list[str] = []
    async with async_session_factory() as db:
        materials = (
            await db.execute(
                select(HardwareMaterial).where(HardwareMaterial.is_deleted.is_(False))
            )
        ).scalars().all()
        existing = {(m.name, m.spec or None): m for m in materials}

        for key, row in by_key.items():
            m = existing.get(key)
            if m is None:
                m = HardwareMaterial(
                    name=row["name"], spec=row["spec"], unit=row["unit"] or "个",
                    category=row["category"] or "其他", code=row["code"],
                    location_no=row["location_no"], managed_class="stocked",
                    no_expiry=True, safety_stock=row["safety"] or Decimal("0"),
                    monthly_demands=row["demands"], lead_time_days=row["lead_days"],
                )
                db.add(m)
                created.append(row["name"])
                continue
            touched = False
            # 覆盖语义：编码/位号非空才写（空值不动，防误清空）
            for field in ("code", "location_no"):
                if row[field] and getattr(m, field) != row[field]:
                    setattr(m, field, row[field])
                    touched = True
            # 补空语义：类别/单位/月需求/安全库存/采购周期（与现有导入器口径一致）
            for field in ("category", "unit"):
                if row[field] and not getattr(m, field):
                    setattr(m, field, row[field])
                    touched = True
            if row["demands"] and not m.monthly_demands:
                m.monthly_demands = row["demands"]
                touched = True
            if row["safety"] is not None and not m.safety_stock:
                m.safety_stock = row["safety"]
                touched = True
            if row["lead_days"] and not m.lead_time_days:
                m.lead_time_days = row["lead_days"]
                touched = True
            if touched:
                updated.append(row["name"])
                if not m.active:
                    m.active = True  # 清单内物资确保启用
        if apply:
            await db.flush()
            # 编码唯一（软删外）终检：同码不同物
            by_code: dict[str, str] = {}
            for m in materials:
                if m.code:
                    if m.code in by_code:
                        code_clashes.append(f"{m.code}: {by_code[m.code]} / {m.name}")
                    by_code[m.code] = m.name

        # 停用：在册 stocked 且启用、不在清单
        deactivated: list[str] = []
        for m in materials:
            if (
                m.managed_class == DEACTIVATE_SCOPE
                and m.active
                and (m.name, m.spec or None) not in by_key
            ):
                m.active = False
                deactivated.append(m.name)

        if not apply:
            print(f"[预演] 新建 {len(created)} / 更新 {len(updated)} / 停用 {len(deactivated)}")
            for label, items in (("新建", created[:10]), ("更新", updated[:10]), ("停用", deactivated[:10])):
                if items:
                    print(f"  {label}示例:", "、".join(items), "..." if len(items) == 10 else "")
            print("确认无误后加 --apply 真跑")
            await db.rollback()
            return

        if code_clashes:
            raise SystemExit(f"✗ 编码冲突，已回滚：{code_clashes[:5]}")
        await db.commit()
        print(f"[已应用] 新建 {len(created)} / 更新 {len(updated)} / 停用 {len(deactivated)}")
        print(f"  位号写入 {sum(1 for r in by_key.values() if r['location_no'])} 行（清单内非空）")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    asyncio.run(run(Path(sys.argv[1]), apply="--apply" in sys.argv[2:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
