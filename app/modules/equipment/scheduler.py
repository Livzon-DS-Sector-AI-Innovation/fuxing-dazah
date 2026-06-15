"""Maintenance plan auto-generation background scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.database import async_session_factory

logger = logging.getLogger(__name__)

# 中国标准时间 UTC+8
CST = timezone(timedelta(hours=8))

stop_maintenance_plan_flag = asyncio.Event()


async def maintenance_plan_loop() -> None:
    """每天 00:05 CST 扫描到期的维护计划并自动生成工单。

    选择 00:05 而非 00:00 是为了避开飞书成员同步（00:00）的执行窗口，
    减少并发数据库连接压力。
    """
    settings = get_settings()
    if not settings.MAINTENANCE_PLAN_AUTO_ENABLED:
        logger.info(
            "维护计划自动生成功能已关闭（MAINTENANCE_PLAN_AUTO_ENABLED=false），跳过启动"
        )
        return

    logger.info("维护计划自动生成任务已启动（每天 00:05 CST）")

    while not stop_maintenance_plan_flag.is_set():
        # 计算到下一个 00:05 CST 的等待秒数
        now = datetime.now(CST)
        next_run = (now + timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0,
        )
        # 如果当前时间还没过今天的 00:05，则设为今天
        if now.hour == 0 and now.minute < 5:
            next_run = now.replace(
                hour=0, minute=5, second=0, microsecond=0,
            )
        wait_seconds = (next_run - now).total_seconds()

        logger.info(
            "下次维护计划扫描将在 %.0f 分钟后（%s）",
            wait_seconds / 60,
            next_run.strftime("%Y-%m-%d %H:%M"),
        )

        try:
            await asyncio.wait_for(
                stop_maintenance_plan_flag.wait(),
                timeout=wait_seconds,
            )
            break  # stop flag 被设置，退出循环
        except TimeoutError:
            pass

        if stop_maintenance_plan_flag.is_set():
            break

        # 每次 tick 重新读取配置，支持运行时动态开关
        if not get_settings().MAINTENANCE_PLAN_AUTO_ENABLED:
            logger.debug("维护计划自动生成已关闭，跳过本轮")
            continue

        try:
            async with async_session_factory() as db:
                from app.modules.equipment.service.maintenance_plan import (
                    generate_due_work_orders,
                )

                created_count, skipped_count = await generate_due_work_orders(
                    db
                )
                await db.commit()

                logger.info(
                    "维护计划自动生成完成: 创建 %d 个工单, 跳过 %d 个计划",
                    created_count,
                    skipped_count,
                )
        except Exception:
            logger.exception("维护计划自动生成循环异常")

    logger.info("维护计划自动生成任务已停止")
