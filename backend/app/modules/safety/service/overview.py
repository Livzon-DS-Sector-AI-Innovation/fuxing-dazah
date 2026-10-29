"""安全总览驾驶舱聚合服务（GET /safety/overview，二期 3.0 门面）。

一个端点喂饱驾驶舱：按域采集器 asyncio.gather 并行，单域失败降级
（该域置 None + errors 标注），绝不拖垮整页。采集全部复用各域既有
service/repo（含直读/镜像双模式 gate），禁止 HTTP 自调。

口径与一致性（验收抽样对账依据，详见 .scratch/safety-web-p2/）：
- 隐患 KPI：未闭环 = hazards stats 的 total − closed（与 GET /hazards/stats
  同源同库）；delta = 未闭环 − 昨日零点时点未闭环（时点值由
  discovered_at/闭环时间推算，无需快照存储）
- 特殊作业：SpecialOperationDailyReportService.get_stats（与
  GET /special-operation-daily-report/stats 同源）
- 报警：滚动近 7 天窗口（today-6..today）记录应用侧分桶；今日计数与
  fire/central stats 的 today_total 同日窗口可对账；真报 = 消防 nature
  含「真实」的今日计数（中控无性质字段，真报为消防口径）
- 证书 / 危化品 / 关键风险 / EHS：各域 stats service 同源（cert 与危化品
  直读为全量拉取，已加 60s TTL 缓存兜住重复请求）
- 速递：Redis 速递格子只读回放（daily_digest.load_daily_digest_cells）
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.feishu.daily_digest import load_daily_digest_cells
from app.modules.safety.regulation_ingest.monitor import build_s2_metric
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.service import (
    CertWarningService,
    ChemicalInventoryService,
    EhsChangeService,
    HazardService,
    KeyRiskOperationReportService,
    SpecialOperationDailyReportService,
)
from app.modules.safety.service.domain_pages import (
    DOMAIN_PAGE_KEYS,
    collect_domain_health,
    module_health_card,
)
from app.modules.safety.service.standard_check import collect_goals_health
from app.modules.safety.workticket_review.repository import WorkTicketReviewRepository

logger = logging.getLogger(__name__)

_TREND_DAYS = 30
_DRILLDOWN_LIMIT = 20
# P1-6：overview 单域采集超时（秒）——慢域降级记 errors，不拖死整页/整轮
_DOMAIN_TIMEOUT = 30

# 健康度模块 key（与前端 menu-config safety 子项 key 一一对应；名称/路径/
# 分组由前端从菜单解析，后端只下发状态与指标文案）
_RUNNING_MODULES = (
    "knowledge-base",
    "risk-grading",
    "occupational-health",
    "contractor-admission",
    "emergency-drill",
)


def _bj_today() -> date:
    """北京时间今天（与 daily_digest/scheduler 同口径）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _bj_day_start_utc(d: date) -> datetime:
    """北京日零点对应的 UTC 时点（窗口比较统一走 UTC aware）。"""
    return datetime.combine(d, time.min, tzinfo=UTC) - timedelta(hours=8)


def _as_utc(ts: datetime) -> datetime:
    """DB/视图时间统一转 UTC aware（naive 视作 UTC）。"""
    return ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)


def _bj_date(ts: datetime) -> date:
    return (_as_utc(ts) + timedelta(hours=8)).date()


async def collect_hazards(db: AsyncSession) -> dict[str, Any]:
    """隐患：未闭环 KPI + 较昨日 delta + 近 30 天新增/闭环按日序列。"""
    from app.modules.safety.service.hazard_direct import config as hazard_config

    today = _bj_today()
    dates = [today - timedelta(days=i) for i in range(_TREND_DAYS - 1, -1, -1)]

    if hazard_config.query_direct_enabled():
        # 直读：全量缓存视图内存统计（趋势分桶/as-of 口径见 page_query 模块头）
        from app.modules.safety.service.hazard_direct.page_query import (
            count_unclosed_asof,
            ledger_stats,
            trend_buckets,
        )
        from app.modules.safety.service.hazard_direct.reader import open_reader

        views = await open_reader().fetch_all()
        stats = ledger_stats(views)
        unclosed = stats["total"] - stats["closed"]
        created, closed = trend_buckets(views)
        created_bucket: Counter[date] = Counter(_bj_date(t) for t in created)
        closed_bucket: Counter[date] = Counter(_bj_date(t) for t in closed)
        unclosed_yesterday = count_unclosed_asof(views, _bj_day_start_utc(today))
    else:
        stats = await HazardService(db).get_hazard_stats()
        unclosed = stats["total"] - stats["closed"]

        repo = SafetyRepository(db)
        window_start = _bj_day_start_utc(today - timedelta(days=_TREND_DAYS - 1))
        window_end = _bj_day_start_utc(today + timedelta(days=1))
        created, closed, unclosed_yesterday = await asyncio.gather(
            repo.get_hazard_created_times(window_start, window_end),
            repo.get_hazard_closed_times(window_start, window_end),
            repo.count_hazards_unclosed_asof(_bj_day_start_utc(today)),
        )

        created_bucket = Counter(_bj_date(t) for t in created)
        closed_bucket = Counter(_bj_date(t) for t in closed)
    return {
        "unclosed": unclosed,
        "delta": unclosed - unclosed_yesterday,
        "overdue": stats["overdue"],
        "trend": {
            "dates": [d.isoformat() for d in dates],
            "created": [created_bucket.get(d, 0) for d in dates],
            "closed": [closed_bucket.get(d, 0) for d in dates],
        },
    }


async def collect_special_ops(db: AsyncSession) -> dict[str, Any]:
    """特殊作业：今日作业数与高风险数（日报 stats 同源）。"""
    from app.modules.safety.service.special_op_direct import config as so_config

    if so_config.direct_enabled():
        # 直读：当日全量视图（风险列存量优先/缺失现场判定），排除项不计入
        from app.modules.safety.service.special_op_direct.bitable_repo import (
            fetch_day_views,
        )

        views = await fetch_day_views(_bj_today())
        effective = [v for v in views if not v.is_excluded]
        return {
            "today_total": len(effective),
            "high": sum(1 for v in effective if v.daily_risk_level == "high"),
        }

    stats = await SpecialOperationDailyReportService(db).get_stats(_bj_today())
    return {"today_total": stats["total"], "high": stats["high"]}


async def collect_alarms(db: AsyncSession) -> dict[str, Any]:
    """报警：今日消防+中控计数与真报数 + 近 7 日按日序列 + Top 消防类型。

    滚动 7 天窗（today-6..today）——自然周在周一只剩 1 天，序列太短。
    """
    from app.modules.safety.service.central_alarm import config as ca_config
    from app.modules.safety.service.fire_alarm.service import FireAlarmService

    today = _bj_today()
    window_start = today - timedelta(days=6)
    fire_records = await FireAlarmService(db).get_week_records(
        window_start,
        today,
    )

    # 直读分支返回视图对象、镜像分支返回 ORM 记录（duck typing 同字段名）
    central_records: list[Any]
    if ca_config.direct_enabled():
        from app.modules.safety.service.central_alarm.reader import open_reader

        central_records = list(
            await open_reader().fetch_window_records(
                start_utc=_bj_day_start_utc(window_start),
                end_utc=_bj_day_start_utc(today + timedelta(days=1)),
            )
        )
    else:
        from app.modules.safety.service.central_alarm.service import (
            CentralAlarmService,
        )

        central_records = await CentralAlarmService(db).get_week_records(
            window_start,
            today,
        )

    today_start = _bj_day_start_utc(today)
    today_end = _bj_day_start_utc(today + timedelta(days=1))

    def _in_today(ts: datetime | None) -> bool:
        return ts is not None and today_start <= _as_utc(ts) < today_end

    fire_today = sum(1 for r in fire_records if _in_today(r.alarm_time))
    central_today = sum(1 for r in central_records if _in_today(r.alarm_date))
    fire_real_today = sum(
        1
        for r in fire_records
        if _in_today(r.alarm_time) and "真实" in (r.alarm_nature or "")
    )

    # 序列画满 7 天（滚动窗），缺数日为 0
    dates = [window_start + timedelta(days=i) for i in range(7)]
    fire_bucket: Counter[date] = Counter(
        _bj_date(r.alarm_time) for r in fire_records if r.alarm_time
    )
    central_bucket: Counter[date] = Counter(
        _bj_date(r.alarm_date) for r in central_records if r.alarm_date
    )
    top_types = Counter(r.alarm_type for r in fire_records if r.alarm_type).most_common(
        5
    )
    return {
        "today_total": fire_today + central_today,
        "fire_today": fire_today,
        "central_today": central_today,
        "fire_real_today": fire_real_today,
        "analysis": {
            "dates": [d.isoformat() for d in dates],
            "fire_daily": [fire_bucket.get(d, 0) for d in dates],
            "central_daily": [central_bucket.get(d, 0) for d in dates],
            "top_fire_types": [
                {"name": name, "count": count} for name, count in top_types
            ],
        },
    }


async def collect_certs(db: AsyncSession) -> dict[str, Any]:
    """证书：30 天内到期数 + 8 天内/已逾期计数 + 到期明细（升序取前 20）。"""
    from app.modules.safety.service.cert_direct import config as cert_config

    if cert_config.direct_enabled():
        from app.modules.safety.service.cert_direct.query import (
            get_summary_direct,
            get_warnings_direct,
        )
        from app.modules.safety.service.cert_direct.reader import open_reader

        reader = open_reader()
        summary = await get_summary_direct(reader)
        items, _total = await get_warnings_direct(
            reader,
            limit=_DRILLDOWN_LIMIT,
            days_within=30,
        )
    else:
        service = CertWarningService(db)
        summary = await service.get_summary()
        items, _total = await service.get_warnings(
            skip=0,
            limit=_DRILLDOWN_LIMIT,
            days_within=30,
        )

    within_30d = (
        summary.key_warning_count + summary.urgent_count + summary.overdue_count
    )
    urgent_or_overdue = summary.urgent_count + summary.overdue_count
    ordered = sorted(
        items,
        key=lambda x: x.remaining_days if x.remaining_days is not None else 1 << 30,
    )
    return {
        "within_30d": within_30d,
        "urgent_or_overdue": urgent_or_overdue,
        "items": [
            {
                "person_name": it.person_name,
                "department": it.department,
                "cert_category": it.cert_category,
                "deadline": it.deadline,
                "remaining_days": it.remaining_days,
            }
            for it in ordered
        ],
    }


async def collect_chemicals(db: AsyncSession) -> dict[str, Any]:
    """危化品：超储项数 + 超储物料明细。"""
    service = ChemicalInventoryService(db)
    stats = await service.get_stats()
    materials = await service.get_over_limit_materials(limit=_DRILLDOWN_LIMIT)
    return {"over_limit": stats["over_limit"], "materials": materials}


def _key_risk_item(it: Any) -> dict[str, Any]:
    return {
        "start_time": getattr(it, "start_time", None),
        "department": getattr(it, "department", None),
        "operation_content": getattr(it, "operation_content", None),
        "apply_status": getattr(it, "apply_status", None),
    }


def _sort_key_risk_items_desc(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """start_time 降序、空值沉底（与台账排序一致，空开始时间排最后不压首行）。"""
    return sorted(
        items,
        key=lambda it: (
            it["start_time"] is None,
            -it["start_time"].timestamp() if it["start_time"] is not None else 0.0,
        ),
    )


async def collect_key_risk_ops(db: AsyncSession) -> dict[str, Any]:
    """关键风险作业：当日已通过/审批中计数 + 当日清单（整卡当日口径）。

    审批中同样按 start_time 落在今日过滤——历史积压的审批中不在本卡展示
    （2026-10-27 用户拍板：其他日期的不展示）。台账页 KPI 仍为全量口径。
    """
    service = KeyRiskOperationReportService(db)
    today = _bj_today()
    approved, approved_total = await service.get_reports(
        0,
        _DRILLDOWN_LIMIT,
        date_from=today,
        date_to=today,
        apply_status="已通过",
    )
    in_review, in_review_total = await service.get_reports(
        0,
        _DRILLDOWN_LIMIT,
        date_from=today,
        date_to=today,
        apply_status="审批中",
    )
    return {
        "today_approved": approved_total,
        "in_progress": in_review_total,
        "items": _sort_key_risk_items_desc(
            [_key_risk_item(it) for it in approved]
            + [_key_risk_item(it) for it in in_review]
        ),
    }


async def collect_ehs(db: AsyncSession) -> dict[str, Any]:
    """EHS 变更：进行中（审核中+实施中）计数。"""
    stats = await EhsChangeService(db).get_ehs_change_stats()
    status: dict[str, int] = stats.get("status", {})
    return {
        "in_progress": status.get("under_review", 0) + status.get("in_progress", 0),
    }


async def collect_digest(digest_store: Any = None) -> dict[str, Any]:
    """今日安全速递回放（Redis 只读；store 为测试接缝）。"""
    cells = await load_daily_digest_cells(_bj_today(), store=digest_store)
    return {"count": len(cells), "cells": cells}


async def collect_supervision(db: AsyncSession) -> dict[str, Any]:
    """监督（三期起步）：最近一次作业票审核摘要（健康度墙指标）。

    无记录 → latest=None（前端卡片显示「待首跑」灰态）。
    """
    review = await WorkTicketReviewRepository(db).get_latest()
    if review is None:
        return {"latest": None}
    return {
        "latest": {
            "date": review.date.isoformat(),
            "violation_count": review.violation_count,
        }
    }


async def collect_facility_tasks(db: AsyncSession) -> dict[str, Any]:
    """设施校验任务（facilities-p1 票 06）：待闭环/逾期计数。

    健康度墙 facilities 卡的任务口径覆盖源——逾期>0 → warn 告警
    （DESIGN §6：驾驶舱逾期校验任务>0 告警卡；无任务/降级时卡仍走
    collect_domain_health 三态口径）。
    """
    from sqlalchemy import func, select

    from app.modules.safety.models import FacilityCheckTask

    open_n = (
        await db.execute(
            select(func.count()).select_from(FacilityCheckTask).where(
                FacilityCheckTask.status == "issued",
                FacilityCheckTask.is_deleted.is_(False),
            )
        )
    ).scalar_one()
    overdue_n = (
        await db.execute(
            select(func.count()).select_from(FacilityCheckTask).where(
                FacilityCheckTask.status == "issued",
                FacilityCheckTask.due_date < _bj_today(),
                FacilityCheckTask.is_deleted.is_(False),
            )
        )
    ).scalar_one()
    return {"open": int(open_n), "overdue": int(overdue_n)}


def _build_module_health(parts: dict[str, Any | None]) -> list[dict[str, Any]]:
    """17 模块健康度（key 对齐前端菜单；缺数域指标降为 None，不炸墙）。"""
    hazards = parts.get("hazards")
    special_ops = parts.get("special_ops")
    alarms = parts.get("alarms")
    certs = parts.get("certs")
    chemicals = parts.get("chemicals")
    key_risk_ops = parts.get("key_risk_ops")
    ehs = parts.get("ehs")
    kb_s2 = parts.get("knowledge_base_s2")

    cards: list[dict[str, Any]] = [
        {
            # S2 法规标准与规程：metric=采集状态摘要（ragplus 契约③+收录留痕，
            # 未对接保持运行中口径；降级变 warn）
            "key": "knowledge-base",
            "status": (kb_s2 or {}).get("status", "ok") if kb_s2 else "ok",
            "metric": (kb_s2 or {}).get("metric") if kb_s2 else "运行中",
        },
        {"key": "risk-grading", "status": "ok", "metric": "运行中"},
        {
            "key": "hazard-ledger",
            "status": "warn" if hazards and hazards["overdue"] > 0 else "ok",
            "metric": (
                f"未闭环 {hazards['unclosed']} · 逾期 {hazards['overdue']}"
                if hazards
                else None
            ),
        },
        {
            "key": "cert-warnings",
            "status": "warn" if certs and certs["urgent_or_overdue"] > 0 else "ok",
            "metric": f"30 天内到期 {certs['within_30d']}" if certs else None,
        },
        {"key": "occupational-health", "status": "ok", "metric": "运行中"},
        {
            "key": "chemicals",
            "status": "warn" if chemicals and chemicals["over_limit"] > 0 else "ok",
            "metric": f"超储 {chemicals['over_limit']} 项" if chemicals else None,
        },
        {
            "key": "special-ops",
            "status": "warn" if special_ops and special_ops["high"] > 0 else "ok",
            "metric": (
                f"今日 {special_ops['today_total']} 项 · 高险 {special_ops['high']}"
                if special_ops
                else None
            ),
        },
        {
            "key": "risk-reporting",
            "status": "ok",
            "metric": (
                f"今日通过 {key_risk_ops['today_approved']} / "
                f"今日审批中 {key_risk_ops['in_progress']}"
                if key_risk_ops
                else None
            ),
        },
        {
            "key": "alarms",
            "status": "warn" if alarms and alarms["fire_real_today"] > 0 else "ok",
            "metric": (
                f"今日 {alarms['today_total']} 起 · 真报 {alarms['fire_real_today']}"
                if alarms
                else None
            ),
        },
        {
            "key": "ehs-change",
            "status": "ok",
            "metric": f"进行中 {ehs['in_progress']} 项" if ehs else None,
        },
        {"key": "contractor-admission", "status": "ok", "metric": "运行中"},
        {"key": "emergency-drill", "status": "ok", "metric": "运行中"},
    ]
    # 四新域卡（四期 1-B）：三态=未接入 inactive·「未接入」/ 接入后 ok|warn 按蓝本
    # 判据 / 采集降级 inactive·无指标（口径 domain_pages.module_health_card）
    # goals 卡（S1 体系标准核查，2026-10-21 改造）：四态判定口径
    # （warn=存在未达标），卡序保持在四新域最前
    cards.append(module_health_card("goals", parts.get("goals")))
    cards.extend(module_health_card(key, parts.get(key)) for key in DOMAIN_PAGE_KEYS)
    # facilities 卡任务口径覆盖（facilities-p1；2026-10-21 修正）：有在办任务
    # （open/overdue>0）即以任务计数为准——任务存在本身证明已有台账接入并跑过
    # 派发，不再要求域卡非 inactive（域健康查的是四期蓝本旧 kind 的连接，
    # 三台账新 kind 已接入时旧 kind 仍空连接，曾把卡死锁在「未接入」）；
    # 无任务时保持三态口径——避免空库把「未接入」盖成假 ok
    facility_tasks = parts.get("facility_tasks")
    facilities_card = next((c for c in cards if c["key"] == "facilities"), None)
    if (
        facility_tasks
        and (facility_tasks["open"] or facility_tasks["overdue"])
        and facilities_card is not None
    ):
        facilities_card["status"] = (
            "warn" if facility_tasks["overdue"] > 0 else "ok"
        )
        facilities_card["metric"] = (
            f"校验待闭环 {facility_tasks['open']} · 逾期 {facility_tasks['overdue']}"
        )
    # 监督卡（三期起步）：最近一次审核真实指标（违规>0 → 黄）；无记录「待首跑」灰；
    # 采集降级（parts=None）沿单域降级惯例 → 灰卡无指标
    supervision_latest = (parts.get("supervision") or {}).get("latest")
    if supervision_latest:
        cards.append(
            {
                "key": "supervision",
                "status": (
                    "warn" if supervision_latest["violation_count"] > 0 else "ok"
                ),
                "metric": (
                    f"最近审核 {supervision_latest['date']} · "
                    f"违规 {supervision_latest['violation_count']}"
                ),
            }
        )
    else:
        cards.append(
            {
                "key": "supervision",
                "status": "upcoming",
                "metric": "待首跑" if parts.get("supervision") else None,
            }
        )
    return cards


def _db_collector(
    fn: Callable[[AsyncSession], Awaitable[Any]],
) -> Callable[[], Awaitable[Any]]:
    """DB 采集器包装：每个采集器独立开 session。

    SQLAlchemy AsyncSession 禁止并发操作——并行 gather 下共享同一 session
    会直接 InvalidRequestError；各开各的短命 session（池 10）互不干扰，
    事务边界即采集器边界（纯只读，无跨域事务需求）。
    """

    async def wrapped() -> Any:
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            return await fn(session)

    return wrapped


async def build_overview(
    *,
    digest_store: Any = None,
    collectors: dict[str, Callable[[], Awaitable[Any]]] | None = None,
) -> dict[str, Any]:
    """聚合入口：并行采集 + 单域降级。collectors 可整体注入（测试接缝）。"""
    default_collectors: dict[str, Callable[[], Awaitable[Any]]] = {
        "hazards": _db_collector(collect_hazards),
        "special_ops": _db_collector(collect_special_ops),
        "alarms": _db_collector(collect_alarms),
        "certs": _db_collector(collect_certs),
        "chemicals": _db_collector(collect_chemicals),
        "key_risk_ops": _db_collector(collect_key_risk_ops),
        "ehs": _db_collector(collect_ehs),
        "supervision": _db_collector(collect_supervision),
        "facility_tasks": _db_collector(collect_facility_tasks),
        # 四新域（四期 1-B）：无 DB 采集，读 bitable 配置/表格（未接入是常态）
        # goals 走标准核查引擎采集（需 DB：演练计数取数器；keyword-only 适配）
        "goals": _db_collector(lambda session: collect_goals_health(db=session)),
        "training-behavior": lambda: collect_domain_health("training-behavior"),
        "facilities": lambda: collect_domain_health("facilities"),
        "incidents": lambda: collect_domain_health("incidents"),
        # S2 卡采集状态摘要（60s TTL 缓存，ragplus 故障只降级不炸驾驶舱）
        "knowledge_base_s2": _db_collector(build_s2_metric),
        "digest": lambda: collect_digest(digest_store),
    }
    merged = {**default_collectors, **(collectors or {})}

    async def _run(
        name: str, fn: Callable[[], Awaitable[Any]]
    ) -> tuple[str, Any, None] | tuple[str, None, str]:
        try:
            # P1-6：单域 30s 超时——慢域（直读全量分页拉取）到点降级记 errors，
            # 不再拖死整轮（与工具层 120s 超时构成双保险）。DB 采集器各自
            # 独立开 session，wait_for 取消即整链关闭，不留半途 session。
            return name, await asyncio.wait_for(fn(), timeout=_DOMAIN_TIMEOUT), None
        except asyncio.TimeoutError:
            logger.warning("overview 采集超时 domain=%s timeout=%ss", name, _DOMAIN_TIMEOUT)
            return name, None, f"{name}: TimeoutError({_DOMAIN_TIMEOUT}s)"
        except Exception as exc:  # noqa: BLE001 —— 单域失败只降级不炸整页
            logger.warning("overview 采集降级 domain=%s: %r", name, exc)
            return name, None, f"{name}: {type(exc).__name__}"

    results = await asyncio.gather(*(_run(n, f) for n, f in merged.items()))
    parts = {name: value for name, value, _err in results}
    errors = [err for _n, _v, err in results if err]

    return {
        "date": _bj_today().isoformat(),
        "generated_at": datetime.now(UTC),
        "hazards": parts["hazards"],
        "special_ops": parts["special_ops"],
        "alarms": parts["alarms"],
        "certs": parts["certs"],
        "chemicals": parts["chemicals"],
        "key_risk_ops": parts["key_risk_ops"],
        "ehs": parts["ehs"],
        "facility_tasks": parts["facility_tasks"],
        "digest": parts["digest"],
        "module_health": _build_module_health(parts),
        "errors": errors,
    }
