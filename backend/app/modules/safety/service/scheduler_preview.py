"""定时任务报告预览（只读生成，不推送）。

仅 report_type=true 的任务开放；预览调用与真实任务相同的报告生成逻辑，
但 push=False / 只构建 Markdown，绝不调用 send_group_card。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.service.scheduler_config import _jobs_index

logger = logging.getLogger(__name__)

SUPPORTED_PREVIEW_JOBS: frozenset[str] = frozenset({
    "特殊作业日报",
    "特殊作业日报17点",
    "作业票审核",
    "消防报警日报",
    "中控报警日报",
    "危化品库存周报",
    "危化品库存日报",
    "隐患督办通报",
})


def _parse_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    return date.today()


async def _preview_special_op(db: AsyncSession, job_name: str, target: date) -> dict[str, Any]:
    from app.modules.safety.service.special_operation_daily_report import (
        SpecialOperationDailyReportService,
    )

    service = SpecialOperationDailyReportService(db)
    await service.sync_from_bitable()
    mode = "afternoon" if job_name.endswith("17点") else "today"
    result = await service.generate_and_push(
        target_date=target, mode=mode, target_chats=None, push=False,
    )
    return {
        "job_name": job_name,
        "date": target.isoformat(),
        "title": f"特殊作业日报 - {target.isoformat()}",
        "markdown": result.markdown_report,
    }


async def _preview_workticket(db: AsyncSession, target: date) -> dict[str, Any]:
    from app.modules.safety.workticket_review.service import WorkTicketReviewService

    service = WorkTicketReviewService(db, chat_id=None)
    result = await service.run_review(target, push=False)
    return {
        "job_name": "作业票审核",
        "date": target.isoformat(),
        "title": f"作业票审核日报 - {target.isoformat()}",
        "markdown": result.get("markdown_report", ""),
    }


async def _preview_fire_alarm(db: AsyncSession, target: date) -> dict[str, Any]:
    from app.modules.safety.service.fire_alarm.service import FireAlarmService

    service = FireAlarmService(db)
    result = await service.generate_daily_report(
        target_date=target, push=False, channel="web", rolling=False,
    )
    return {
        "job_name": "消防报警日报",
        "date": target.isoformat(),
        "title": f"消防报警日报 - {target.isoformat()}",
        "markdown": result.markdown_report,
    }


async def _preview_central_alarm(db: AsyncSession, target: date) -> dict[str, Any]:
    from app.modules.safety.service.central_alarm.service import CentralAlarmService

    service = CentralAlarmService(db)
    result = await service.generate_daily_report(
        target_date=target, push=False, channel="web", rolling=False,
    )
    return {
        "job_name": "中控报警日报",
        "date": target.isoformat(),
        "title": f"中控报警日报 - {target.isoformat()}",
        "markdown": result.markdown_report,
    }


async def _preview_chemical_weekly(db: AsyncSession, target: date) -> dict[str, Any]:
    from app.modules.safety.chemical_inventory.weekly_report import (
        _format_report,
        build_weekly_report,
        generate_ai_summary,
    )

    report = await build_weekly_report(db, target)
    ai_summary = await generate_ai_summary(report)
    report["ai_summary"] = ai_summary
    content = _format_report(report, ai_summary)
    return {
        "job_name": "危化品库存周报",
        "date": target.isoformat(),
        "title": f"危化品库存周报 - {target.isoformat()}",
        "markdown": content,
    }


async def _preview_chemical_daily(db: AsyncSession, target: date) -> dict[str, Any]:
    from app.modules.safety.chemical_inventory.daily_job import (
        build_daily_summary,
        run_scheduled_daily_update,
    )

    result = await run_scheduled_daily_update()
    content = build_daily_summary(result)
    return {
        "job_name": "危化品库存日报",
        "date": target.isoformat(),
        "title": f"危化品库存每日更新总结 - {target.isoformat()}",
        "markdown": content,
    }


async def _preview_supervision_bulletin(db: AsyncSession) -> dict[str, Any]:
    """隐患督办通报预览（直读多维表格）。"""
    from app.modules.safety.service.hazard_direct.bulletin import build_bulletin

    content, _stats = await build_bulletin()
    return {
        "job_name": "隐患督办通报",
        "date": date.today().isoformat(),
        "title": "隐患督办通报",
        "markdown": content,
    }


async def preview_task_report(db: AsyncSession, job_name: str, date_str: str | None = None) -> dict[str, Any]:
    """只读生成任务报告 Markdown；任务不存在或非报告类返回 400 语义（抛 ValueError）。"""
    if job_name not in _jobs_index():
        raise ValueError("未知定时任务")
    if job_name not in SUPPORTED_PREVIEW_JOBS:
        raise ValueError("该任务暂不支持预览")
    target = _parse_date(date_str)

    if job_name in ("特殊作业日报", "特殊作业日报17点"):
        return await _preview_special_op(db, job_name, target)
    if job_name == "作业票审核":
        return await _preview_workticket(db, target)
    if job_name == "消防报警日报":
        return await _preview_fire_alarm(db, target)
    if job_name == "中控报警日报":
        return await _preview_central_alarm(db, target)
    if job_name == "危化品库存周报":
        return await _preview_chemical_weekly(db, target)
    if job_name == "危化品库存日报":
        return await _preview_chemical_daily(db, target)
    if job_name == "隐患督办通报":
        return await _preview_supervision_bulletin(db)
    raise ValueError("该任务暂不支持预览")
