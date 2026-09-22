"""出报日期当日机器人任务推送：内容构建与发送（定时触发由 quality/scheduled.py 注册到平台统一调度引擎）。

- 早报：今日出报任务 + 待复核任务列表 + 明日出报预告（填报中的任务另发填报卡片）
- 午后催办：今日出报但尚未完成/复核的任务再提醒一次
"""

import logging
from datetime import timedelta

from app.core.time import today as _app_today

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str, default: tuple[int, int]) -> tuple[int, int]:
    """解析 HH:MM 配置（如 08:05），非法/为空回退默认值。"""
    try:
        h, m = value.strip().split(":")
        return int(h), int(m)
    except Exception:
        return default


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
    today = _app_today().isoformat()
    from app.modules.quality.feishu.fill_service import (
        _frontend_task_link,
        _task_doc_file_nos,
    )

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
                f"｜{status_label} {filled}/{len(rows)}{sop_suffix}\n"
                f"  🔗 {_frontend_task_link(str(t.id))}"
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
            + f"\n  🔗 {_frontend_task_link(str(t.id))}"
            for t in review_items
        ]
        # 明日出报预告
        tomorrow = (_app_today() + timedelta(days=1)).isoformat()
        tomorrow_items = await list_test_tasks_by_report_date(db, tomorrow)
        tomorrow_lines = [
            f"- {t.product_name} 批号 {t.batch_number}｜"
            f"{'填报中' if t.status == 'in_progress' else {'pending_review': '待复核', 'completed': '已完成'}.get(t.status, t.status)}"
            for t in tomorrow_items
            if t.status != "void"
        ]
    if not lines and not review_lines and not tomorrow_lines:
        return
    blocks: list[str] = []
    if lines:
        blocks.append(f"📅 今日出报任务（{today}）：\n" + "\n".join(lines))
    if review_lines:
        blocks.append(f"🔍 待复核任务（{len(review_lines)} 项，请专员进系统审核）：\n" + "\n".join(review_lines))
    if tomorrow_lines:
        blocks.append(f"⏰ 明日出报预告（{tomorrow}）：\n" + "\n".join(tomorrow_lines))
    text = "\n\n".join(blocks)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            logger.exception("飞书早报发送失败: %s", chat_id)
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
    today = _app_today().isoformat()
    from app.modules.quality.feishu.fill_service import (
        _frontend_task_link,
        _task_doc_file_nos,
    )

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
                f"- {t.product_name} 批号 {t.batch_number}｜{status_label} {filled}/{len(rows)}{sop_suffix}\n"
                f"  🔗 {_frontend_task_link(str(t.id))}"
            )
    if not lines:
        return
    text = f"⏰ 出报催办（{today}）：以下任务尚未完成，请抓紧处理\n" + "\n".join(lines)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            logger.exception("飞书催办发送失败: %s", chat_id)


