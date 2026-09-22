"""cert 直读 reader 只读真机冒烟（cert-direct Ticket 02）。

用法（backend 目录下）：.venv/Scripts/python.exe scripts/tmp/smoke_cert_reader.py
预期：3 kind 全量行数与探针量级一致（约 559 行）。
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from app.modules.safety.service.cert_direct.reader import open_reader  # noqa: E402


async def main() -> int:
    reader = open_reader()
    t0 = time.perf_counter()
    views = await reader.get_all_active(strict=True)
    elapsed = time.perf_counter() - t0
    by_cat = Counter(v.cert_category for v in views)
    print(f"total={len(views)} by_category={dict(by_cat)} elapsed={elapsed:.2f}s")
    named = sum(1 for v in views if v.person_name)
    print(f"named={named} first={views[0].id},{views[0].person_name}"
          f" last={views[-1].id},{views[-1].person_name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
