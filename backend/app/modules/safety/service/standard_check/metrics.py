"""指标注册表（S1 体系标准符合性核查）——metric_key → 取数器。

每个取数器：async (window, ctx) -> MetricOutcome；源不可用（未接入/无会话）
返回 NoData（附原因），绝不把「系统没接」算成未达标。口径 docstring 即冻结点
（DESIGN 附录 A「判定口径冻结点」），改动=改代码+历史快照天然保留旧口径。

T1 交付注册表框架 + 演练 3 取数器；隐患/设施/承包商等组分票补齐。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models.chemical_inventory import ChemicalInventoryRecord
from app.modules.safety.models.contractors import EmergencyDrillRecord
from app.modules.safety.models.facilities import FacilityCheckTask
from app.modules.safety.models.msds import MsdsDocument
from app.modules.safety.models.regulation_ingest import RegulationIngestRun
from app.modules.safety.models.work_ticket_review import WorkTicketReview
from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.contractor_admission_direct import reader as ca_reader
from app.modules.safety.service.hazard_direct import bitable_repo as hz_repo
from app.modules.safety.service.hazard_id_direct import reader as hi_reader
from app.modules.safety.service.oh_direct import ledger as oh_ledger
from app.modules.safety.service.standard_check.engine import (
    MetricOutcome,
    MetricSpec,
    PeriodWindow,
)
from app.modules.safety.service.visitor_insurance import reader as vs_reader

logger = logging.getLogger(__name__)


class Opener(Protocol):
    """Bitable 直读 opener 协议（与 domain_pages 同款，测试注入替身）。"""

    def __call__(self, domain: str, kind: str) -> Any: ...


@dataclass(frozen=True)
class MetricContext:
    """取数上下文：各源句柄按需注入（测试替身/端点真源同构）。"""

    db: AsyncSession | None = None
    opener: Opener | None = None


ComputeFn = Callable[[PeriodWindow, MetricContext], Awaitable[MetricOutcome]]


@dataclass(frozen=True)
class MetricDef:
    spec: MetricSpec
    compute: ComputeFn


REGISTRY: dict[str, MetricDef] = {}


def register(spec: MetricSpec, compute: ComputeFn) -> None:
    REGISTRY[spec.key] = MetricDef(spec=spec, compute=compute)


def get_metric(key: str) -> MetricDef | None:
    return REGISTRY.get(key)


# ═══════════════════════════════════════════════════════════════
# 应急演练（源：safety.emergency_drill_records 镜像表，status=已完成、软删不计）
# ═══════════════════════════════════════════════════════════════


async def _count_drills(
    types: tuple[str, ...], window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    if ctx.db is None:
        return MetricOutcome(no_data_reason="数据库会话不可用")
    query = select(EmergencyDrillRecord).where(
        ~EmergencyDrillRecord.is_deleted,
        EmergencyDrillRecord.status == "已完成",
        EmergencyDrillRecord.execution_time.isnot(None),
        EmergencyDrillRecord.execution_time >= window.start,
        EmergencyDrillRecord.execution_time <= window.end,
        EmergencyDrillRecord.drill_type.in_(types),
    )
    rows = (await ctx.db.execute(query)).scalars().all()
    evidence = tuple(
        {
            "title": r.drill_content or (r.drill_type or "演练"),
            "date": r.execution_time.isoformat() if r.execution_time else "",
            "type": r.drill_type or "",
        }
        for r in rows
    )
    return MetricOutcome(value=float(len(rows)), evidence=evidence)


register(
    MetricSpec(
        key="drill.count.comprehensive_or_special",
        label="综合/专项演练次数",
        unit="次",
        settle="early",
    ),
    lambda w, c: _count_drills(("综合应急演练", "专项应急演练"), w, c),
)
register(
    MetricSpec(
        key="drill.count.site_handling",
        label="现场处置方案演练次数",
        unit="次",
        settle="early",
    ),
    lambda w, c: _count_drills(("现场岗位处置",), w, c),
)
register(
    MetricSpec(
        key="drill.count.evacuation",
        label="应急疏散演练次数",
        unit="次",
        settle="early",
    ),
    lambda w, c: _count_drills(("应急疏散演练",), w, c),
)


# ═══════════════════════════════════════════════════════════════
# 隐患治理（源：hazard 域 Bitable 直读；口径冻结点见 DESIGN 附录 A）
# ═══════════════════════════════════════════════════════════════


_HAZARD_FIELDS = (
    hz_repo.F_NO, hz_repo.F_DESC, hz_repo.F_DATE, hz_repo.F_DEADLINE,
    hz_repo.F_RECTIFY_DONE_AT, hz_repo.F_RECTIFY_STATUS, hz_repo.F_LEVEL_MANUAL,
)


async def _fetch_hazards(ctx: MetricContext) -> list[dict[str, Any]] | None:
    """hazard 全量直读；未接入返回 None（由调用方转 NoData）。"""
    open_client = ctx.opener or bd_reader.resolve_client
    try:
        client = open_client("hazard", "hazard")
        return await client.list_all_records(
            field_names=list(_HAZARD_FIELDS), page_size=500, strict=True
        )
    except BitableConfigError as exc:
        logger.info("hazard 域未接入，指标转无数据: %s", exc)
        return None


def _as_date(value: Any) -> date | None:
    """datetime（UTC）→ 北京日；date 原样；其余 None。"""
    if isinstance(value, datetime):
        return (value + timedelta(hours=8)).date()
    if isinstance(value, date):
        return value
    return None


def _rec_date(record: dict[str, Any], cn: str) -> date | None:
    dt = bd_fields.datetime_ms(record.get("fields") or {}, cn)
    return (dt + timedelta(hours=8)).date() if dt else None


def _select(record: dict[str, Any], cn: str) -> str:
    return bd_fields.select(record.get("fields") or {}, cn) or ""


async def _hazard_on_time_close_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """按期整改完成率=窗口内关闭且带期限的记录中，完成日≤期限的占比。

    超期完成计入未按期；无期限的关闭行不计入分母（口径 docstring 冻结）。
    """
    rows = await _fetch_hazards(ctx)
    if rows is None:
        return MetricOutcome(no_data_reason="hazard 域未接入")
    closed = [
        r for r in rows
        if _select(r, hz_repo.F_RECTIFY_STATUS) == "已关闭"
        and (d := _rec_date(r, hz_repo.F_RECTIFY_DONE_AT)) is not None
        and window.start <= d <= window.end
    ]
    with_deadline = [r for r in closed if _rec_date(r, hz_repo.F_DEADLINE)]
    if not with_deadline:
        return MetricOutcome(
            no_data_reason="窗口内无带整改期限的关闭记录"
        )
    on_time = [
        r for r in with_deadline
        if _rec_date(r, hz_repo.F_RECTIFY_DONE_AT)
        <= _rec_date(r, hz_repo.F_DEADLINE)
    ]
    evidence = (
        {
            "title": f"窗口内关闭 {len(closed)} 条（带期限 {len(with_deadline)}，"
                     f"按期 {len(on_time)}，超期 {len(with_deadline) - len(on_time)}）",
            "date": f"{window.start}~{window.end}",
            "type": "hazard.on_time_close_rate",
        },
    )
    return MetricOutcome(
        value=round(len(on_time) * 100 / len(with_deadline)), evidence=evidence
    )


async def _hazard_major_close_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """重大隐患闭环率=当前全部「重大」级记录中已关闭占比（存量时点口径）。"""
    rows = await _fetch_hazards(ctx)
    if rows is None:
        return MetricOutcome(no_data_reason="hazard 域未接入")
    majors = [
        r for r in rows if "重大" in _select(r, hz_repo.F_LEVEL_MANUAL)
    ]
    if not majors:
        return MetricOutcome(no_data_reason="无重大级隐患记录")
    closed = [
        r for r in majors if _select(r, hz_repo.F_RECTIFY_STATUS) == "已关闭"
    ]
    evidence = (
        {
            "title": f"重大级 {len(majors)} 条，已关闭 {len(closed)} 条",
            "date": f"截至 {window.end}",
            "type": "hazard.major_close_rate",
        },
    )
    return MetricOutcome(value=round(len(closed) * 100 / len(majors)), evidence=evidence)


async def _hazard_register_count(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """排查活动痕迹=窗口内「检查日期」命中行数（仅证明有排查活动）。"""
    rows = await _fetch_hazards(ctx)
    if rows is None:
        return MetricOutcome(no_data_reason="hazard 域未接入")
    hits = [
        r for r in rows
        if (d := _rec_date(r, hz_repo.F_DATE)) is not None
        and window.start <= d <= window.end
    ]
    evidence = tuple(
        {
            "title": f"{_select(r, hz_repo.F_NO)} {_select(r, hz_repo.F_DESC)[:40]}",
            "date": str(_rec_date(r, hz_repo.F_DATE) or ""),
            "type": "hazard.register",
        }
        for r in hits[:20]
    )
    return MetricOutcome(value=float(len(hits)), evidence=evidence)


register(
    MetricSpec("hazard.on_time_close_rate", "隐患按期整改完成率", "%", "period_end"),
    _hazard_on_time_close_rate,
)
register(
    MetricSpec("hazard.major_close_rate", "重大隐患闭环率", "%", "period_end"),
    _hazard_major_close_rate,
)
register(
    MetricSpec("hazard.register_count", "隐患排查登记数", "条", "early"),
    _hazard_register_count,
)


# ═══════════════════════════════════════════════════════════════
# 危险源辨识（源：hazard_id 域直读 reader；计数按记录创建时间）
# ═══════════════════════════════════════════════════════════════



async def _hazard_id_count(window: PeriodWindow, ctx: MetricContext) -> MetricOutcome:
    try:
        views = await hi_reader.open_reader().fetch_all(strict=True)
    except BitableConfigError as exc:
        return MetricOutcome(no_data_reason=f"hazard_id 域未接入: {exc}")
    def _view_date(v: Any) -> date | None:
        ms = getattr(v, "created_time_ms", None)
        if not ms:
            return None
        return _as_date(datetime.fromtimestamp(ms / 1000, tz=UTC))

    hits = [v for v in views if (d := _view_date(v)) and window.start <= d <= window.end]
    evidence = tuple(
        {
            "title": (v.specific_activity or "危险源辨识")[:40],
            "date": str(_view_date(v) or ""),
            "type": "hazard_id",
        }
        for v in hits[:20]
    )
    return MetricOutcome(value=float(len(hits)), evidence=evidence)


register(
    MetricSpec("hazard_id.count.year", "年度危险源辨识次数", "次", "early"),
    _hazard_id_count,
)


# ═══════════════════════════════════════════════════════════════
# 职业健康体检率（源：oh 域 exam_registry/person_master 直读）
# ═══════════════════════════════════════════════════════════════



async def _oh_exam_rate(window: PeriodWindow, ctx: MetricContext) -> MetricOutcome:
    """体检率=窗口内 exam_date 命中的体检记录数 / 人员汇总表在册行数。

    应检基数口径（docstring 冻结）：person_master 全量在册——「接触职业危害
    人员名单」口径待安环科核定后收紧；结果封顶 100%。
    """
    try:
        exams = await oh_ledger.fetch_exams()
        persons = await oh_ledger.fetch_persons()
    except BitableConfigError as exc:
        return MetricOutcome(no_data_reason=f"oh 域未接入: {exc}")
    if not persons:
        return MetricOutcome(no_data_reason="人员汇总表为空")
    hits = [
        v for v in exams
        if (d := _as_date(getattr(v, "exam_date", None))) is not None
        and window.start <= d <= window.end
    ]
    rate = min(100, round(len(hits) * 100 / len(persons)))
    evidence = (
        {
            "title": f"窗口内体检记录 {len(hits)} 条 / 在册 {len(persons)} 人",
            "date": f"{window.start}~{window.end}",
            "type": "oh.exam_rate",
        },
    )
    return MetricOutcome(value=float(rate), evidence=evidence)


register(
    MetricSpec("oh.exam_rate", "职业健康体检率", "%", "period_end"),
    _oh_exam_rate,
)


# ═══════════════════════════════════════════════════════════════
# 特殊作业票审核覆盖率（源：work_ticket_reviews 每日审核摘要，DB）
# ═══════════════════════════════════════════════════════════════



async def _workticket_audit_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """审核覆盖率=窗口内各日 Σreviewed / Σtotal（无作业票的月份无分母→无数据）。"""
    if ctx.db is None:
        return MetricOutcome(no_data_reason="数据库会话不可用")
    result = await ctx.db.execute(
        select(
            sa_func.coalesce(sa_func.sum(WorkTicketReview.total), 0),
            sa_func.coalesce(sa_func.sum(WorkTicketReview.reviewed), 0),
        ).where(
            ~WorkTicketReview.is_deleted,
            WorkTicketReview.date >= window.start,
            WorkTicketReview.date <= window.end,
        )
    )
    total_sum, reviewed_sum = result.one()
    if not total_sum:
        return MetricOutcome(no_data_reason="窗口内无作业票审核记录")
    evidence = (
        {
            "title": f"窗口内作业票 {total_sum} 张，纳入审核 {reviewed_sum} 张",
            "date": f"{window.start}~{window.end}",
            "type": "workticket.audit_rate",
        },
    )
    return MetricOutcome(
        value=round(reviewed_sum * 100 / total_sum), evidence=evidence
    )


register(
    MetricSpec("workticket.audit_rate", "作业票审核覆盖率", "%", "period_end"),
    _workticket_audit_rate,
)


# ═══════════════════════════════════════════════════════════════
# 设施校验任务（源：facility_check_tasks DB；窗口=due_date∈窗口的任务）
# ═══════════════════════════════════════════════════════════════



async def _facility_on_time_close_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """按期闭环率=窗口内到期任务中 closed 且 closed_at≤due 的比例。"""
    if ctx.db is None:
        return MetricOutcome(no_data_reason="数据库会话不可用")
    rows = (
        await ctx.db.execute(
            select(FacilityCheckTask).where(
                ~FacilityCheckTask.is_deleted,
                FacilityCheckTask.due_date >= window.start,
                FacilityCheckTask.due_date <= window.end,
            )
        )
    ).scalars().all()
    if not rows:
        return MetricOutcome(no_data_reason="窗口内无到期校验任务")
    closed_on_time = [
        t for t in rows
        if t.status == "closed" and t.closed_at is not None
        and t.closed_at.date() <= t.due_date
    ]
    evidence = (
        {
            "title": f"窗口内到期 {len(rows)} 项，按期闭环 {len(closed_on_time)} 项",
            "date": f"{window.start}~{window.end}",
            "type": "facility.on_time_close_rate",
        },
    )
    return MetricOutcome(
        value=round(len(closed_on_time) * 100 / len(rows)), evidence=evidence
    )


register(
    MetricSpec("facility.on_time_close_rate", "设施校验按期闭环率", "%", "period_end"),
    _facility_on_time_close_rate,
)


# ═══════════════════════════════════════════════════════════════
# 承包商准入（源：contractor_admission 直读；窗口=entry_date∈窗口）
# ═══════════════════════════════════════════════════════════════


_CA_COMPLETED = "completed"


async def _fetch_admissions(ctx: MetricContext):
    try:
        return await ca_reader.open_reader().fetch_all(strict=True)
    except BitableConfigError as exc:
        logger.info("contractor_admission 域未接入: %s", exc)
        return None


async def _contractor_admit_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """准入审核完成率=窗口内入场记录中 AI 审核结论非空（completed）比例。"""
    views = await _fetch_admissions(ctx)
    if views is None:
        return MetricOutcome(no_data_reason="contractor_admission 域未接入")
    hits = [
        v for v in views
        if (d := getattr(v, "entry_date", None)) and window.start <= d <= window.end
    ]
    if not hits:
        return MetricOutcome(no_data_reason="窗口内无入场记录")
    done = [v for v in hits if getattr(v, "ai_review_status", None) == _CA_COMPLETED]
    evidence = (
        {
            "title": f"窗口内入场 {len(hits)} 家，审核完成 {len(done)} 家",
            "date": f"{window.start}~{window.end}",
            "type": "contractor.admit_rate",
        },
    )
    return MetricOutcome(value=round(len(done) * 100 / len(hits)), evidence=evidence)


async def _contractor_agreement_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """安全协议签订率=窗口内入场记录中安全管理协议附件非空比例。"""
    views = await _fetch_admissions(ctx)
    if views is None:
        return MetricOutcome(no_data_reason="contractor_admission 域未接入")
    hits = [
        v for v in views
        if (d := getattr(v, "entry_date", None)) and window.start <= d <= window.end
    ]
    if not hits:
        return MetricOutcome(no_data_reason="窗口内无入场记录")
    signed = [v for v in hits if getattr(v, "safety_agreement_files", None)]
    evidence = (
        {
            "title": f"窗口内入场 {len(hits)} 家，协议已附 {len(signed)} 家",
            "date": f"{window.start}~{window.end}",
            "type": "contractor.agreement_rate",
        },
    )
    return MetricOutcome(value=round(len(signed) * 100 / len(hits)), evidence=evidence)


register(
    MetricSpec("contractor.admit_rate", "承包商准入审核完成率", "%", "period_end"),
    _contractor_admit_rate,
)
register(
    MetricSpec("contractor.agreement_rate", "相关方安全协议签订率", "%", "period_end"),
    _contractor_agreement_rate,
)


# ═══════════════════════════════════════════════════════════════
# 外来人员（源：visitor_notice 域直读；窗口=进厂开始时间∈窗口）
# ═══════════════════════════════════════════════════════════════



async def _fetch_visitor_views(ctx: MetricContext):
    try:
        return await vs_reader.open_reader().fetch_all()
    except BitableConfigError as exc:
        logger.info("visitor_notice 域未接入: %s", exc)
        return None


async def _visitor_notice_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """报备审批完成率=窗口内进厂申请单中申请状态=已通过比例。"""
    views = await _fetch_visitor_views(ctx)
    if views is None:
        return MetricOutcome(no_data_reason="visitor_notice 域未接入")
    hits = [
        v for v in views
        if (d := getattr(v, "entry_start", None)) and window.start <= d <= window.end
    ]
    if not hits:
        return MetricOutcome(no_data_reason="窗口内无进厂申请")
    approved = [v for v in hits if getattr(v, "status", None) == "已通过"]
    evidence = (
        {
            "title": f"窗口内进厂申请 {len(hits)} 单，已通过 {len(approved)} 单",
            "date": f"{window.start}~{window.end}",
            "type": "visitor.notice_rate",
        },
    )
    return MetricOutcome(value=round(len(approved) * 100 / len(hits)), evidence=evidence)


async def _visitor_insurance_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """保险填报率=窗口内进厂申请单中保险有效期已填比例。"""
    views = await _fetch_visitor_views(ctx)
    if views is None:
        return MetricOutcome(no_data_reason="visitor_notice 域未接入")
    hits = [
        v for v in views
        if (d := getattr(v, "entry_start", None)) and window.start <= d <= window.end
    ]
    if not hits:
        return MetricOutcome(no_data_reason="窗口内无进厂申请")
    filled = [v for v in hits if getattr(v, "insurance_end", None)]
    evidence = (
        {
            "title": f"窗口内进厂申请 {len(hits)} 单，保险已填 {len(filled)} 单",
            "date": f"{window.start}~{window.end}",
            "type": "visitor.insurance_rate",
        },
    )
    return MetricOutcome(value=round(len(filled) * 100 / len(hits)), evidence=evidence)


register(
    MetricSpec("visitor.notice_rate", "外来人员报备审批完成率", "%", "period_end"),
    _visitor_notice_rate,
)
register(
    MetricSpec("visitor.insurance_rate", "外来人员保险填报率", "%", "period_end"),
    _visitor_insurance_rate,
)


# ═══════════════════════════════════════════════════════════════
# 危化品 SDS 覆盖率（源：库存品种表 × MSDS 文档表，均 DB）
# ═══════════════════════════════════════════════════════════════



def coverage_of(names: set[str], doc_names: set[str]) -> tuple[set[str], list[str]]:
    """品种集合 × 现役 MSDS 名称集合 → (已覆盖, 未覆盖排序清单)（纯函数）。"""
    norm_names = {n.strip() for n in names if n and n.strip()}
    norm_docs = {d.strip() for d in doc_names if d and d.strip()}
    covered = norm_names & norm_docs
    return covered, sorted(norm_names - covered)


async def _msds_coverage_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """SDS 覆盖率=在册库存品种（distinct material_name）中匹配现役 MSDS 的比例。

    现役=archive_status≠archived；名称归一=strip 全比较（docstring 冻结）。
    """
    if ctx.db is None:
        return MetricOutcome(no_data_reason="数据库会话不可用")
    chemicals = (
        await ctx.db.execute(select(ChemicalInventoryRecord.material_name).where(~ChemicalInventoryRecord.is_deleted))
    ).scalars().all()
    names = {n.strip() for n in chemicals if n and n.strip()}
    if not names:
        return MetricOutcome(no_data_reason="库存品种表为空")
    docs = (
        await ctx.db.execute(
            select(MsdsDocument.name).where(
                ~MsdsDocument.is_deleted,
                MsdsDocument.archive_status != "archived",
            )
        )
    ).scalars().all()
    covered, missing = coverage_of(names, {d.strip() for d in docs if d})
    evidence = (
        {
            "title": f"在册 {len(names)} 种，已配 SDS {len(covered)} 种"
                     + (f"；未配：{'、'.join(missing[:8])}" if missing else ""),
            "date": f"截至 {window.end}",
            "type": "msds.coverage_rate",
        },
    )
    return MetricOutcome(value=round(len(covered) * 100 / len(names)), evidence=evidence)


register(
    MetricSpec("msds.coverage_rate", "危化品 SDS 配备覆盖率", "%", "period_end"),
    _msds_coverage_rate,
)


# ═══════════════════════════════════════════════════════════════
# 法规收录（源：regulation_ingest_runs DB；completed 运行计数）
# ═══════════════════════════════════════════════════════════════



async def _regulation_ingest_count(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    if ctx.db is None:
        return MetricOutcome(no_data_reason="数据库会话不可用")
    rows = (
        await ctx.db.execute(
            select(RegulationIngestRun.created_at).where(
                ~RegulationIngestRun.is_deleted,
                RegulationIngestRun.status == "completed",
            )
        )
    ).scalars().all()
    hits = [c for c in rows if (d := _as_date(c)) and window.start <= d <= window.end]
    evidence = (
        {
            "title": f"窗口内完成收录运行 {len(hits)} 次",
            "date": f"{window.start}~{window.end}",
            "type": "regulation.ingest_count",
        },
    )
    return MetricOutcome(value=float(len(hits)), evidence=evidence)


register(
    MetricSpec("regulation.ingest_count", "法规收录运行次数", "次", "early"),
    _regulation_ingest_count,
)


# ═══════════════════════════════════════════════════════════════
# S6 教育培训（源：training_behavior/training Bitable 直读，2026-10-22 接入）
# ═══════════════════════════════════════════════════════════════


_TRAINING_STATUS = "状态"
_TRAINING_FIELDS_READ = (
    "培训名称", "状态", "计划日期", "实施日期", "签到表", "考核方式", "考核合格人数",
)
_PLANNED_STATUSES = ("未开始", "进行中", "已完成")


async def _fetch_trainings(ctx: MetricContext) -> list[dict[str, Any]] | None:
    """training 表全量直读；未接入返回 None（由调用方转 NoData）。"""
    open_client = ctx.opener or bd_reader.resolve_client
    try:
        client = open_client("training_behavior", "training")
        return await client.list_all_records(
            field_names=list(_TRAINING_FIELDS_READ), page_size=500, strict=True
        )
    except BitableConfigError as exc:
        logger.info("training_behavior 域未接入，指标转无数据: %s", exc)
        return None


def _int_text(record: dict[str, Any], cn: str) -> int | None:
    """数字文本列（应到/合格人数）→ int；缺失/非数字 None。"""
    raw = bd_fields.text(record.get("fields") or {}, cn)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


async def _training_completion_rate(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """D3-05 计划完成率=窗口内（计划日期锚定）非取消行中已完成/应完成。"""
    rows = await _fetch_trainings(ctx)
    if rows is None:
        return MetricOutcome(no_data_reason="training_behavior 域未接入")
    hits = [
        r for r in rows
        if (d := _rec_date(r, "计划日期")) and window.start <= d <= window.end
        and _select(r, _TRAINING_STATUS) != "已取消"
    ]
    planned = [r for r in hits if _select(r, _TRAINING_STATUS) in _PLANNED_STATUSES]
    if not planned:
        return MetricOutcome(no_data_reason="窗口内无培训计划")
    done = sum(1 for r in planned if _select(r, _TRAINING_STATUS) == "已完成")
    evidence = (
        {
            "title": f"窗口内计划 {len(planned)} 项，已完成 {done} 项",
            "date": f"{window.start}~{window.end}",
            "type": "training.completion_rate",
        },
    )
    return MetricOutcome(value=round(done * 100 / len(planned)), evidence=evidence)


async def _training_record_integrity(
    window: PeriodWindow, ctx: MetricContext
) -> MetricOutcome:
    """D3-07 台账完整率=窗口内（实施日期锚定）已完成行中留痕完整占比。

    完整=签到表附件非空 且（考核方式=无需考核 或 考核合格人数已填）。
    """
    rows = await _fetch_trainings(ctx)
    if rows is None:
        return MetricOutcome(no_data_reason="training_behavior 域未接入")
    held = [
        r for r in rows
        if _select(r, _TRAINING_STATUS) == "已完成"
        and (d := _rec_date(r, "实施日期")) and window.start <= d <= window.end
    ]
    if not held:
        return MetricOutcome(no_data_reason="窗口内无已完成培训")

    def intact(r: dict[str, Any]) -> bool:
        fields = r.get("fields") or {}
        has_attendance = bool(bd_fields.attachments(fields, "签到表"))
        no_exam = _select(r, "考核方式") == "无需考核"
        return has_attendance and (no_exam or _int_text(r, "考核合格人数") is not None)

    ok = [r for r in held if intact(r)]
    evidence = (
        {
            "title": f"窗口内已完成 {len(held)} 项，留痕完整 {len(ok)} 项",
            "date": f"{window.start}~{window.end}",
            "type": "training.record_integrity",
        },
    )
    return MetricOutcome(value=round(len(ok) * 100 / len(held)), evidence=evidence)


register(
    MetricSpec("training.completion_rate", "年度培训计划完成率", "%", "period_end"),
    _training_completion_rate,
)
register(
    MetricSpec("training.record_integrity", "培训台账记录完整率", "%", "period_end"),
    _training_record_integrity,
)
