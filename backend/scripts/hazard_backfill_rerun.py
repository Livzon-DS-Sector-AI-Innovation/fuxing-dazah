"""P2-4 T05-C —— ① 定向重跑器（指定 record_id 走标准识别+写回链）。

复刻轮询主流程单条路径：record_lock → _identify_one → write_ai_analysis
（D5 CAS 写前回读）→ failure_ledger.record_success。用于字段完整率修补的
小批量定向补全（分类（AI）非空、轮询判据不吃的历史缺列记录）。

- ``--record-ids``：逗号分隔；缺省=T05 裁决清单 C 组 10 条（级别 2+类别 8）
- ``--confirm``：真实写回门（缺省 dry-run 只跑 _identify_one 前的取数与视图
  构造，不调 AI 不写回）；逐条写回、逐条报告成败
- 语义=① 标准重跑：AI 列全部按新输出重写（CAS 保护窗口内人工改动）

用法（cwd=backend）::

    .venv/bin/python scripts/hazard_backfill_rerun.py            # dry-run
    .venv/bin/python scripts/hazard_backfill_rerun.py --confirm  # 真跑 C 组
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.getcwd())

# T05 裁决清单 C 组（.scratch/hazard-p2-closeout/evidence/backfill-adjudication.md）
C_GROUP_LEVEL = ["recvllDYG0KwDN", "recvmSWRW0TJiV"]
C_GROUP_CATEGORY = [
    "recvoKiLyBwKlA", "recvoL2BzFflUS", "recvq9vEyx4V7S", "recvqM5triJ8hM",
    "recvsanqY7ssLK", "recvsaxNelLIw3", "recvsekFtfo8ab", "recvt5l0Tbfxmu",
]


async def _rerun_one(client: Any, record_id: str, *, confirm: bool) -> tuple[str, str]:
    """单条重跑，返回 (status, detail)——status ∈ done/skip/failed/dry-run。"""
    from app.modules.safety.service.hazard_direct import (
        ai_analysis,
        bitable_repo,
        failure_ledger,
    )
    from app.modules.safety.service.hazard_direct.field_authority import F_TYPE_AI

    record = {"record_id": record_id, "fields": await client.get_record(record_id)}
    fields = record.get("fields") or {}
    if not fields:
        return "skip", "记录不存在/读取失败"
    view = bitable_repo.to_view(record)

    async with bitable_repo.record_lock(record_id):
        if not confirm:
            return (
                "dry-run",
                f"可重跑：描述 {len(view.description or '')} 字｜"
                f"现分类（AI）={view.raw.get(F_TYPE_AI)!r}",
            )
        output = await ai_analysis._identify_one(client, view)
        async with bitable_repo.WRITE_LOCK:
            ok = await bitable_repo.write_ai_analysis(
                client,
                record_id,
                hazard_no=None,
                output={
                    **output,
                    "advice_text": ai_analysis._build_advice_text(output),
                },
                supervision_label=ai_analysis._supervision_label(view),
                snapshot_fields=fields,
            )
        if not ok:
            return "failed", "写回返回 False"
        await failure_ledger.record_success(record_id)
        return (
            "done",
            f"级别={output.get('hazard_level')} 类别={output.get('hazard_category')}",
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record-ids", default=",".join(C_GROUP_LEVEL + C_GROUP_CATEGORY),
        help="逗号分隔 record_id 清单（默认=T05 C 组 10 条）",
    )
    parser.add_argument("--confirm", action="store_true", help="真实写回确认门")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    ids = [rid.strip() for rid in args.record_ids.split(",") if rid.strip()]
    print(f"目标 {len(ids)} 条｜{'真写回' if args.confirm else 'dry-run'}")
    client = SafetyBitableClient()
    done = failed = 0
    for rid in ids:
        try:
            status, detail = await _rerun_one(client, rid, confirm=args.confirm)
        except Exception as exc:  # noqa: BLE001 — 逐条隔离，失败不中断
            status, detail = "failed", f"{type(exc).__name__}: {str(exc)[:120]}"
        done += status == "done"
        failed += status == "failed"
        print(f"  {rid}: {status}（{detail}）")
    print(f"结束：done={done} failed={failed} skip/其他={len(ids) - done - failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
