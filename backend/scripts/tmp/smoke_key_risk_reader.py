"""key_risk_op 直读 reader 真机冒烟（key_risk_op-direct Ticket 05，零写入）。

验证：全量行数与探针量级一致（1585 级）、首次拉取耗时、缓存命中后 <2s。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/smoke_key_risk_reader.py
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")


async def main() -> int:
    from app.modules.safety.service.key_risk_op_direct.reader import open_reader

    reader = open_reader()
    t0 = time.perf_counter()
    views = await reader.fetch_all(strict=True)
    cold = time.perf_counter() - t0

    await reader.fetch_all()  # 预热：非 strict 首调为填缓存
    warm0 = time.perf_counter()
    views2 = await reader.fetch_all()
    warm = time.perf_counter() - warm0

    approved = sum(1 for v in views if v.apply_status == "已通过")
    print(f"行数={len(views)}（已通过={approved}）"
          f" 首拉={cold:.2f}s 缓存命中={warm:.2f}s")
    if views:
        v = views[0]
        print(f"首行: id={v.id} report_no={v.report_no} dept={v.department}"
              f" status={v.apply_status} start={v.start_time}")
    ok = 1400 <= len(views) <= 1800 and warm < 2.0 and views2
    print("[OK]" if ok else "[!!] 量级/耗时与探针不符（探针 1585 行 ~4.9s 首拉）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
