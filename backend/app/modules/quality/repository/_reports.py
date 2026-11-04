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
    db: AsyncSession, start: datetime, end: datetime, product_name: str | None = None
) -> list[ReportRecord]:
    """时间段内的报告单（月度汇总用），按创建时间升序；可按产品名模糊过滤。"""
    stmt = select(ReportRecord).where(
        ReportRecord.created_at >= start,
        ReportRecord.created_at < end,
        ReportRecord.is_deleted == False,  # noqa: E712
    )
    if product_name:
        stmt = stmt.where(ReportRecord.product_name.ilike(f"%{product_name}%"))
    return list((await db.execute(stmt.order_by(ReportRecord.created_at))).scalars())


async def count_report_records_since(
    db: AsyncSession, since: datetime
) -> int:
    """统计某时间点之后生成的报告单数（流水号用）。

    注意：**含软删行**——GMP 要求流水号作废不复用；若只数未删行，
    将来一旦有报告单被软删，当日序号会重算回已用过的号并撞唯一索引。
    """
    stmt = select(func.count()).where(
        ReportRecord.created_at >= since,
    )
    return int((await db.execute(stmt)).scalar_one())


async def list_report_records_by_date(
    db: AsyncSession, day: str, product_name: str | None = None
) -> list[ReportRecord]:
    """某日生成的报告单（流水号汇总：流水号+产品+批号，按北京时间计日）；可按产品名模糊过滤。"""
    start = datetime.fromisoformat(day).replace(tzinfo=APP_TZ)
    end = start + timedelta(days=1)
    stmt = select(ReportRecord).where(
        ReportRecord.created_at >= start,
        ReportRecord.created_at < end,
        ReportRecord.is_deleted == False,  # noqa: E712
    )
    if product_name:
        stmt = stmt.where(ReportRecord.product_name.ilike(f"%{product_name}%"))
    return list((await db.execute(stmt.order_by(ReportRecord.created_at))).scalars())


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
    audit_status: str | None = None,
) -> tuple[list[ReportRecord], int]:
    """分页查询报告单列表。"""
    stmt = select(ReportRecord).where(
        ReportRecord.is_deleted == False  # noqa: E712
    )
    if product_name:
        stmt = stmt.where(ReportRecord.product_name.ilike(f"%{product_name}%"))
    if batch_number:
        stmt = stmt.where(ReportRecord.batch_number.ilike(f"%{batch_number}%"))
    if audit_status:
        stmt = stmt.where(ReportRecord.audit_status == audit_status)

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


async def list_report_records_by_task(db: AsyncSession, task_id: uuid.UUID) -> list[ReportRecord]:
    """某任务已生成的报告单（按创建时间升序）。"""
    stmt = select(ReportRecord).where(
        ReportRecord.test_task_id == task_id,
        ReportRecord.is_deleted == False,  # noqa: E712
    ).order_by(ReportRecord.created_at)
    return list((await db.execute(stmt)).scalars())


async def update_report_audit(
    db: AsyncSession,
    report_id: uuid.UUID,
    audit_status: str,
    audited_by: uuid.UUID,
    comment: str | None = None,
) -> ReportRecord | None:
    """报告单审核：pending → approved / rejected（审核人+时间+备注）。"""
    stmt = select(ReportRecord).where(
        ReportRecord.id == report_id,
        ReportRecord.is_deleted == False,  # noqa: E712
    )
    report = (await db.execute(stmt)).scalar_one_or_none()
    if not report:
        return None
    if report.audit_status != "pending":
        # 状态机单向：已通过/已退回的报告单不可再审核（退回后由统计员重新出报新报告单）
        return None
    report.audit_status = audit_status
    report.audited_by = audited_by
    report.audited_at = datetime.now(APP_TZ)
    report.audit_comment = comment
    await db.flush()
    stmt = select(ReportRecord).where(ReportRecord.id == report_id)
    return (await db.execute(stmt)).scalar_one()
