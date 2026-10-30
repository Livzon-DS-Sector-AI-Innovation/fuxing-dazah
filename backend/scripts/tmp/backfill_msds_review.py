"""MSDS 存量台账追平：全量 force 重建标准 PDF（修正「外观与性状」模板标签）
+ 补跑错别字 AI 校对（2026-10-30 机制上线一次性回填）。

用法：cd backend && PYTHONPATH=. uv run python scripts/tmp/backfill_msds_review.py [--limit N]
"""

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv(".env.development")

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402
from app.modules.safety.service.msds_review import sync_pdf_revision  # noqa: E402


async def main() -> None:
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    conn = store.get_connection("msds", "registry")
    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
    records = await client.list_all_records()
    print(f"台账共 {len(records)} 条")

    stats: dict[str, int] = {}
    done = 0
    for item in records:
        rid = item.get("record_id") or item.get("id") or ""
        if not rid:
            continue
        try:
            result = await sync_pdf_revision(rid, force=True)
        except Exception as e:
            result = {"status": f"exception:{type(e).__name__}"}
        status = str(result.get("status"))
        stats[status] = stats.get(status, 0) + 1
        done += 1
        if done % 10 == 0 or status not in ("regenerated",):
            print(f"[{done}/{len(records)}] {rid} → {status}")
        if limit and done >= limit:
            break

    print("汇总:", stats)


if __name__ == "__main__":
    asyncio.run(main())
