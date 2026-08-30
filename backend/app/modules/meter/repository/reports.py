"""检测报告数据访问与名称/编号匹配查询。"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter.models import (
    CalibrationReport,
    GasDetectorRecord,
    InstrumentRecord,
)
from app.modules.meter.repository._utils import _escape_like


async def create_report(db: AsyncSession, data: dict[str, Any]) -> CalibrationReport:
    stmt = pg_insert(CalibrationReport).values(**data).returning(CalibrationReport)
    result = await db.execute(stmt)
    await db.flush()
    return result.scalar_one()


async def get_report_by_id(db: AsyncSession, report_id: UUID) -> CalibrationReport | None:
    stmt = select(CalibrationReport).where(
        CalibrationReport.id == report_id,
        CalibrationReport.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_reports_by_instrument(
    db: AsyncSession, instrument_id: UUID
) -> list[CalibrationReport]:
    # NULLS LAST：无日期报告不应排在有日期报告之前（PG 对 DESC 默认 NULLS FIRST）
    stmt = select(CalibrationReport).where(
        CalibrationReport.instrument_id == instrument_id,
        CalibrationReport.is_deleted == False,  # noqa: E712
    ).order_by(
        CalibrationReport.report_date.desc().nullslast(),
        CalibrationReport.created_at.desc(),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_reports_by_gas_detector(
    db: AsyncSession, gas_detector_id: UUID
) -> list[CalibrationReport]:
    stmt = select(CalibrationReport).where(
        CalibrationReport.gas_detector_id == gas_detector_id,
        CalibrationReport.is_deleted == False,  # noqa: E712
    ).order_by(
        CalibrationReport.report_date.desc().nullslast(),
        CalibrationReport.created_at.desc(),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def soft_delete_report(db: AsyncSession, report_id: UUID) -> bool:
    stmt = (
        sa_update(CalibrationReport)
        .where(CalibrationReport.id == report_id, CalibrationReport.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0  # type: ignore[no-any-return,attr-defined]


async def update_report_date(db: AsyncSession, report_id: UUID, report_date: date) -> None:
    """更新检测报告的 report_date 字段。"""
    stmt = (
        sa_update(CalibrationReport)
        .where(CalibrationReport.id == report_id)
        .values(report_date=report_date)
    )
    await db.execute(stmt)
    await db.flush()


async def update_report_certificate_no(
    db: AsyncSession, report_id: UUID, certificate_no: str | None
) -> None:
    """手动修改检测报告的证书编号（None = 清除编号）。"""
    stmt = (
        sa_update(CalibrationReport)
        .where(CalibrationReport.id == report_id, CalibrationReport.is_deleted == False)  # noqa: E712
        .values(certificate_no=certificate_no)
    )
    await db.execute(stmt)
    await db.flush()


async def find_existing_certificate_nos(db: AsyncSession, nos: list[str]) -> set[str]:
    """查未删除报告中已存在的证书编号集合。"""
    stmt = select(CalibrationReport.certificate_no).where(
        CalibrationReport.certificate_no.in_(nos),
        CalibrationReport.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


async def search_instruments_by_name(
    db: AsyncSession, name: str, limit: int = 10
) -> list[InstrumentRecord]:
    """按名称模糊搜索标准计量器具候选。"""
    stmt = (
        select(InstrumentRecord)
        .where(
            InstrumentRecord.instrument_name.ilike(f"%{_escape_like(name)}%", escape="\\"),
            InstrumentRecord.is_deleted == False,  # noqa: E712
        )
        .order_by(InstrumentRecord.sort_order)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def search_gas_detectors_by_name(
    db: AsyncSession, name: str, limit: int = 10
) -> list[GasDetectorRecord]:
    """按名称模糊搜索探测器候选。"""
    stmt = (
        select(GasDetectorRecord)
        .where(
            GasDetectorRecord.instrument_name.ilike(f"%{_escape_like(name)}%", escape="\\"),
            GasDetectorRecord.is_deleted == False,  # noqa: E712
        )
        .order_by(GasDetectorRecord.sort_order)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ═══════════════════════════════════════════
# 文件匹配查询
# ═══════════════════════════════════════════


async def find_instrument_by_name_and_serial(
    db: AsyncSession, name: str, serial: str
) -> InstrumentRecord | None:
    """按器具名称（模糊）+ 器具编号精确匹配。

    编号非唯一（台账允许重复），命中多条时取最新创建的一条，保证结果确定。
    """
    stmt = select(InstrumentRecord).where(
        InstrumentRecord.instrument_name.ilike(f"%{_escape_like(name)}%", escape="\\"),
        InstrumentRecord.serial_number == serial,
        InstrumentRecord.is_deleted == False,  # noqa: E712
    ).order_by(InstrumentRecord.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def find_gas_detector_by_name_and_product(
    db: AsyncSession, name: str, product: str
) -> GasDetectorRecord | None:
    """按器具名称（模糊）+ 产品编号精确匹配。

    编号非唯一（台账允许重复），命中多条时取最新创建的一条，保证结果确定。
    """
    stmt = select(GasDetectorRecord).where(
        GasDetectorRecord.instrument_name.ilike(f"%{_escape_like(name)}%", escape="\\"),
        GasDetectorRecord.product_number == product,
        GasDetectorRecord.is_deleted == False,  # noqa: E712
    ).order_by(GasDetectorRecord.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ═══════════════════════════════════════════
# 部门管理
# ═══════════════════════════════════════════
