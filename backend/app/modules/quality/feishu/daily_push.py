"""出报日期当日机器人任务推送：每天定时把当天需出报的检验任务推送到配置的群。

由 app/main.py 按 safety 调度先例最小挂载（模块级 loop + stop_flag）。
- 08:05 早间推送：今日出报任务 + 待复核任务列表（填报中的任务另发填报卡片）
- 15:00 午后催办：今日出报但尚未完成/复核的任务再提醒一次
"""

import asyncio
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str, default: tuple[int, int]) -> tuple[int, int]:
    """解析 HH:MM 配置（如 08:05），非法/为空回退默认值。"""
    try:
        h, m = value.strip().split(":")
        return int(h), int(m)
    except Exception:
        return default


# 每天推送时间（服务器本地时区），环境变量可调
_PUSH_HOUR, _PUSH_MINUTE = _parse_hhmm(os.getenv("QUALITY_PUSH_MORNING", ""), (8, 5))
_REMIND_HOUR, _REMIND_MINUTE = _parse_hhmm(os.getenv("QUALITY_PUSH_REMIND", ""), (15, 0))

stop_flag = asyncio.Event()


async def _push_today_tasks() -> None:
    """早间推送：今日出报任务（含待复核）汇总；填报中的任务另发填报卡片。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text
    from app.modules.quality.models import QualityTestTask
    from app.modules.quality.repository import (
        list_test_results,
        list_test_tasks,
        list_test_tasks_by_report_date,
    )

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    from app.modules.quality.feishu.fill_service import _task_doc_file_nos

    async with async_session_factory() as db:
        tasks = await list_test_tasks_by_report_date(db, today)
        lines: list[str] = []
        pending: list[tuple[QualityTestTask, list]] = []
        for t in tasks:
            rows = await list_test_results(db, t.id)
            filled = sum(1 for r in rows if r.is_pass is not None)
            status_label = {
                "in_progress": "填报中",
                "pending_review": "待复核",
                "completed": "已完成",
            }.get(t.status, t.status)
            file_nos = await _task_doc_file_nos(db, t)
            sop_suffix = f"｜标准文件：{'、'.join(file_nos)}" if file_nos else ""
            lines.append(
                f"- {t.product_name} 批号 {t.batch_number}（{t.specification or '-'}）"
                f"｜{status_label} {filled}/{len(rows)}{sop_suffix}"
            )
            if t.status == "in_progress":
                pending.append((t, rows))
        # 待复核任务（不限出报日期）：堆积提醒专员进系统审核
        review_items, _ = await list_test_tasks(
            db, product_name=None, status="pending_review", page=1, page_size=200
        )
        review_lines = [
            f"- {t.product_name} 批号 {t.batch_number}" + (
                f"（出报日期 {t.report_date}）" if t.report_date else ""
            )
            for t in review_items
        ]
    if not lines and not review_lines:
        return
    blocks: list[str] = []
    if lines:
        blocks.append(f"📅 今日出报任务（{today}）：\n" + "\n".join(lines))
    if review_lines:
        blocks.append(f"🔍 待复核任务（{len(review_lines)} 项，请专员进系统审核）：\n" + "\n".join(review_lines))
    text = "\n\n".join(blocks)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        await send_chat_text(chat_id, text)
    # 填报中的任务：与「出报日期=今天」的即时推送一致，下发提醒+填报卡片
    from app.modules.quality.feishu.fill_service import push_task_reminder

    for t, rows in pending:
        await push_task_reminder(t, rows)


async def _push_afternoon_reminder() -> None:
    """午后催办：今日出报但仍未完成（填报中/待复核）的任务再提醒一次。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text
    from app.modules.quality.repository import (
        list_test_results,
        list_test_tasks_by_report_date,
    )

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    from app.modules.quality.feishu.fill_service import _task_doc_file_nos

    async with async_session_factory() as db:
        tasks = await list_test_tasks_by_report_date(db, today)
        lines: list[str] = []
        for t in tasks:
            if t.status == "completed":
                continue
            rows = await list_test_results(db, t.id)
            filled = sum(1 for r in rows if r.is_pass is not None)
            status_label = {"in_progress": "填报中", "pending_review": "待复核"}.get(t.status, t.status)
            file_nos = await _task_doc_file_nos(db, t)
            sop_suffix = f"｜标准文件：{'、'.join(file_nos)}" if file_nos else ""
            lines.append(
                f"- {t.product_name} 批号 {t.batch_number}｜{status_label} {filled}/{len(rows)}{sop_suffix}"
            )
    if not lines:
        return
    text = f"⏰ 出报催办（{today}）：以下任务尚未完成，请抓紧处理\n" + "\n".join(lines)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        await send_chat_text(chat_id, text)


async def daily_report_push_loop() -> None:
    """每日定时推送（08:05 早报 + 15:00 催办，各每天一次；停止由 stop_flag 控制）。"""
    pushed_morning: set[str] = set()
    pushed_afternoon: set[str] = set()
    while not stop_flag.is_set():
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if (
                now.hour == _PUSH_HOUR
                and now.minute == _PUSH_MINUTE
                and today not in pushed_morning
            ):
                pushed_morning.add(today)
                await _push_today_tasks()
            if (
                now.hour == _REMIND_HOUR
                and now.minute == _REMIND_MINUTE
                and today not in pushed_afternoon
            ):
                pushed_afternoon.add(today)
                await _push_afternoon_reminder()
            await asyncio.sleep(20)
        except Exception:
            logger.exception("出报日期每日推送失败")
            await asyncio.sleep(60)
