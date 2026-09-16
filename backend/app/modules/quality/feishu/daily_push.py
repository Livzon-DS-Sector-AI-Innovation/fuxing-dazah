"""出报日期当日机器人任务推送：内容构建与发送（定时触发由 quality/scheduled.py 注册到平台统一调度引擎）。

- 早报：今日出报任务 + 待复核任务列表（填报中的任务另发填报卡片）+ 标准文件到期提醒
- 午后催办：今日出报但尚未完成/复核的任务再提醒一次
"""

import logging
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)


def _parse_effective_date(s: str | None) -> str | None:
    """标准文档生效日期归一化：2026年03月05日 / 2026.03.05 → 2026-03-05。"""
    if not s:
        return None
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s.strip().replace(".", "-").replace("/", "-")


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
    today = datetime.now().strftime("%Y-%m-%d")
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
        # 标准文件到期提醒（30 天内）
        from app.modules.quality.repository import list_standard_documents
        from app.modules.quality.service import TestTaskService

        expiring: list[str] = []
        std_docs = await list_standard_documents(db)
        for d in std_docs:
            eff = _parse_effective_date(d.effective_date)
            if not eff or not d.valid_years:
                continue
            expiry = TestTaskService._calc_expiry(eff, d.valid_years)
            if not expiry:
                continue
            days_left = (date.fromisoformat(expiry) - date.today()).days
            if 0 <= days_left <= 30:
                expiring.append(
                    f"- {d.file_no}（{d.product_name}）{expiry} 到期（剩 {days_left} 天）"
                )
    if not lines and not review_lines and not expiring:
        return
    blocks: list[str] = []
    if lines:
        blocks.append(f"📅 今日出报任务（{today}）：\n" + "\n".join(lines))
    if review_lines:
        blocks.append(f"🔍 待复核任务（{len(review_lines)} 项，请专员进系统审核）：\n" + "\n".join(review_lines))
    if expiring:
        blocks.append("⏳ 标准文件到期提醒：\n" + "\n".join(expiring))
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
        await send_chat_text(chat_id, text)


