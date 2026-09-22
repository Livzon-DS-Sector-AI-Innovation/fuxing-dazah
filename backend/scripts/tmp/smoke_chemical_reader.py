"""chemical_inventory 直读 reader 只读真机冒烟（chemical_inventory-direct Ticket 03）。

零写入。验证：全量行数与探针量级一致（462 级）、耗时、视图字段抽样。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/smoke_chemical_reader.py
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")


async def main() -> int:
    from app.modules.safety.service.chemical_inventory_direct.reader import open_reader

    reader = open_reader()
    t0 = time.perf_counter()
    views = await reader.fetch_all(strict=True)
    elapsed = time.perf_counter() - t0

    warn = sum(1 for v in views if v.risk_flag == "warn")
    print(f"行数={len(views)} 耗时={elapsed:.2f}s 预警行={warn}")
    if views:
        v = views[0]
        print(
            f"首行: id={v.id} dept={v.department} name={v.material_name!r} "
            f"unit={v.unit!r} total_t={v.total_quantity_t} flag={v.risk_flag} "
            f"updated_at={v.updated_at}"
        )
    ok = 400 <= len(views) <= 600 and elapsed < 5.0
    print("[OK]" if ok else "[!!] 量级/耗时与探针不符（探针 462 行 ~1s）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
