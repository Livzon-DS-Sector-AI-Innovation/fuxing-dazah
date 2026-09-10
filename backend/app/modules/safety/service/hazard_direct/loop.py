"""隐患直读模式 — 轮询循环（① 隐患AI分析 / ② AI整改审核 / ③ 督办等级计算）。

由安全模块调度器 ``scheduled_task_loop`` 在启动时挂载为子任务，
不新增进程、不改 ``app/main.py``；复用调度器的停止信号。

三个轮询错开启动（默认 0 / 2.5 / 1.25 分钟），避免同时打同一张多维表格
（官方：单表写操作不支持并发，1254291 / 1254607）。
"""

from __future__ import annotations

import asyncio
import logging

from app.modules.safety.service.hazard_direct import config
from app.modules.safety.service.hazard_direct.ai_analysis import run_ai_analysis_round
from app.modules.safety.service.hazard_direct.alert import notify_rounds_exceeded
from app.modules.safety.service.hazard_direct.review import run_review_round
from app.modules.safety.service.hazard_direct.supervision import run_supervision_round

logger = logging.getLogger(__name__)


async def _interruptible_sleep(seconds: float) -> None:
    """可被调度器停止信号打断的 sleep。"""
    from app.modules.safety.scheduler import stop_scheduled_task_flag

    try:
        await asyncio.wait_for(stop_scheduled_task_flag.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def _stopped() -> bool:
    from app.modules.safety.scheduler import stop_scheduled_task_flag

    return stop_scheduled_task_flag.is_set()


async def _ai_loop() -> None:
    """① 隐患AI分析轮询。"""
    interval = config.poll_interval_seconds()
    consecutive = 0
    logger.info("① 隐患AI分析轮询已启动 (间隔=%ds)", interval)
    while not await _stopped():
        error = ""
        try:
            result = await run_ai_analysis_round()
            consecutive = 0 if result.failed == 0 else consecutive + 1
            if result.failed:
                error = f"{result.failed} 条失败"
        except Exception as exc:
            consecutive += 1
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("① 轮询异常")

        if consecutive >= config.alert_after_rounds():
            await notify_rounds_exceeded("隐患AI分析轮询", consecutive, error)
            consecutive = 0  # 告警后重置，避免每轮重复轰炸

        await _interruptible_sleep(interval)
    logger.info("① 隐患AI分析轮询已停止")


async def _review_loop() -> None:
    """② AI整改审核轮询（相对 ① 错开半个周期启动）。"""
    interval = config.poll_interval_seconds()
    stagger = min(config.review_stagger_seconds(), max(0, interval - 1))
    if stagger:
        logger.info("② 隐患整改审核轮询等待错开 %ds 后启动", stagger)
        await _interruptible_sleep(stagger)

    consecutive = 0
    logger.info("② 隐患整改审核轮询已启动 (间隔=%ds)", interval)
    while not await _stopped():
        error = ""
        try:
            result = await run_review_round()
            consecutive = 0 if result.failed == 0 else consecutive + 1
            if result.failed:
                error = f"{result.failed} 条失败"
        except Exception as exc:
            consecutive += 1
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("② 轮询异常")

        if consecutive >= config.alert_after_rounds():
            await notify_rounds_exceeded("隐患整改审核轮询", consecutive, error)
            consecutive = 0

        await _interruptible_sleep(interval)
    logger.info("② 隐患整改审核轮询已停止")


async def _supervision_loop() -> None:
    """③ 督办等级计算轮询（读多维表格 → 算 → 只回写多维表格）。

    只回写「计算结果与当前字段值不同」的记录，避免无意义写。
    不发汇总 DM（每 5 分钟一次会打扰；需要汇总时用 @机器人 或看多维表格）。
    """
    interval = config.poll_interval_seconds()
    stagger = min(config.supervision_stagger_seconds(), max(0, interval - 1))
    if stagger:
        logger.info("③ 督办等级计算轮询等待错开 %ds 后启动", stagger)
        await _interruptible_sleep(stagger)

    consecutive = 0
    logger.info("③ 督办等级计算轮询已启动 (间隔=%ds)", interval)
    while not await _stopped():
        error = ""
        try:
            result = await run_supervision_round()
            consecutive = 0 if result.failed == 0 else consecutive + 1
            if result.failed:
                error = f"{result.failed} 条失败"
        except Exception as exc:
            consecutive += 1
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("③ 轮询异常")

        if consecutive >= config.alert_after_rounds():
            await notify_rounds_exceeded("督办等级计算轮询", consecutive, error)
            consecutive = 0

        await _interruptible_sleep(interval)
    logger.info("③ 督办等级计算轮询已停止")


async def hazard_direct_loop() -> None:
    """按开关启动 ①②③ 轮询；全部关闭时直接返回（不占用资源）。"""
    if not config.direct_poll_enabled():
        logger.info(
            "隐患直读模式未启用（SAFETY_HAZARD_DIRECT_POLL_ENABLED=false），跳过轮询启动"
        )
        return

    tasks: list[asyncio.Task[None]] = []
    if config.ai_poll_enabled():
        tasks.append(asyncio.create_task(_ai_loop()))
    else:
        logger.info("① 隐患AI分析轮询未启用（SAFETY_HAZARD_AI_POLL_ENABLED=false）")
    if config.review_poll_enabled():
        tasks.append(asyncio.create_task(_review_loop()))
    else:
        logger.info("② 隐患整改审核轮询未启用（SAFETY_HAZARD_REVIEW_POLL_ENABLED=false）")
    if config.supervision_poll_enabled():
        tasks.append(asyncio.create_task(_supervision_loop()))
    else:
        logger.info(
            "③ 督办等级计算轮询未启用（SAFETY_HAZARD_SUPERVISION_POLL_ENABLED=false）"
        )

    if not tasks:
        logger.info("隐患直读模式已开启但三个轮询均未启用，无任务运行")
        return

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        raise
