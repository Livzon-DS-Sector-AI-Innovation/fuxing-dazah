# -*- coding: utf-8 -*-
"""播种「消防报警周报」scheduler_task_configs 行（与 seed_default_task_targets 同逻辑）。"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def main() -> None:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import SchedulerTaskConfig
    from app.modules.safety.service.scheduler_config import (
        _resolve_effective_target,
    )

    async with async_session_factory() as session:
        existing = await session.scalar(
            select(SchedulerTaskConfig).where(
                SchedulerTaskConfig.job_name == "消防报警周报",
                SchedulerTaskConfig.is_deleted == False,  # noqa: E712
            )
        )
        if existing:
            print("已存在:", existing.target_chat_id)
            return
        target, source = _resolve_effective_target("消防报警周报", None)
        row = SchedulerTaskConfig(job_name="消防报警周报", target_chat_id=target)
        session.add(row)
        await session.commit()
        print(f"播种完成: target_chat_id={target} (来源={source})")


asyncio.run(main())
