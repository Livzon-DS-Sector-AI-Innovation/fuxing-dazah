# -*- coding: utf-8 -*-
"""查消防报警 AI 场景配置与推送相关 DB 配置（修正列名）。"""
import asyncio

import asyncpg

DSN = "postgresql://postgres:postgres@localhost:5432/dazah"


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        print("=== ai_scenario_configs: fire_alarm_analysis ===")
        rows = await conn.fetch(
            "SELECT scenario, enabled, model_profile, note, updated_at, updated_by "
            "FROM safety.ai_scenario_configs WHERE scenario='fire_alarm_analysis' AND is_deleted=false"
        )
        for r in rows:
            print(dict(r))
        if not rows:
            print("(无行 → 走代码默认配置)")

        print("\n=== scheduler_task_configs 列结构 ===")
        cols = [c["column_name"] for c in await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='safety' AND table_name='scheduler_task_configs' ORDER BY ordinal_position"
        )]
        print(cols)

        print("\n=== scheduler_task_configs 消防/中控相关行 ===")
        rows = await conn.fetch(
            "SELECT * FROM safety.scheduler_task_configs "
            "WHERE job_name LIKE '%消防%' OR job_name LIKE '%中控%'"
        )
        for r in rows:
            print({k: r[k] for k in r.keys()})
    finally:
        await conn.close()


asyncio.run(main())
