"""出报日期当日机器人任务推送：每天定时把当天需出报的检验任务推送到配置的群。

由 app/main.py 按 safety 调度先例最小挂载（模块级 loop + stop_flag）。
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 每天推送时间（服务器本地时区）
_PUSH_HOUR, _PUSH_MINUTE = 8, 5

stop_flag = asyncio.Event()


async def _push_today_tasks() -> None:
    """推送 report_date == 今日 且未作废的任务（汇总文本；填报中的任务另发填报卡片）。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text
    from app.modules.quality.models import QualityTestTask
    from app.modules.quality.repository import (
        list_test_results,
        list_test_tasks_by_report_date,
    )

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    today = datetime.now().strftime("%Y-%m-%d")
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
            lines.append(
                f"- {t.product_name} 批号 {t.batch_number}（{t.specification or '-'}）"
                f"｜{status_label} {filled}/{len(rows)}"
            )
            if t.status == "in_progress":
                pending.append((t, rows))
    if not lines:
        return
    text = f"📅 今日出报任务（{today}）：\n" + "\n".join(lines)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        await send_chat_text(chat_id, text)
    # 填报中的任务：与「出报日期=今天」的即时推送一致，下发提醒+填报卡片
    from app.modules.quality.feishu.fill_service import push_task_reminder

    for t, rows in pending:
        await push_task_reminder(t, rows)


async def daily_report_push_loop() -> None:
    """每日定时推送出报任务（每天一次；停止由 stop_flag 控制）。"""
    pushed_dates: set[str] = set()
    while not stop_flag.is_set():
        try:
            now = datetime.now()
            if (
                now.hour == _PUSH_HOUR
                and now.minute == _PUSH_MINUTE
                and now.strftime("%Y-%m-%d") not in pushed_dates
            ):
                pushed_dates.add(now.strftime("%Y-%m-%d"))
                await _push_today_tasks()
            await asyncio.sleep(20)
        except Exception:
            logger.exception("出报日期每日推送失败")
            await asyncio.sleep(60)
