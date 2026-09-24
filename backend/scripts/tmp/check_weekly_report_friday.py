# -*- coding: utf-8 -*-
"""查消防报警周报上周五（2026-09-18）发送情况：
1. scheduler_task_configs 覆写配置（是否存在周报任务覆写）
2. scheduler_job_runs 上周五运行记录
3. fire_alarm_records 上周（9.14-9.20）数据量
"""
import asyncio
import json

import asyncpg

DSN = "postgresql://postgres:postgres@localhost:5432/dazah"


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        print("=== 1. scheduler_task_configs（DB 覆写）===")
        rows = await conn.fetch(
            "SELECT job_name, enabled, hour, minute, dow, retry_until_hour, retry_until_minute "
            "FROM safety.scheduler_task_configs ORDER BY job_name"
        )
        if rows:
            for r in rows:
                print(dict(r))
        else:
            print("(空，无覆写)")

        print("\n=== 2. scheduler_job_runs 2026-09-15 ~ 2026-09-21 ===")
        rows = await conn.fetch(
            "SELECT job_name, fired_date, status, attempt_count, alerted, last_attempt_at "
            "FROM safety.scheduler_job_runs "
            "WHERE fired_date BETWEEN '2026-09-15' AND '2026-09-21' "
            "ORDER BY fired_date, job_name"
        )
        for r in rows:
            print(dict(r))

        print("\n=== 3. fire_alarm_records 2026-09-14 ~ 2026-09-20 按天统计 ===")
        rows = await conn.fetch(
            "SELECT alarm_time::date AS d, count(*) AS n "
            "FROM safety.fire_alarm_records "
            "WHERE alarm_time >= '2026-09-14' AND alarm_time < '2026-09-21' "
            "GROUP BY 1 ORDER BY 1"
        )
        for r in rows:
            print(dict(r))

        print("\n=== 4. scheduler_job_runs 全部任务名（看周报是否曾以其他名字跑过）===")
        rows = await conn.fetch(
            "SELECT DISTINCT job_name FROM safety.scheduler_job_runs ORDER BY 1"
        )
        for r in rows:
            print(r["job_name"])
    finally:
        await conn.close()


if __name__ == "__main__":
    print(json.dumps({"dsn": "dazah@localhost"}))
    asyncio.run(main())
