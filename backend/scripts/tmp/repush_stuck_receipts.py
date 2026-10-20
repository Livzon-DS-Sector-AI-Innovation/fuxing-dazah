"""滞留候选回执补发（一次性对账修复）。

背景：2026-10-19 补推批次的契约②回执 10s 超时 + 重试，两次都落在 ragplus
promote 的解析等待期内 → dazah 记失败、候选滞留 pending，文件从未进正式库
（109 条）。promote 已改为触发即返回（毫秒级），本脚本按本仓留痕的判定
结果补发回执，并把回执响应中的 kb_doc_id 回填 ragplus_doc_map。

用法（backend 目录下；先重启 ragplus backend 加载快速 promote）：

    PYTHONPATH=. uv run python scripts/tmp/repush_stuck_receipts.py           # 干跑
    PYTHONPATH=. uv run python scripts/tmp/repush_stuck_receipts.py --apply  # 补发
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")

RAGPLUS_DB = Path.home() / "Agent work/ragplus-x/backend/data/ragplus.db"


async def _load_judgments() -> dict[str, dict]:
    """本仓 regulation_ingest_runs.items_result → {candidate_id: 判定}。"""
    from sqlalchemy import select
    from app.core.database import async_session_factory
    from app.modules.safety.models import RegulationIngestRun

    judgments: dict[str, dict] = {}
    async with async_session_factory() as s:
        rows = (await s.execute(
            select(RegulationIngestRun.items_result).where(
                RegulationIngestRun.is_deleted.is_(False),
                RegulationIngestRun.items_result.isnot(None),
            )
        )).scalars().all()
    for items in rows:
        for it in items or []:
            cid = str(it.get("candidate_id") or "")
            if cid:
                judgments[cid] = it
    return judgments


def _load_stranded() -> list[dict]:
    """ragplus SQLite：已推送、已解析、仍 pending 的滞留候选。"""
    conn = sqlite3.connect(f"file:{RAGPLUS_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT candidate_id, filename, title FROM crawler_candidates "
        "WHERE status='pending' AND pushed_at IS NOT NULL AND parse_status='parsed'"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


async def main(apply: bool) -> int:
    from sqlalchemy import select
    from app.core.database import async_session_factory
    from app.modules.safety.knowledge.ragplus_sync import upsert_ragplus_map, KB_REGULATION
    from app.modules.safety.regulation_ingest.ragplus_crawler_client import get_ragplus_crawler_client

    judgments = await _load_judgments()
    stranded = _load_stranded()
    print(f"滞留候选 {len(stranded)} 条；本仓判定留痕 {len(judgments)} 条")

    no_judgment = [c for c in stranded if c["candidate_id"] not in judgments]
    plan = []
    for c in stranded:
        j = judgments.get(c["candidate_id"])
        if not j or j.get("action_taken") not in ("promote", "reject", "duplicate"):
            continue
        plan.append((c, j))
    print(f"可补发 {len(plan)} 条（promote={sum(1 for _, j in plan if j['action_taken']=='promote')} "
          f"reject={sum(1 for _, j in plan if j['action_taken']=='reject')} "
          f"duplicate→reject={sum(1 for _, j in plan if j['action_taken']=='duplicate')}）；"
          f"无判定留痕 {len(no_judgment)} 条跳过")
    for c in no_judgment[:5]:
        print("  无判定:", c["candidate_id"][:8], (c["title"] or "")[:40])
    if not apply:
        print("（干跑结束，未发送）")
        return 0

    client = get_ragplus_crawler_client()
    ok_cnt = fail_cnt = map_filled = 0
    async with async_session_factory() as s:
        for c, j in plan:
            action = j["action_taken"]
            # duplicate 判定 = 台账已有：reject 收口（清暂存+终态），原文不重复入正式库
            send_action = "reject" if action == "duplicate" else action
            reason = (j.get("reason") or "")[:180] + "（回执补发 2026-10-20）"
            try:
                resp = await client.send_lifecycle(c["candidate_id"], send_action, reason)
                ok_cnt += 1
                kb_doc_id = (resp or {}).get("kb_doc_id")
                if send_action == "promote" and kb_doc_id and j.get("bitable_record_id"):
                    await upsert_ragplus_map(
                        s,
                        domain="regulation",
                        biz_key=j["bitable_record_id"],
                        dataset_name=KB_REGULATION,
                        status="active",
                        kb_doc_id=int(kb_doc_id),
                        file_name=c["filename"] or "",
                        title=c["title"] or "",
                    )
                    map_filled += 1
            except Exception as exc:
                fail_cnt += 1
                print(f"  失败 {c['candidate_id'][:8]} {send_action}: {str(exc)[:100]}")
        await s.commit()
    print(f"补发完成：成功 {ok_cnt} 失败 {fail_cnt}；映射回填 {map_filled} 行")
    return 0 if fail_cnt == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="滞留候选回执补发")
    ap.add_argument("--apply", action="store_true", help="执行发送（默认干跑）")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.apply)))
