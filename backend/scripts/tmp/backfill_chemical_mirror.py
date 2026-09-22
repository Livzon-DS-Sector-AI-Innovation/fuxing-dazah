"""本地 dev 库镜像回填（chemical_inventory-direct Ticket 08，cert backfill 同口径）。

事件镜像只在生产跑，本地库为空——双路径比对前先回填。
只读 Bitable、只写本地 dev 库。注意：本脚本走既有
sync_inventory_records_from_bitable()，直读闸门开着（DIRECT 开 + EVENT_SYNC 关）时
会被短路——本地默认全关即放行。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/backfill_chemical_mirror.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> int:
    from app.modules.safety.feishu.chemical_inventory_bitable_handler import (
        sync_inventory_records_from_bitable,
    )

    result = await sync_inventory_records_from_bitable()
    print(f"回填结果: {result}")
    if result.get("skipped") and result.get("reason") == "direct_mode":
        print("[x] 直读闸门开着（DIRECT 开/EVENT 关）会短路同步，本地回填请保持开关全关")
        return 2
    if result.get("skipped"):
        print("[x] Bitable 连接未配置或已停用")
        return 2
    print(f"[OK] created={result.get('created')} updated={result.get('updated')}"
          f" total={result.get('total')}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
