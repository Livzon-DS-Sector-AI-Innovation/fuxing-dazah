"""backfill_training_attendees — 参训人明细批量回填（签到表补解析）。

背景：链3 vision 解析此前只回填 Bitable 计数列，names/scores 明细未落库
（个人档案联动培训的一期缺口）。本脚本对「有签到表附件且尚无 attendee 行」
的培训行逐个重新触发 parse_training_record——只补漏不重跑（已有明细的行
跳过，避免备注被重复追加解析明细行）。

注意：parse_training_record 单次调用会全表读行 + 下载附件 + vision 调用，
逐行串行较慢；--limit 控制批量，--dry-run 只盘点不解析。

用法（backend 下）：
    .venv/bin/python -m scripts.backfill_training_attendees --dry-run
    .venv/bin/python -m scripts.backfill_training_attendees --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func  # noqa: E402

from app.core.database import async_session_factory  # noqa: E402
from app.modules.safety.models import TrainingAttendee  # noqa: E402
from app.modules.safety.service.bitable_direct import fields as bd_fields  # noqa: E402
from app.modules.safety.service.bitable_direct import reader as bd_reader  # noqa: E402
from app.modules.safety.service.training_behavior import record_parsing  # noqa: E402

_READ_FIELDS = (
    "培训名称", "实施日期", record_parsing.SIGN_COLUMN,
    record_parsing.ATTENDANCE_COLUMN, record_parsing.REMARK_COLUMN,
)


async def main(dry_run: bool, limit: int | None) -> None:
    client = bd_reader.resolve_client("training_behavior", "training")
    records = await client.list_all_records(
        field_names=list(_READ_FIELDS), strict=True
    )
    with_sign = [
        r for r in records
        if bd_fields.attachments(r.get("fields") or {}, record_parsing.SIGN_COLUMN)
    ]
    async with async_session_factory() as session:
        res = await session.execute(
            select(
                TrainingAttendee.training_record_id,
                func.count().label("n"),
            ).where(TrainingAttendee.is_deleted == False).group_by(  # noqa: E712
                TrainingAttendee.training_record_id
            )
        )
        known_counts = {row[0]: row[1] for row in res}

    todo = [
        r for r in with_sign
        if str(r.get("record_id") or "") not in known_counts
    ]
    print(
        f"培训行总数 {len(records)}｜有签到附件 {len(with_sign)}｜"
        f"已有明细 {len(known_counts)} 行｜待补解析 {len(todo)}"
    )
    if dry_run:
        for r in todo[:20]:
            f = r.get("fields") or {}
            print(
                f"  [待解析] {r.get('record_id')} "
                f"{bd_fields.text(f, '培训名称')} "
                f"实施={bd_fields.text(f, '实施日期')}"
            )
        return
    if limit is not None:
        todo = todo[:limit]

    ok = fail = 0
    async with async_session_factory() as session:
        for r in todo:
            rid = str(r.get("record_id") or "")
            try:
                data = await record_parsing.parse_training_record(
                    record_id=rid, db=session
                )
                await session.commit()
                ok += 1
                print(
                    f"  [OK] {rid} 参训人落库 {data.get('attendees_persisted')} 行"
                )
            except Exception as exc:
                await session.rollback()
                fail += 1
                print(f"  [FAIL] {rid}: {exc}")
    print(f"完成：成功 {ok}｜失败 {fail}｜跳过（已有明细/无附件）"
          f" {len(with_sign) - len(todo)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只盘点不解析")
    parser.add_argument("--limit", type=int, default=None, help="最多解析行数")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, limit=args.limit))
