"""knowledge 法规两表 article_no 回填脚本（knowledge-direct Ticket 02，黄色操作）。

前置：先跑 create_article_no_field.py --apply 建列（本脚本对无列表会因
update_record 失败计数，不中断）。从 PG 镜像（SafetyKnowledgeArticle）按
feishu_record_id 匹配两表现有行，把 article_no 回写到 Bitable——只写目标列。

回写纪律（§5 通用 8 条）：串行 + 条目间 0.5s + handler `_set_sync_ignore`
（60s TTL）防「平台发起 changed 事件」回环。

dry-run（默认）只报告匹配与待写清单；--apply 才真正 update_record。
用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/backfill_article_no.py           # dry-run
    .venv/Scripts/python.exe scripts/tmp/backfill_article_no.py --apply   # 回填
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402
from app.modules.safety.models import SafetyKnowledgeArticle  # noqa: E402
from app.modules.safety.service.bitable_direct import reader as bd_reader  # noqa: E402

_KINDS = ("collection", "collection_env")
_WRITE_INTERVAL_SEC = 0.5


async def main(apply: bool) -> int:
    from app.core.database import async_session_factory
    from app.modules.safety.feishu.knowledge_bitable_handler import (
        _set_sync_ignore,
    )

    print(f"== knowledge 两表 article_no 回填 =="
          f"（{'APPLY' if apply else 'DRY-RUN'}；前置：先建列）")

    # 1. 两表现有 record_id 集合（按表归位，防 fid 撞表写错目标）
    ids_by_kind: dict[str, set[str]] = {}
    clients: dict[str, SafetyBitableClient] = {}
    for kind in _KINDS:
        client = bd_reader.resolve_client("knowledge", kind)
        clients[kind] = client
        records = await bd_reader.fetch_all_records(client, strict=True)
        ids_by_kind[kind] = {
            str(r.get("record_id") or "") for r in records
        } - {""}
        label = "安全法规标准" if kind == "collection" else "环保法规标准"
        print(f"  {label}（{kind}）表内行数: {len(ids_by_kind[kind])}")

    # 2. PG 镜像有编号且 fid 命中两表的行
    session = async_session_factory()
    try:
        rows = list((await session.scalars(
            select(SafetyKnowledgeArticle).where(
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
                SafetyKnowledgeArticle.feishu_record_id.isnot(None),
                SafetyKnowledgeArticle.article_no.isnot(None),
            )
        )).all())
    finally:
        await session.close()

    planned: list[tuple[str, SafetyBitableClient, str, str]] = []  # (kind, client, rid, no)
    skipped_no_fid = 0
    for row in rows:
        fid = str(row.feishu_record_id or "")
        kind = next((k for k in _KINDS if fid in ids_by_kind[k]), None)
        if kind is None:
            skipped_no_fid += 1
            continue
        planned.append((kind, clients[kind], fid, str(row.article_no)))

    print(f"  PG 待回填行={len(planned)}"
          f"（镜像无编号/两表无此 fid 跳过={skipped_no_fid}）")
    if not planned:
        return 0

    # 3. 串行回写（只写 article_no 列）
    ok = failed = 0
    for i, (kind, client, fid, no) in enumerate(planned, start=1):
        label = "安全" if kind == "collection" else "环保"
        if not apply:
            print(f"  [dry] {i}/{len(planned)} {label} {fid} -> {no}")
            ok += 1
            continue
        try:
            written = await client.update_record(fid, {"article_no": no})
        except Exception as exc:
            print(f"  [FAIL] {label} {fid}: {exc}")
            failed += 1
        else:
            if written:
                await _set_sync_ignore(fid)
                ok += 1
                if i % 50 == 0 or i == len(planned):
                    print(f"  进度 {i}/{len(planned)}（成功 {ok} 失败 {failed}）")
            else:
                print(f"  [WARN] {label} {fid}: update_record False"
                      f"（表仍无 article_no 列？先跑建列脚本 --apply）")
                failed += 1
        await asyncio.sleep(_WRITE_INTERVAL_SEC)

    print(f"  完成：成功/计划 {ok}/{len(planned)} 失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--apply" in sys.argv)))
