"""MSDS 存量回填 ragplus-x（台账 28 字段 md + 供应商资料 PDF）。

存量数据不走事件（订阅只推增量），本脚本从飞书直读全量拉取后回填：

  1. 台账（registry 表）：msds_direct 直读 fetch_all → 每条 28 字段拼
     .md 全文（复用 MSDS_FIELD_LABELS/build_msds_full_text，与增量收口
     msds_indexer 完全同构）→ 上传 MSDS 库（biz_key=registry:{record_id}）。
  2. 采集（collection 表）：直读取「供应商资料」附件 file_token → 下载
     PDF 上传（biz_key=collection:{record_id}，与增量
     _schedule_ragplus_upload 键规范一致）。
  3. 断点续跑：ragplus_doc_map 已 active 且有 kb_doc_id 的键跳过（幂等）。
  4. 编排对齐 ragplus_bulk_ingest 稳定参数：上传串行、解析 25/批
     （811 parallel 曾触发引擎 code=100）、统一轮询至 DONE/FAIL。

默认 dry-run 只盘点；--apply 真跑。失败清单 + 对账表落档
仓库根 .scratch/msds-ragplus/。

用法（backend 目录下）：

    PYTHONPATH=. uv run python scripts/tmp/backfill_msds_to_ragplus.py            # dry-run
    PYTHONPATH=. uv run python scripts/tmp/backfill_msds_to_ragplus.py --apply    # 真跑
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, ".")

from app.modules.safety.knowledge.ragplus_sync import (  # noqa: E402
    KB_MSDS,
    build_admin_client,
    upsert_ragplus_map,
)
from app.modules.safety.knowledge.msds_indexer import (  # noqa: E402
    MSDS_FIELD_LABELS,
    build_msds_full_text,
)

# backend/scripts/tmp/x.py → parents[3] = 仓库根
SCRATCH_DIR = Path(__file__).resolve().parents[3] / ".scratch" / "msds-ragplus"
_PARSE_BATCH = 25
_WAIT_DEADLINE = 1800.0


def _view_title(view: Any) -> str:
    """对齐 msds_indexer._article_title（view 与 ORM 字段同名）。"""
    if view.name:
        return str(view.name).strip()
    if view.cas_no:
        return f"MSDS-{str(view.cas_no).strip()}"
    return f"MSDS-{view.feishu_record_id or view.id}"


def _view_full_text(view: Any) -> str:
    """view 版 28 字段全文（build_msds_full_text duck-typing 直用）。"""
    return build_msds_full_text(view)


# ═══════════════════════════════════════════════════════════════
# 数据源（飞书直读，不依赖本地镜像）
# ═══════════════════════════════════════════════════════════════


async def collect_registry_pending() -> list[dict[str, Any]]:
    """台账直读全量 → 待传项 [{biz_key, title, file_name, blob, content_type}]。"""
    from app.modules.safety.service.msds_direct import reader as md_reader

    views = await md_reader.open_reader().fetch_all(strict=True)
    pending: list[dict[str, Any]] = []
    for v in views:
        rid = (v.feishu_record_id or "").strip()
        if not rid:
            continue  # 直读行必有 record_id；防御空值
        title = _view_title(v)
        blob = _view_full_text(v).encode("utf-8")
        if not blob:
            continue
        pending.append({
            "biz_key": f"registry:{rid}",
            "title": title,
            "file_name": f"{title}.md",
            "blob": blob,
            "content_type": "text/markdown",
        })
    return pending


async def collect_collection_pending() -> list[dict[str, Any]]:
    """采集表直读全量 → 供应商 PDF 待传项（附件缺失跳过并计数）。"""
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.bitable_direct import reader as bd_reader
    from app.modules.safety.bitable_config.store import store

    conn = store.get_connection("msds", "collection")
    if conn is None:
        print("  采集表未配置，跳过 PDF 回填")
        return []
    client = bd_reader.resolve_client("msds", "collection")
    records = await bd_reader.fetch_all_records(client, strict=True)

    dl = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
    pending: list[dict[str, Any]] = []
    for r in records:
        rid = str(r.get("record_id") or "")
        if not rid:
            continue
        fields = r.get("fields") or {}
        atts = fields.get("供应商资料")
        first = (
            atts[0]
            if isinstance(atts, list) and atts and isinstance(atts[0], dict)
            else {}
        )
        file_token = str(first.get("file_token") or "")
        if not file_token:
            continue
        file_name = str(first.get("name") or f"{rid}.pdf")
        try:
            blob = await dl.download_attachment(file_token)
        except Exception as exc:
            pending.append({
                "biz_key": f"collection:{rid}",
                "title": f"MSDS-{file_name}",
                "file_name": file_name,
                "blob": None,
                "content_type": first.get("type") or "application/pdf",
                "error": f"download_failed: {exc}",
            })
            continue
        if not blob:
            continue
        pending.append({
            "biz_key": f"collection:{rid}",
            "title": f"MSDS-{file_name}",
            "file_name": file_name,
            "blob": blob,
            "content_type": first.get("type") or "application/pdf",
        })
    return pending


# ═══════════════════════════════════════════════════════════════
# 上传-解析-登记（对齐 ragplus_bulk_ingest 编排）
# ═══════════════════════════════════════════════════════════════


async def _load_existing_active() -> set[str]:
    """预载 msds 域 active 映射键（断点续跑）。"""
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import RagplusDocMap

    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RagplusDocMap).where(
                        RagplusDocMap.domain == "msds",
                        RagplusDocMap.is_deleted.is_(False),
                        RagplusDocMap.status == "active",
                        RagplusDocMap.kb_doc_id.isnot(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {str(r.biz_key) for r in rows}


async def upload_parse_register(
    admin: Any,
    kb: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, int]:
    """串行上传 → 25/批解析 → 统一轮询 → 映射登记。返回计数。"""
    counts = {
        "uploaded": 0, "upload_failed": 0,
        "parsed_ok": 0, "parse_failed": 0,
    }
    doc_ids: dict[int, dict[str, Any]] = {}  # kb_doc_id → item
    for i, it in enumerate(items, 1):
        try:
            doc = await admin.upload_document(
                kb["id"], it["file_name"], it["blob"], it["content_type"],
            )
            doc_ids[int(doc["id"])] = it
            counts["uploaded"] += 1
        except Exception as exc:
            counts["upload_failed"] += 1
            print(f"  [上传失败] {it['biz_key']}: {exc}")
        if i % 20 == 0:
            print(f"  上传进度 {i}/{len(items)}")

    ids = list(doc_ids.keys())
    for s in range(0, len(ids), _PARSE_BATCH):
        batch = ids[s: s + _PARSE_BATCH]
        try:
            await admin.parse_documents(kb["id"], batch, mode="parallel")
        except Exception as exc:
            print(f"  [解析批次失败] {len(batch)} 条: {exc}")

    if ids:
        results = await admin.wait_documents_ready(
            kb["id"], ids, poll=4, deadline=_WAIT_DEADLINE,
        )

        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            for doc_id, it in doc_ids.items():
                r = results.get(doc_id) or {}
                ok = str(r.get("status") or "") == "DONE"
                counts["parsed_ok" if ok else "parse_failed"] += 1
                await upsert_ragplus_map(
                    session,
                    domain="msds",
                    biz_key=it["biz_key"],
                    dataset_name=KB_MSDS,
                    status="active" if ok else "failed",
                    kb_doc_id=doc_id,
                    dataset_id=str(kb.get("dataset_id") or "") or None,
                    title=it["title"],
                    file_name=it["file_name"],
                    last_error=None
                    if ok
                    else str(r.get("fail_reason") or r.get("status"))[:500],
                )
            await session.commit()
    return counts


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="真跑（默认 dry-run 只盘点）",
    )
    args = parser.parse_args()

    print(f"== MSDS 存量回填 ragplus（{'APPLY' if args.apply else 'DRY-RUN'}）==")
    registry = await collect_registry_pending()
    print(f"  台账待传盘点：{len(registry)} 条（.md 结构化全文）")
    collection = await collect_collection_pending()
    print(f"  采集 PDF 待传盘点：{len(collection)} 条")

    active = await _load_existing_active()
    registry_todo = [it for it in registry if it["biz_key"] not in active]
    collection_todo = [it for it in collection if it["biz_key"] not in active]
    dl_failed = [it for it in collection_todo if it.get("blob") is None]
    collection_todo = [it for it in collection_todo if it.get("blob") is not None]
    print(
        f"  断点续跑：跳过已 active {len(registry) - len(registry_todo)}"
        f"+{len(collection) - len(collection_todo) - len(dl_failed)} 条；"
        f"下载失败 {len(dl_failed)} 条"
    )

    if not args.apply:
        print("== DRY-RUN 结束（--apply 真跑）==")
        for it in registry_todo[:5]:
            print(f"    e.g. {it['biz_key']} → {it['file_name']}")
        return 0

    admin = build_admin_client()
    try:
        await admin.login()
        kb = await admin.ensure_kb(KB_MSDS)
        all_todo = registry_todo + collection_todo
        counts = await upload_parse_register(admin, kb, all_todo)
    finally:
        await admin.aclose()

    print(
        f"== 完成：上传 {counts['uploaded']} 失败 {counts['upload_failed']}；"
        f"解析成功 {counts['parsed_ok']} 失败 {counts['parse_failed']} =="
    )

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (SCRATCH_DIR / f"backfill_对账_{stamp}.json").write_text(
        json.dumps(
            {
                "time": datetime.now(UTC).isoformat(timespec="seconds"),
                "registry_total": len(registry),
                "collection_total": len(collection),
                "skipped_active": len(registry) - len(registry_todo)
                + len(collection) - len(collection_todo) - len(dl_failed),
                "download_failed": [it["biz_key"] for it in dl_failed],
                **counts,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"对账已落档：{SCRATCH_DIR}/backfill_对账_{stamp}.json")
    return 1 if (counts["upload_failed"] or counts["parse_failed"]) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
