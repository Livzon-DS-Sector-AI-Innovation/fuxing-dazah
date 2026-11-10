"""① 定向重跑器 CLI（指定 record_id 走标准识别+写回链）。

重跑核心已下沉 ``hazard_direct/rerun.py::rerun_record``（P3-1 T03，可导入
可单测）；本脚本只保留 CLI 与默认清单。单条链路语义：
record_lock → _identify_one → write_ai_analysis（D5 CAS）→ failure_ledger。

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

sys.path.insert(0, os.getcwd())

# T05 裁决清单 C 组（.scratch/hazard-p2-closeout/evidence/backfill-adjudication.md）
C_GROUP_LEVEL = ["recvllDYG0KwDN", "recvmSWRW0TJiV"]
C_GROUP_CATEGORY = [
    "recvoKiLyBwKlA", "recvoL2BzFflUS", "recvq9vEyx4V7S", "recvqM5triJ8hM",
    "recvsanqY7ssLK", "recvsaxNelLIw3", "recvsekFtfo8ab", "recvt5l0Tbfxmu",
]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record-ids", default=",".join(C_GROUP_LEVEL + C_GROUP_CATEGORY),
        help="逗号分隔 record_id 清单（默认=T05 C 组 10 条）",
    )
    parser.add_argument(
        "--stale", action="store_true",
        help="stale 模式：忽略 --record-ids，全表扫描取 input_changed 组按需重算",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="stale 模式单次上限（缺省=registry SAFETY_HAZARD_STALE_RERUN_MAX；只能更低不能更高）",
    )
    parser.add_argument("--confirm", action="store_true", help="真实写回确认门")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard_direct.rerun import (
        rerun_record,
        stale_rerun,
    )

    client = SafetyBitableClient()

    if args.stale:
        from app.modules.safety.app_config.store import store as config_store

        registry_cap = config_store.get_int(
            "SAFETY_HAZARD_STALE_RERUN_MAX", 20, minimum=0
        )
        limit = args.limit if args.limit is not None else registry_cap
        records = await client.list_all_records(strict=True)
        print(
            f"stale 模式｜{'真写回' if args.confirm else 'dry-run'}｜"
            f"limit={min(limit, registry_cap)}（registry 上限 {registry_cap}）"
        )
        report = await stale_rerun(
            client, records,
            limit=limit, registry_cap=registry_cap, confirm=args.confirm,
        )
        if report.protected:
            print(f"保护清单（人工改过 AI 列，永不重算）{len(report.protected)} 条：")
            for rid in report.protected:
                print(f"  [protect] {rid}")
        for rid, detail in report.details.items():
            diff = report.diffs.get(rid)
            suffix = f"｜{diff}" if diff else ""
            print(f"  {rid}: {detail}{suffix}")
        print(
            f"结束：done={report.done} failed={report.failed} "
            f"dry-run={report.dry_run} 保护={len(report.protected)}"
        )
        return 0

    ids = [rid.strip() for rid in args.record_ids.split(",") if rid.strip()]
    print(f"目标 {len(ids)} 条｜{'真写回' if args.confirm else 'dry-run'}")
    done = failed = 0
    for rid in ids:
        try:
            status, detail = await rerun_record(client, rid, confirm=args.confirm)
        except Exception as exc:  # noqa: BLE001 — 逐条隔离，失败不中断
            status, detail = "failed", f"{type(exc).__name__}: {str(exc)[:120]}"
        done += status == "done"
        failed += status == "failed"
        print(f"  {rid}: {status}（{detail}）")
    print(f"结束：done={done} failed={failed} skip/其他={len(ids) - done - failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
