"""msds 本地镜像回填（dev 工具，msds-direct Ticket 04 双路径比对前置）。

msds 台账事件镜像在 dev 库严重断流（3 行 vs Bitable 71 行，spec §0 探针），
公共行字段值亦陈旧 → 双路径比对空转/误报。本脚本把 Bitable 台账表全量按
「search 形态归一 → handler 既有映射纯函数 _map_fields」UPSERT 写入**本地
dev 库** msds_documents，并把 Bitable 已不存在的记录按软删口径对齐（与事件
镜像最终状态一致）。只读 Bitable、只写本地库；生产环境严禁执行。

用法（backend 目录下）：.venv/Scripts/python.exe scripts/tmp/backfill_msds_mirror.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.bitable_config.store import store
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.feishu.msds_bitable_handler import (
        BITABLE_TO_MODEL,
        _map_fields,
    )
    from app.modules.safety.models import MsdsDocument
    from app.modules.safety.service.bitable_direct import fields as bd_fields

    conn = store.get_connection("msds", "registry")
    if conn is None or conn.status == "disabled":
        print("[x] msds/registry 连接未配置或已停用")
        return 2

    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
    records = await client.list_all_records(
        table_id=conn.table_id, page_size=500, strict=True,
    )
    collected: dict[str, dict[str, object]] = {}
    for r in records:
        rid = str(r.get("record_id") or "")
        if not rid:
            continue
        fields = dict(r.get("fields") or {})
        # search 富文本段形态归一为 handler 预期的纯字符串（仅文本列）
        for column in BITABLE_TO_MODEL:
            if column in fields and column not in ("日期", "MSDS附件"):
                fields[column] = bd_fields.rich_text(fields.get(column)) or None
        mapped = _map_fields(fields)
        collected[rid] = mapped

    upserted = 0
    async with async_session_factory() as session:
        for rid, mapped in collected.items():
            existing = await session.scalar(
                select(MsdsDocument).where(
                    MsdsDocument.feishu_record_id == rid,
                    MsdsDocument.is_deleted == False,  # noqa: E712
                )
            )
            if existing is None:
                existing = MsdsDocument(feishu_record_id=rid)
                session.add(existing)
            for col, val in mapped.items():
                setattr(existing, col, val)
            upserted += 1

        result = await session.execute(
            select(MsdsDocument.feishu_record_id).where(
                MsdsDocument.is_deleted == False,  # noqa: E712
            )
        )
        existing_ids = {rid for (rid,) in result.all() if rid}
        stale = sorted(existing_ids - set(collected))
        for rid in stale:
            row = await session.scalar(
                select(MsdsDocument).where(
                    MsdsDocument.feishu_record_id == rid,
                    MsdsDocument.is_deleted == False,  # noqa: E712
                )
            )
            if row is not None:
                row.is_deleted = True
        await session.commit()

    print(f"upserted={upserted} bitable_total={len(records)}"
          f" soft_deleted_stale={len(stale)}{stale[:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
