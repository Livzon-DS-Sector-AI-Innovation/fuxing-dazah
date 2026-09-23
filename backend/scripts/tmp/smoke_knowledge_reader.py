"""knowledge 直读取器真机只读冒烟（knowledge-direct Ticket 05）。

只读，零写入。验证：两表连接解析、双表并发全量拉取、视图映射（枚举/日期/
article_no 降级）、排序与窗口查询口径。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/smoke_knowledge_reader.py
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")


async def main() -> int:
    from app.modules.safety.service.knowledge_direct.query import latest_regulations
    from app.modules.safety.service.knowledge_direct.reader import open_reader

    t0 = time.perf_counter()
    views = await open_reader().fetch_all(strict=True)
    elapsed = time.perf_counter() - t0
    by_kind = {"collection": 0, "collection_env": 0}
    for v in views:
        by_kind[v.source_kind] = by_kind.get(v.source_kind, 0) + 1
    print(f"全量 {len(views)} 行（安全 {by_kind['collection']}"
          f" / 环保 {by_kind['collection_env']}）耗时 {elapsed:.2f}s")

    with_input = sum(1 for v in views if v.input_date is not None)
    with_no = sum(1 for v in views if v.article_no)
    print(f"入库日期覆盖 {with_input}/{len(views)}"
          f" article_no 非空 {with_no}（建列回填前预期 0）")

    got = latest_regulations(views, limit=5, days=365_000)
    print("最近 5 条（input_date desc）：")
    for i in got["items"]:
        print(f"  {i['id']}  {i['title']}  [{i['category']}]"
              f"  影响={i['impact_level']}  编号={i['article_no']}")

    hot = latest_regulations(views, limit=5, days=365_000, impact_level="高")
    print(f"影响等级=高：{hot['total']} 条（先截断后过滤 quirk 两侧同款）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
