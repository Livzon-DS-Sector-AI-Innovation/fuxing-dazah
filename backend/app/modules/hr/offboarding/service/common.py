"""离职管理服务层共用件：会话内取数、通知上下文、离职台账 upsert。

service/ 按「办结单（case）→ 证明签收（certify）→ 办结联动（closing）」拆分，
本模块放三者共用的取数与台账读写；对外入口经 service/__init__.py re-export。
依赖方向单向：service → notify / approval → repository，notify 与 approval 不反向依赖 service。
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.hr.models import DepartureRecord, Employee
from app.modules.hr.offboarding import clearance, notify
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding import settings as offboarding_settings
from app.modules.hr.offboarding.models import OffboardingCase

logger = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


async def refetch(db: AsyncSession, case_id: UUID) -> OffboardingCase:
    """UPDATE 后按铁律 select 重取（flush 不回填 updated_at，直接读会触发 MissingGreenlet）。"""
    case = await repo.get_case(db, case_id)
    assert case is not None, f"办结单 {case_id} 刚更新后查询不到"
    return case


async def get_or_404(db: AsyncSession, case_id: UUID) -> OffboardingCase:
    case = await repo.get_case(db, case_id)
    if not case:
        raise NotFoundException("离职办结单", str(case_id))
    return case


async def notify_context(db: AsyncSession) -> notify.NotifyContext:
    kv = await offboarding_settings.load_offboarding_settings(db)
    return notify.NotifyContext(
        hr_copy=offboarding_settings.hr_copy_entries(kv),
        contact=offboarding_settings.contact_info(kv),
    )


async def linked_record(db: AsyncSession, case: OffboardingCase) -> DepartureRecord | None:
    """办结单关联的离职台账行：优先按 departure_record_id，兜底按工号。"""
    if case.departure_record_id:
        record = await repo.get_departure_record(db, case.departure_record_id)
        if record is not None:
            return record
    return await repo.find_departure_record(db, case.employee_number)


# ─── 清退阶段 ───

async def seed_clearance_items(db: AsyncSession, case: OffboardingCase) -> int:
    """进入清退阶段落默认清单：系统配置里的清退清单优先，没配用需求列明的清单。"""
    kv = await offboarding_settings.load_offboarding_settings(db)
    return await clearance.seed_default_items(
        db, case, items=offboarding_settings.clearance_items(kv),
    )


async def should_hold_clearance(db: AsyncSession, case: OffboardingCase) -> bool:
    """清退交接接了飞书审批、且还没到建议发起日（离职日前 2 天）→ 实例先不发起（挂起）。"""
    kv = await offboarding_settings.load_offboarding_settings(db)
    configured = offboarding_settings.stage_configured(
        kv, stage="clearance", track=case.approval_track, level=case.level,
    )
    return configured and clearance.should_defer_clearance(case)


def clearance_stage_note(case: OffboardingCase, result: Any | None) -> str | None:
    """进入清退阶段后通知里的「下一步」：挂起 / 未接飞书 / 已发起各说各话。"""
    if case.clearance_pending:
        due = clearance.clearance_due_date(case)
        return (
            f"还没到清退交接的建议发起日（{due.month}月{due.day}日，离职日前 2 天），"
            "到期后自动发起；需要提前办可在办理页手动发起"
        )
    if result is not None and getattr(result, "unconfigured", False):
        return "飞书审批定义未配置，走站内登记办结"
    return None


async def upsert_departure_record(
    db: AsyncSession,
    case: OffboardingCase,
    employee: Employee | None,
    *,
    overwrite: bool = False,
) -> DepartureRecord:
    """按工号 upsert 离职台账行（双轨并行：平台流程写台账，飞书表同步保留兜底）。

    overwrite=False（建单/编辑/开证）：只补空字段——飞书同步来的行以源表为准，
    平台不抢先改写；overwrite=True（办结）：办结结果是权威口径，回写覆盖。
    cert_sign_* 只由签收登记写，这里不碰。
    """
    record = await linked_record(db, case)
    if record is None:
        record = DepartureRecord(
            name=case.name,
            employee_number=case.employee_number,
            department=case.department,
            position=case.position or "-",
            offboarding_type=case.offboarding_type,
        )
        db.add(record)
        await db.flush()

    def put(field_name: str, value: object) -> None:
        if value in (None, "", []):
            return
        if overwrite or getattr(record, field_name) in (None, "", []):
            setattr(record, field_name, value)

    put("department", case.department)
    put("position", case.position)
    put("offboarding_date", case.offboarding_date)
    put("offboarding_type", case.offboarding_type)
    put("offboarding_reason", [case.reason] if case.reason else None)
    if employee:
        put("livo_entry_date", employee.hire_date)
        put("id_card", employee.id_card)
        put("phone", employee.phone)
        put("gender", employee.gender)
        put("education", getattr(employee, "education", None))
    if case.departure_record_id is None:
        case.departure_record_id = record.id
    return record
