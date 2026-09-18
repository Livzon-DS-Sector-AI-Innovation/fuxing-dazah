"""运维脚本：消防点检 PDF 补档（复用归档编排 service，与定时任务同一代码路径）。

用法（backend 目录下）：
    python scripts/backfill_fire_inspection_pdf.py                 # 全表增量：只为缺档记录补档
    python scripts/backfill_fire_inspection_pdf.py recXXX,recYYY   # 指定记录：仍只补空档
"""

import asyncio
import sys

sys.path.insert(0, ".")

from app.modules.safety.fire_inspection.service import generate_and_backfill


async def main() -> None:
    record_ids: list[str] | None = None
    if len(sys.argv) > 1 and sys.argv[1].strip():
        record_ids = [part.strip() for part in sys.argv[1].split(",") if part.strip()]
    result = await generate_and_backfill(record_ids)
    print(f"generated={result.generated}")
    print(f"skipped={result.skipped}")
    print(f"failed={result.failed}")


if __name__ == "__main__":
    asyncio.run(main())
