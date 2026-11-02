"""MSDS 台账「标签要素」批量回填（2026-11-02）。

对每条记录：列为空时 GHS 规则推导 → 只写「标签要素」列。
写入触发 record_edited → 修订同步机制自动重生成标准 PDF（一并带上：
分子式上下标规范化 + 黑体居中表头 + 标签要素渲染）。

用法：cd backend && PYTHONPATH=. uv run python scripts/tmp/fill_msds_label_elements.py
"""

import asyncio

from dotenv import load_dotenv

load_dotenv(".env.development")

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402
from app.modules.safety.service.msds_review import (  # noqa: E402
    derive_label_elements,
    entry_from_bitable_fields,
)


async def main() -> None:
    conn = store.get_connection("msds", "registry")
    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
    records = await client.list_all_records()
    print(f"台账共 {len(records)} 条")

    filled = skipped_existing = no_derive = failed = 0
    for i, item in enumerate(records):
        rid = item.get("record_id") or item.get("id") or ""
        if not rid:
            continue
        try:
            fields = await client.get_record(record_id=rid)
            if fields.get("标签要素"):
                skipped_existing += 1
                continue
            entry = entry_from_bitable_fields(fields)
            derived = derive_label_elements(entry)
            if not derived:
                no_derive += 1
                continue
            ok = await client.update_record(record_id=rid, fields={"标签要素": derived})
            if ok:
                filled += 1
            else:
                failed += 1
        except Exception:
            failed += 1
            print(f"  [{i}] {rid} 异常")
        if (i + 1) % 10 == 0:
            print(f"[{i + 1}/{len(records)}] 填充={filled} 已有={skipped_existing} 无推导={no_derive} 失败={failed}")

    print(f"汇总: 填充={filled} 已有={skipped_existing} 无推导={no_derive} 失败={failed}")


if __name__ == "__main__":
    asyncio.run(main())
