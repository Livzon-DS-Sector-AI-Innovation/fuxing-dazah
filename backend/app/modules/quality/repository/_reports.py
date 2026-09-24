"""Quality 模块数据读写。只负责查询与持久化，不做业务判断。"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.modules.quality.models import (
    ReportRecord,
)

# ─── 报告单 ───


def is_serial_unique_violation(exc: Exception) -> bool:
    """判断是否为流水号唯一索引冲突（并发生成 COA 撞号，需要重算流水号重试）。"""
    return isinstance(exc, IntegrityError) and "uq_quality_report_record_serial" in str(exc.orig)


async def create_report_record(
    db: AsyncSession,
    template_path: str,
    product_name: str,
    batch_number: str,
    inspection_record_id: uuid.UUID | None = None,
    test_task_id: uuid.UUID | None = None,
    file_path: str | None = None,
    file_size: int | None = None,
    serial_no: str | None = None,
) -> ReportRecord:
    """创建报告单记录（inspection_record_id 与 test_task_id 二选一，P2 任务驱动 COA）。"""
    report = ReportRecord(
        inspection_record_id=inspection_record_id,
        test_task_id=test_task_id,
        template_path=template_path,
        product_name=product_name,
        batch_number=batch_number,
        file_path=file_path,
        file_size=file_size,
        # 空串归一为 None："" 会进入流水号唯一索引，多条空串记录会误撞号
        serial_no=serial_no or None,
    )
    db.add(report)
    await db.flush()
    return report


async def list_report_records_between(
    db: AsyncSession, start: datetime, end: datetime
) -> list[ReportRecord]:
    """时间段内的报告单（月度汇总用），按创建时间升序。"""
    stmt = select(ReportRecord).where(
        ReportRecord.created_at >= start,
        ReportRecord.created_at < end,
        ReportRecord.is_deleted == False,  # noqa: E712
    ).order_by(ReportRecord.created_at)
    return list((await db.execute(stmt)).scalars())


async def count_report_records_since(
    db: AsyncSession, since: datetime
) -> int:
    """统计某时间点之后生成的报告单数（流水号用）。"""
    stmt = select(func.count()).where(
        ReportRecord.is_deleted == False,  # noqa: E712
        ReportRecord.created_at >= since,
    )
    return int((await db.execute(stmt)).scalar_one())


async def list_report_records_by_date(
    db: AsyncSession, day: str
) -> list[ReportRecord]:
    """某日生成的报告单（流水号汇总：流水号+产品+批号，按北京时间计日）。"""
    start = datetime.fromisoformat(day).replace(tzinfo=APP_TZ)
    end = start + timedelta(days=1)
    stmt = select(ReportRecord).where(
        ReportRecord.created_at >= start,
        ReportRecord.created_at < end,
        ReportRecord.is_deleted == False,  # noqa: E712
    ).order_by(ReportRecord.created_at)
    return list((await db.execute(stmt)).scalars())


async def get_latest_report_record_by_task(
    db: AsyncSession, task_id: uuid.UUID
) -> ReportRecord | None:
    """任务最近一次生成的报告单记录（进度查询「已出报时间」用）。"""
    stmt = select(ReportRecord).where(
        ReportRecord.test_task_id == task_id,
        ReportRecord.is_deleted == False,  # noqa: E712
    ).order_by(ReportRecord.created_at.desc())
    return (await db.execute(stmt)).scalars().first()


async def get_report_record(
    db: AsyncSession, report_id: uuid.UUID
) -> ReportRecord | None:
    """按 ID 查询报告单记录。"""
    stmt = select(ReportRecord).where(
        ReportRecord.id == report_id,
        ReportRecord.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_report_records(
    db: AsyncSession,
    product_name: str | None = None,
    batch_number: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ReportRecord], int]:
    """分页查询报告单列表。"""
    stmt = select(ReportRecord).where(
        ReportRecord.is_deleted == False  # noqa: E712
    )
    if product_name:
        stmt = stmt.where(ReportRecord.product_name.ilike(f"%{product_name}%"))
    if batch_number:
        stmt = stmt.where(ReportRecord.batch_number.ilike(f"%{batch_number}%"))

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = (
        stmt.order_by(ReportRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars())
    return items, total
