"""本地 dev 库镜像回填（key_risk_op-direct Ticket 05，cert/chemical 同口径）。

事件镜像只在生产跑，本地库为空——双路径比对前先回填。
只读 Bitable、只写本地 dev 库。注意：本脚本走既有 sync_from_bitable()，
直读闸门开着（DIRECT 开 + EVENT 关）时会被短路——本地回填请保持开关全关。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/backfill_key_risk_mirror.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> int:
    from app.core.database import async_session_factory
    from app.modules.safety.service.key_risk_operation_report import (
        KeyRiskOperationReportService,
    )

    async with async_session_factory() as db:
        result = await KeyRiskOperationReportService(db).sync_from_bitable()
    print(f"回填结果: {result}")
    if result.get("skipped") and result.get("reason") == "direct_mode":
        print("[x] 直读闸门开着会短路同步，本地回填请保持开关全关")
        return 2
    print(f"[OK] created={result.get('created')} updated={result.get('updated')}"
          f" deleted={result.get('deleted')} skipped_deleted={result.get('skipped_deleted')}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
