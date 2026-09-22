"""cert 本地镜像回填（dev 工具，cert-direct Ticket 06 双路径比对前置）。

cert 事件镜像只在生产运行，本地库 person_certificates 为空 → 双路径比对空转。
本脚本把 Bitable 3 表全量按既有映射纯函数 + repo.upsert_from_bitable 写入
**本地 dev 库**镜像，并把 Bitable 已不存在的记录按软删口径对齐（与事件镜像
最终状态一致）。只读 Bitable、只写本地库；生产环境严禁执行。

用法（backend 目录下）：.venv/Scripts/python.exe scripts/tmp/backfill_cert_mirror.py
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
    from app.modules.safety.feishu.cert_bitable import (
        map_guardian_cert_fields,
        map_special_op_cert_fields,
    )
    from app.modules.safety.models import PersonCertificate
    from app.modules.safety.repository import PersonCertificateRepository

    conns = {v.kind: v for v in store.get_connections("cert") if v.enabled}
    collected: dict[str, dict[str, object]] = {}
    per_kind: dict[str, int] = {}
    for kind in ("special_op", "guardian_a", "guardian_b"):
        conn = conns.get(kind)
        if conn is None or not conn.app_token or not conn.table_id:
            print(f"[!] {kind} 连接未配置，跳过")
            continue
        client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
        records = await client.list_all_records(
            table_id=conn.table_id, page_size=500, strict=True,
        )
        n = 0
        for r in records:
            rid = str(r.get("record_id") or "")
            fields = r.get("fields") or {}
            if kind == "special_op":
                mapped = map_special_op_cert_fields(fields)
            else:
                mapped = map_guardian_cert_fields(fields, kind)
            if mapped is None:
                continue
            collected[rid] = mapped
            n += 1
        per_kind[kind] = n

    async with async_session_factory() as session:
        repo = PersonCertificateRepository(session)
        for rid, mapped in collected.items():
            await repo.upsert_from_bitable(mapped, rid)

        result = await session.execute(
            select(PersonCertificate.feishu_record_id).where(
                PersonCertificate.source == "bitable",
                PersonCertificate.is_deleted == False,  # noqa: E712
            )
        )
        existing = {rid for (rid,) in result.all() if rid}
        stale = sorted(existing - set(collected))
        for rid in stale:
            await repo.soft_delete_by_feishu_id(rid)
        await session.commit()

    print(f"upserted={len(collected)} per_kind={per_kind} soft_deleted_stale={len(stale)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
