"""contractor_admission 直读真机只读冒烟（Ticket 08）。

零写入：reader 直拉 → 视图/派生 AI 态/过滤/排序/统计各过一遍；
不经 service 查询路径（变更检测触发器不挂载，绝不触发 AI 审核）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/smoke_contractor_reader.py
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")


async def main() -> int:
    from app.modules.safety.service.contractor_admission_direct import query as dq
    from app.modules.safety.service.contractor_admission_direct.reader import (
        open_reader,
    )

    t0 = time.perf_counter()
    views = await open_reader().fetch_all(strict=True)
    elapsed = time.perf_counter() - t0
    completed = sum(1 for v in views if v.ai_review_status == "completed")
    agreement = sum(1 for v in views if v.safety_agreement_files)
    print(f"[1] fetch_all strict=True: {len(views)} 行 {elapsed:.2f}s"
          f" 派生 completed={completed} 协议挂载={agreement}")
    if not views:
        print("[x] 直读视图为空，中止")
        return 3

    first = dq.sort_views(views)[0]
    print(f"[2] 默认排序首页: id={first.id} company={first.company_name!r}"
          f" type={first.related_party_type!r} submit={first.submit_status!r}"
          f" created_at={first.created_at}")

    filtered = dq.filter_views(views, ai_review_status="completed")
    print(f"[3] 过滤 ai_review_status=completed: {len(filtered)} 行")
    processing = dq.filter_views(views, ai_review_status="processing")
    print(f"[4] 过滤 ai_review_status=processing（派生态不可表达，应恒空）: {len(processing)} 行")

    stats = dq.stats_of(views)
    print(f"[5] stats: total={stats['total']}"
          f" by_ai_review_status={stats['by_ai_review_status']}"
          f" by_related_party_type={stats['by_related_party_type']}"
          f" by_submit_status={stats['by_submit_status']}")

    hit = dq.find_view(views, views[0].id)
    print(f"[6] find_view({views[0].id}): {'命中' if hit else '未命中'}")
    print("[OK] 直读冒烟完成（零写入）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
