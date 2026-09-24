# -*- coding: utf-8 -*-
"""查今日（2026-09-22）定时任务触发情况。"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def main() -> None:
    import asyncpg

    conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/dazah")
    try:
        rows = await conn.fetch(
            "SELECT job_name, fired_date, status, attempt_count, last_attempt_at "
            "FROM safety.scheduler_job_runs "
            "WHERE fired_date >= '2026-09-21' ORDER BY last_attempt_at"
        )
        for r in rows:
            print(dict(r))
    finally:
        await conn.close()


asyncio.run(main())
