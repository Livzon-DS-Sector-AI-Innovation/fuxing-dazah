"""离职台账查询：十类筛选 + 办理流程信息装配 + 筛选选项（方案 §3.8）。

台账 = 结果数据（hr.departure_records：飞书离职人员管理表同步 + 平台办结回写），
办理单 = 过程（hr.offboarding_cases）。两本账按工号关联：每行台账挂该工号最近一张
办结单，带出审批状态、证明开具/签收、四部门清退结算。分页在 SQL 层完成，流程信息
按页批量装配（IN 查询，免 N+1）。
"""

import logging
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, Select, String, and_, asc, cast, desc, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Subquery

from app.core.exceptions import AppException, ForbiddenException
from app.modules.hr.deps import HrAccessContext
from app.modules.hr.models import DepartureRecord
from app.modules.hr.offboarding.models import OffboardingCase, OffboardingClearanceItem
from app.modules.hr.schemas import DepartureRecordResponse, mask_sensitive_fields

logger = logging.getLogger(__name__)

APPROVAL_NONE = "none"  # 未发起离职办理（台账筛选里「办理状态」的一个取值）
APPROVAL_NONE_LABEL = "未发起"
_SORT_FIELDS = ("offboarding_date", "name", "department")
# 学历列里混着源表错位带进来的日期（「1983/09/18」），不配当筛选选项
_DATE_LIKE = re.compile(r"\d{4}\s*[/\-年.]\s*\d{1,2}")
_OPTION_KEYS = (
    "departments", "positions", "offboarding_types",
    "genders", "educations", "employee_categories",
)


def scoped_departments(ctx: HrAccessContext, department: str | None) -> set[str] | None:
    """数据范围与离职台账列表同口径：不限 → None；self_only → 403；否则授权部门集合。"""
    if ctx.is_unrestricted:
        return None
    if not ctx.scoped_departments:
        raise ForbiddenException("数据范围限制：仅可访问本人相关数据")
    if department and department not in ctx.scoped_departments:
        raise ForbiddenException("数据范围限制：仅可查看授权部门")
    return set(ctx.scoped_departments)


def _like(value: str) -> str:
    """模糊匹配串；转义 % 和 _，否则用户输入「%」能匹配出整表。"""
    escaped = value.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _latest_case_subquery() -> Subquery:
    """每工号最近一张办结单（未删除）；rn = 1 即最新。"""
    ranked = func.row_number().over(
        partition_by=OffboardingCase.employee_number,
        order_by=OffboardingCase.created_at.desc(),
    )
    return (
        select(
            OffboardingCase.id.label("case_id"),
            OffboardingCase.case_no.label("case_no"),
            OffboardingCase.employee_number.label("case_employee_number"),
            OffboardingCase.status.label("case_status"),
            ranked.label("rn"),
        )
        .where(OffboardingCase.is_deleted.is_(False))
        .subquery()
    )


def _base_select(filters: dict[str, Any], scoped: set[str] | None) -> Select[Any]:
    """筛选后的 (台账行 id, 办结单 id, 编号, 状态)；计数与取页都从它派生，口径一致。"""
    sub = _latest_case_subquery()
    stmt = (
        select(
            DepartureRecord.id.label("record_id"),
            sub.c.case_id,
            sub.c.case_no,
            sub.c.case_status,
        )
        .outerjoin(sub, and_(
            sub.c.case_employee_number == DepartureRecord.employee_number,
            sub.c.rn == 1,
        ))
        .where(DepartureRecord.is_deleted.is_(False))
    )
    if scoped is not None:
        stmt = stmt.where(DepartureRecord.department.in_(scoped))

    keyword = (filters.get("keyword") or "").strip()
    if keyword:
        like = _like(keyword)
        stmt = stmt.where(or_(
            DepartureRecord.name.ilike(like, escape="\\"),
            DepartureRecord.employee_number.ilike(like, escape="\\"),
            DepartureRecord.department.ilike(like, escape="\\"),
            DepartureRecord.position.ilike(like, escape="\\"),
        ))
    for key, column in (
        ("department", DepartureRecord.department),
        ("position", DepartureRecord.position),
        ("offboarding_type", DepartureRecord.offboarding_type),
        ("gender", DepartureRecord.gender),
        ("education", DepartureRecord.education),
        ("employee_category", DepartureRecord.employee_category),
    ):
        if filters.get(key):
            stmt = stmt.where(column == filters[key])
    if filters.get("offboarding_reason"):
        # 离职原因是 JSON 多选列，存量数据里还混有标量。不能直接 CAST 成文本再匹配：
        # json 类型原样保留输入文本，库里的中文是 \uXXXX 转义形态，用中文匹配不到；
        # 先转 jsonb（解码转义）再转文本，数组 / 标量两种形态都能按「包含」命中
        reason_text = cast(cast(DepartureRecord.offboarding_reason, JSONB), String)
        stmt = stmt.where(reason_text.ilike(_like(filters["offboarding_reason"]), escape="\\"))

    date_from = filters.get("offboarding_date_from")
    date_to = filters.get("offboarding_date_to")
    if date_from and date_to and date_from > date_to:
        raise AppException(message="离职日期区间：起始日期不能晚于截止日期")
    if date_from:
        stmt = stmt.where(DepartureRecord.offboarding_date >= date_from)
    if date_to:
        stmt = stmt.where(DepartureRecord.offboarding_date <= date_to)

    approval_status = filters.get("approval_status")
    if approval_status == APPROVAL_NONE:
        stmt = stmt.where(sub.c.case_id.is_(None))
    elif approval_status:
        stmt = stmt.where(sub.c.case_status == approval_status)

    if filters.get("cert_issued") is True:
        stmt = stmt.where(DepartureRecord.cert_issued_at.is_not(None))
    elif filters.get("cert_issued") is False:
        stmt = stmt.where(DepartureRecord.cert_issued_at.is_(None))
    if filters.get("cert_signed") is True:
        stmt = stmt.where(DepartureRecord.cert_sign_status == "signed")
    elif filters.get("cert_signed") is False:
        stmt = stmt.where(or_(
            DepartureRecord.cert_sign_status.is_(None),
            DepartureRecord.cert_sign_status != "signed",
        ))
    return stmt


def clearance_summary(items: Sequence[OffboardingClearanceItem]) -> dict[str, dict[str, Any]]:
    """四部门清退进度与扣补金额（台账「清退与结算」从清退明细聚合）。"""
    summary = {
        category: {"total": 0, "done": 0, "deduction": 0.0, "supplement": 0.0}
        for category in OffboardingClearanceItem.CATEGORY_LABELS
    }
    for item in items:
        bucket = summary.setdefault(
            item.category, {"total": 0, "done": 0, "deduction": 0.0, "supplement": 0.0},
        )
        bucket["total"] += 1
        if item.status != OffboardingClearanceItem.STATUS_PENDING:
            bucket["done"] += 1
        bucket["deduction"] = round(bucket["deduction"] + float(item.deduction_amount or 0), 2)
        bucket["supplement"] = round(bucket["supplement"] + float(item.supplement_amount or 0), 2)
    return summary


async def assemble(
    db: AsyncSession, rows: Sequence[Row[Any]], *, with_case: bool = False,
) -> list[dict[str, Any]]:
    """台账行 + 办理流程信息。with_case 时额外挂办结单对象（仅供导出取值，不进接口响应）。"""
    case_ids = [row.case_id for row in rows if row.case_id]
    cases_by_id: dict[Any, OffboardingCase] = {}
    items_by_case: dict[Any, list[OffboardingClearanceItem]] = defaultdict(list)
    if case_ids:
        cases = (await db.execute(
            select(OffboardingCase).where(OffboardingCase.id.in_(case_ids))
        )).scalars().all()
        cases_by_id = {case.id: case for case in cases}
        for item in (await db.execute(
            select(OffboardingClearanceItem).where(
                OffboardingClearanceItem.case_id.in_(case_ids),
                OffboardingClearanceItem.is_deleted.is_(False),
            )
        )).scalars().all():
            items_by_case[item.case_id].append(item)

    result: list[dict[str, Any]] = []
    for record, case_id, case_no, case_status in rows:
        data = DepartureRecordResponse.model_validate(record).model_dump(mode="json")
        # 签名图 base64 不进列表 / 导出（详情按需取）
        has_sign_image = bool(data.pop("cert_sign_image", None))
        status_label = (
            OffboardingCase.STATUS_LABELS.get(case_status or "", APPROVAL_NONE_LABEL)
            if case_status else APPROVAL_NONE_LABEL
        )
        data.update(
            has_sign_image=has_sign_image,
            case_id=str(case_id) if case_id else None,
            case_no=case_no,
            approval_status=case_status,
            approval_status_label=status_label,
            cert_issued=bool(record.cert_issued_at),
            cert_signed=record.cert_sign_status == "signed",
            clearance=clearance_summary(items_by_case.get(case_id, [])),
        )
        if with_case:
            data["_case"] = cases_by_id.get(case_id)
        result.append(data)
    return result


async def query(
    db: AsyncSession,
    filters: dict[str, Any],
    *,
    scoped: set[str] | None,
    sort_by: str = "offboarding_date",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
    limit: int | None = None,
    with_case: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """分页查询；limit 非空时不分页、最多取 limit 行（导出用）。返回 (行, 总数)。"""
    base = _base_select(filters, scoped).subquery()
    total = int((await db.execute(
        select(func.count()).select_from(base)
    )).scalar_one())

    sort_column = getattr(DepartureRecord, sort_by if sort_by in _SORT_FIELDS else "offboarding_date")
    order = desc(sort_column) if sort_order == "desc" else asc(sort_column)
    stmt = (
        select(DepartureRecord, base.c.case_id, base.c.case_no, base.c.case_status)
        .join(base, base.c.record_id == DepartureRecord.id)
        .order_by(order, DepartureRecord.name, DepartureRecord.id)
    )
    if limit is None:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    else:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    return await assemble(db, rows, with_case=with_case), total


def mask_rows(rows: list[dict[str, Any]], has_sensitive: bool) -> list[dict[str, Any]]:
    """无敏感信息权限时屏蔽身份证等字段（与台账详情接口同一口径）。"""
    return [mask_sensitive_fields(row, has_sensitive) for row in rows]


async def filter_options(db: AsyncSession, scoped: set[str] | None) -> dict[str, Any]:
    """筛选下拉选项：聚合台账现有取值（按数据范围收敛，跟随飞书源表变化）。"""
    stmt = select(
        DepartureRecord.department, DepartureRecord.position, DepartureRecord.offboarding_type,
        DepartureRecord.gender, DepartureRecord.education, DepartureRecord.employee_category,
        DepartureRecord.offboarding_reason,
    ).where(DepartureRecord.is_deleted.is_(False))
    if scoped is not None:
        stmt = stmt.where(DepartureRecord.department.in_(scoped))

    buckets: dict[str, set[str]] = {key: set() for key in (*_OPTION_KEYS, "offboarding_reasons")}
    for row in (await db.execute(stmt)).all():
        for key, value in zip(_OPTION_KEYS, row[:6], strict=True):
            if value is not None and str(value).strip():
                if key == "educations" and _DATE_LIKE.search(str(value)):
                    continue
                buckets[key].add(str(value).strip())
        reasons = row.offboarding_reason
        if isinstance(reasons, list):
            buckets["offboarding_reasons"].update(
                reason.strip() for reason in reasons
                if isinstance(reason, str) and reason.strip()
            )
    approval_statuses = [
        {"value": APPROVAL_NONE, "label": APPROVAL_NONE_LABEL},
        *({"value": status, "label": label} for status, label in OffboardingCase.STATUS_LABELS.items()),
    ]
    return {
        **{key: sorted(values) for key, values in buckets.items()},
        "approval_statuses": approval_statuses,
    }
