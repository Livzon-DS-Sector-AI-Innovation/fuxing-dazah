"""msds 台账直读读取器真机只读冒烟（Ticket 04）。

只读零写入：全量拉取 MSDS 收录台账表，打印行数/耗时/首行视图字段抽样
（直读常量列核对）。用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/smoke_msds_reader.py

退出码：0 成功；3 拉取失败。
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")


async def main() -> int:
    from app.modules.safety.service.msds_direct.reader import open_reader

    t0 = time.perf_counter()
    views = await open_reader().fetch_all(strict=True)
    elapsed = time.perf_counter() - t0
    print(f"msds 台账直读冒烟：{len(views)} 行，{elapsed:.2f}s")
    if not views:
        print("[x] 直读返回 0 行（表空或连接异常）")
        return 3
    v = views[0]
    print("首行字段抽样:")
    print(f"  id={v.id} name={v.name!r} cas_no={v.cas_no!r}"
          f" source_date={v.source_date}")
    print(f"  review_status={v.review_status} archive_status={v.archive_status}"
          f" is_deleted={v.is_deleted}")
    print(f"  created_at={v.created_at} collection_record_id="
          f"{v.collection_record_id} label_elements={v.label_elements}")
    print(f"  msds_attachment={[a.get('name') for a in (v.msds_attachment or [])]}")
    dates = [x.source_date for x in views if x.source_date is not None]
    if dates:
        print(f"  日期覆盖：非空 {len(dates)}/{len(views)}，"
              f"min={min(dates)} max={max(dates)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001（冒烟脚本顶层兜底）
        print(f"[x] {exc}")
        sys.exit(3)
