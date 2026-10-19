"""MSDS ragplus 映射补登记（一次性对账修复）。

背景：backfill_msds_to_ragplus.py 轮询 deadline（30 分钟）早于单 CPU 引擎
解析完成时，映射行会被标 failed（脚本超时标注，非引擎失败——与法规一期
「37 篇入库失败」同族现象）。本脚本对 msds 域 failed 且有 kb_doc_id 的行：
查 ragplus 实际文档状态补登记——DONE → active；FAIL → 更新 last_error；
仍 RUNNING → 跳过（稍后再跑）。不重复上传（与回填脚本断点续跑互补）。

用法（backend 目录下）：

    PYTHONPATH=. uv run python scripts/tmp/reconcile_msds_ragplus_map.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.modules.safety.knowledge.ragplus_sync import (  # noqa: E402
    KB_MSDS,
    build_admin_client,
)


async def main() -> int:
    from app.core.database import async_session_factory
    from app.modules.safety.models import RagplusDocMap

    admin = build_admin_client()
    try:
        await admin.login()
        kb = next(
            (k for k in await admin.list_kbs() if k.get("name") == KB_MSDS), None,
        )
        if not kb:
            print("MSDS 库不存在")
            return 1
        engine_status = {
            int(d["id"]): str(d.get("status") or "")
            for d in await admin.list_documents(kb["id"])
        }
    finally:
        await admin.aclose()

    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RagplusDocMap).where(
                        RagplusDocMap.domain == "msds",
                        RagplusDocMap.is_deleted.is_(False),
                        RagplusDocMap.status == "failed",
                        RagplusDocMap.kb_doc_id.isnot(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        counts = {"to_active": 0, "still_running": 0, "real_fail": 0}
        for r in rows:
            st = engine_status.get(int(r.kb_doc_id))
            if st == "DONE":
                r.status = "active"
                r.last_error = None
                counts["to_active"] += 1
            elif st in ("RUNNING", "PARSING", "UNSTART", "PENDING"):
                counts["still_running"] += 1
            else:
                r.last_error = f"engine: {st}"[:500]
                counts["real_fail"] += 1
        await session.commit()

    print(
        f"补登记完成：active {counts['to_active']}；"
        f"引擎仍在跑 {counts['still_running']}（稍后重跑本脚本）；"
        f"真失败 {counts['real_fail']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
