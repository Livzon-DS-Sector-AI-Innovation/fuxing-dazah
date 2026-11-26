"""离职合同台账 · 查询与行装配（P3）。

按离职记录逐行装配需求第二章四块内容（人员/合同/离职信息/手续状态）：
- 合同信息按工号从 hr.labor_contracts 实时聚合（不落快照，避免两处维护与回写过期）；
  历史离职人员多不在合同表（P1 迁移只覆盖在职），此时退回离职记录自带的合同起止日期
- 终止方式的 SQL 判定表达式与 departure_service.derive_termination_type 同序（测试保证
  一致），人工更正值优先
- 手续状态：流程单号/证明开具送达以离职办结单为准（有则取），否则取人工补录与台账签字字段

规则常量与流程衔接函数见 departure_service.py。
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.departure_service import (
    CASE_CANCELED,
    CERT_LABELS,
    EMPLOYER_TYPES,
    EXPIRY_TYPES,
    RESIGN_TYPES,
    RETIRE_TYPES,
    TERMINATION_EMPLOYER,
    TERMINATION_EXPIRY,
    TERMINATION_LABELS,
    TERMINATION_NONE,
    TERMINATION_OTHER,
    TERMINATION_RESIGN,
    TERMINATION_RETIRE,
    TERMINATION_TRANSFER,
    TRANSFER_TYPES,
    chunks,
    derive_certificate_status,
    term_from_dates,
    term_label,
)
from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.models import DepartureRecord

_ORDER_BY = (
    DepartureRecord.offboarding_date.desc().nulls_last(),
    DepartureRecord.created_at.desc(),
)
_ASSEMBLE_CHUNK = 200

STATEMENT_HEADERS = [
    "序号", "姓名", "工号", "部门", "岗位", "离职日期", "离职类型",
    "合同签订次数", "历次合同起止", "最后一份期限", "合同终止/解除方式", "合同终止日期",
    "审批依据", "离职流程单号", "离职证明", "合同原件", "扫描件归档",
]


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _dt(value) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M") if value else None


# ═══════════════════════════════════════════════════════════════
# 查询：部门 / 离职时间 / 终止方式 / 关键字 筛选 + 分页 + 导出
# ═══════════════════════════════════════════════════════════════

def _latest_contract_subquery():
    """每工号签订次数最高的一份合同（未删除）。"""
    rn = func.row_number().over(
        partition_by=LaborContract.employee_number,
        order_by=LaborContract.seq_no.desc(),
    ).label("rn")
    return (
        select(
            LaborContract.employee_number.label("employee_number"),
            rn,
            LaborContract.end_date.label("end_date"),
        )
        .where(LaborContract.is_deleted.is_(False))
        .subquery()
    )


def _termination_type_expr(latest) -> ColumnElement:
    """终止方式的 SQL 表达式（人工更正优先），判定顺序同 derive_termination_type。"""
    effective_end = func.coalesce(latest.c.end_date, DepartureRecord.contract_end_date)
    off_type = DepartureRecord.offboarding_type
    leave = DepartureRecord.offboarding_date
    no_contract = and_(
        latest.c.employee_number.is_(None),
        DepartureRecord.contract_end_date.is_(None),
        DepartureRecord.contract_start_date.is_(None),
    )
    return func.coalesce(
        DepartureRecord.contract_termination_type,
        case(
            (no_contract, TERMINATION_NONE),
            (off_type.in_(RETIRE_TYPES), TERMINATION_RETIRE),
            (off_type.in_(EXPIRY_TYPES), TERMINATION_EXPIRY),
            (
                and_(effective_end.is_not(None), leave.is_not(None), leave >= effective_end),
                TERMINATION_EXPIRY,
            ),
            (off_type.in_(RESIGN_TYPES), TERMINATION_RESIGN),
            (off_type.in_(EMPLOYER_TYPES), TERMINATION_EMPLOYER),
            (off_type.in_(TRANSFER_TYPES), TERMINATION_TRANSFER),
            else_=TERMINATION_OTHER,
        ),
    )


def _filtered_stmt(
    *, department: str | None, date_from: date | None, date_to: date | None,
    termination_type: str | None, keyword: str | None,
):
    latest = _latest_contract_subquery()
    termination = _termination_type_expr(latest)
    stmt = (
        select(DepartureRecord, termination.label("termination_type"))
        .outerjoin(
            latest,
            and_(
                latest.c.employee_number == DepartureRecord.employee_number,
                latest.c.rn == 1,
            ),
        )
        .where(DepartureRecord.is_deleted.is_(False))
    )
    if department:
        stmt = stmt.where(DepartureRecord.department == department)
    if date_from:
        stmt = stmt.where(DepartureRecord.offboarding_date >= date_from)
    if date_to:
        stmt = stmt.where(DepartureRecord.offboarding_date <= date_to)
    if termination_type:
        stmt = stmt.where(termination == termination_type)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(DepartureRecord.name.ilike(kw), DepartureRecord.employee_number.ilike(kw))
        )
    return stmt


async def page_rows(
    db: AsyncSession, *, department: str | None = None, date_from: date | None = None,
    date_to: date | None = None, termination_type: str | None = None,
    keyword: str | None = None, offset: int = 0, limit: int = 20,
) -> tuple[int, list[dict[str, Any]]]:
    """离职合同台账分页行（四块内容装配完毕）。"""
    stmt = _filtered_stmt(
        department=department, date_from=date_from, date_to=date_to,
        termination_type=termination_type, keyword=keyword,
    )
    total = int((await db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )).scalar_one())
    rows = (await db.execute(stmt.order_by(*_ORDER_BY).offset(offset).limit(limit))).all()
    return total, await assemble_rows(db, [(d, t) for d, t in rows])


async def export_rows(db: AsyncSession, **filters) -> list[list[str]]:
    """「离职人员合同情况说明」数据行（与列表同筛选口径，不分页）。"""
    stmt = _filtered_stmt(
        department=filters.get("department"), date_from=filters.get("date_from"),
        date_to=filters.get("date_to"), termination_type=filters.get("termination_type"),
        keyword=filters.get("keyword"),
    ).order_by(*_ORDER_BY)
    rows = (await db.execute(stmt)).all()
    lines: list[list[str]] = []
    for start in range(0, len(rows), _ASSEMBLE_CHUNK):
        views = await assemble_rows(db, [(d, t) for d, t in rows[start:start + _ASSEMBLE_CHUNK]])
        lines.extend(statement_line(i, v) for i, v in enumerate(views, start=start + 1))
    return lines


# ═══════════════════════════════════════════════════════════════
# 行装配：人员 / 合同 / 离职信息 / 手续状态
# ═══════════════════════════════════════════════════════════════

def _contract_brief(c: LaborContract) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "seq_no": c.seq_no,
        "seq_label": c.seq_label,
        "term_label": c.term_label,
        "start_date": _iso(c.start_date),
        "end_date": _iso(c.end_date),
        "status": c.status,
        "status_label": c.status_label,
        "terminated_reason": c.terminated_reason,
        "archive_status": c.archive_status,
        "archive_status_label": LaborContract.ARCHIVE_LABELS.get(c.archive_status, c.archive_status),
    }


def build_view(
    departure: DepartureRecord, termination_type: str, contracts: list[LaborContract], case,
) -> dict[str, Any]:
    """单条离职记录的合同台账视图（纯函数，不查库）。"""
    last = contracts[-1] if contracts else None
    fallback_start = departure.contract_start_date
    fallback_end = departure.contract_end_date
    contract_end = last.end_date if last else fallback_end
    has_contract = bool(contracts) or fallback_start is not None or fallback_end is not None

    if termination_type == TERMINATION_EXPIRY:
        termination_date: date | None = contract_end  # 到期终止以合同到期日为准
    elif termination_type == TERMINATION_NONE:
        termination_date = None
    else:
        termination_date = departure.offboarding_date

    term_type_last = term_years_last = term_label_last = None
    periods: list[str] = []
    approval_refs: list[str] = []
    if last is not None:
        term_type_last, term_years_last, term_label_last = last.term_type, last.term_years, last.term_label
        periods = [f"第{c.seq_no}次 {c.start_date}~{c.end_date or '无固定'}" for c in contracts]
        for c in contracts:
            if c.approval_instance_code:
                approval_refs.append(f"第{c.seq_no}份续签审批 {c.approval_instance_code}")
            elif c.dept_decision == LaborContract.DECISION_DISAGREE:
                decided = f" · {_dt(c.dept_decision_at)}" if c.dept_decision_at else ""
                approval_refs.append(f"部门不同意续签（{c.dept_decision_by or '-'}{decided}）")
    elif fallback_start is not None:
        term_type_last, term_years_last = term_from_dates(fallback_start, fallback_end)
        term_label_last = term_label(term_type_last, term_years_last)
        periods = [f"{fallback_start}~{fallback_end or '无固定'}"]

    resignation_instance = getattr(case, "resignation_instance_code", None) if case is not None else None
    if resignation_instance:
        approval_refs.insert(0, f"离职审批 {resignation_instance}")
    if departure.contract_approval_ref:
        approval_refs.insert(0, departure.contract_approval_ref)

    case_no = getattr(case, "case_no", None) if case is not None else None
    certificate_status = derive_certificate_status(departure, case)
    archive_status = last.archive_status if last else LaborContract.ARCHIVE_UNARCHIVED
    return {
        # 人员信息
        "id": str(departure.id),
        "name": departure.name,
        "employee_number": departure.employee_number,
        "department": departure.department,
        "position": departure.position,
        "employee_category": departure.employee_category,
        # 合同信息
        "has_contract_rows": bool(contracts),
        "has_contract": has_contract,
        "contract_count": len(contracts) if contracts else (1 if has_contract else 0),
        "contract_count_known": bool(contracts),
        "contracts": [_contract_brief(c) for c in contracts],
        "contract_periods_text": "；".join(periods),
        "contract_start_date": _iso(contracts[0].start_date if contracts else fallback_start),
        "contract_end_date": _iso(contract_end),
        "term_type_last": term_type_last,
        "term_label_last": term_label_last,
        "archive_status": archive_status,
        "archive_status_label": LaborContract.ARCHIVE_LABELS.get(archive_status, archive_status),
        # 离职信息
        "offboarding_date": _iso(departure.offboarding_date),
        "offboarding_type": departure.offboarding_type,
        "offboarding_reason": departure.offboarding_reason or [],
        "termination_type": termination_type,
        "termination_type_label": TERMINATION_LABELS.get(termination_type, termination_type),
        "termination_type_overridden": bool(departure.contract_termination_type),
        "termination_date": _iso(termination_date),
        "approval_ref": departure.contract_approval_ref,
        "approval_refs": approval_refs,
        # 手续状态
        "separation_process_no": case_no or departure.separation_process_no,
        "process_no_source": "case" if case_no else ("manual" if departure.separation_process_no else None),
        "certificate_status": certificate_status,
        "certificate_status_label": CERT_LABELS[certificate_status],
        "contract_original_status": departure.contract_original_status,
        "contract_original_status_label": DepartureRecord.ORIGINAL_STATUS_LABELS.get(
            departure.contract_original_status, departure.contract_original_status,
        ),
    }


def statement_line(index: int, v: dict[str, Any]) -> list[str]:
    """「离职人员合同情况说明」一行。"""
    if v["contract_count_known"]:
        count = str(v["contract_count"])
    else:
        count = "1（离职台账登记）" if v["contract_count"] else "0"
    return [
        str(index), v["name"], v["employee_number"] or "", v["department"], v["position"],
        v["offboarding_date"] or "", v["offboarding_type"], count,
        v["contract_periods_text"], v["term_label_last"] or "", v["termination_type_label"],
        v["termination_date"] or "", "；".join(v["approval_refs"]),
        v["separation_process_no"] or "", v["certificate_status_label"],
        v["contract_original_status_label"], v["archive_status_label"],
    ]


async def _map_cases(db: AsyncSession, departure_ids: list[UUID]) -> dict[UUID, Any]:
    """离职记录 → 最新一张未取消的离职办结单（按离职记录 ID 批量）。"""
    from app.modules.hr.offboarding.models import OffboardingCase

    result: dict[UUID, Any] = {}
    for chunk in chunks(departure_ids):
        rows = (await db.execute(
            select(OffboardingCase).where(
                OffboardingCase.departure_record_id.in_(chunk),
                OffboardingCase.is_deleted.is_(False),
                OffboardingCase.status != CASE_CANCELED,
            ).order_by(OffboardingCase.created_at.desc())
        )).scalars().all()
        for offboarding_case in rows:
            if offboarding_case.departure_record_id is not None:
                result.setdefault(offboarding_case.departure_record_id, offboarding_case)
    return result


async def assemble_rows(
    db: AsyncSession, pairs: list[tuple[DepartureRecord, str]],
) -> list[dict[str, Any]]:
    """批量装配（合同、办结单分块 IN 查询，免 N+1）。"""
    numbers = list({d.employee_number for d, _ in pairs if d.employee_number})
    contracts_map: dict[str, list[LaborContract]] = {}
    for chunk in chunks(numbers):
        contracts_map.update(await repo.map_contracts_for_numbers(db, chunk))
    cases_map = await _map_cases(db, [d.id for d, _ in pairs])
    return [
        build_view(d, t, contracts_map.get(d.employee_number or "", []), cases_map.get(d.id))
        for d, t in pairs
    ]
