"""聚合服务（S1 体系标准符合性核查）——直读核查表 → 取数 → 判定 → 分组汇总。

三态信封（照 domain_pages 口径）：
- not_connected：registry 未配置连接（核查表未建/未登记）
- live：读取成功，summary+groups 出数（判定引擎四态）
- degraded：连接有效但读取异常 → errors 标注

取数去重：同 (metric_key, 周期窗口) 只取一次数——多张标准行共享同一指标时
（如综合/专项与疏散各有两张行）不重复打源。唯一组合并行取数（2026-11-02
性能修复：55 行串行逐指标全量直读是总览 goals 域 30s 超时的根因）。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.standard_check.engine import (
    ST_IN_PROGRESS,
    ST_MISSED,
    ST_NO_DATA,
    ST_OK,
    MetricOutcome,
    PeriodWindow,
    StandardRow,
    Verdict,
    format_target,
    judge,
    window_for,
)
from app.modules.safety.service.standard_check.metrics import MetricContext, get_metric

logger = logging.getLogger(__name__)

DOMAIN = "goals"
KIND = "standard_check"

ELEMENT_ORDER = (
    "目标职责", "制度化管理", "教育培训", "现场管理",
    "风险管控与隐患治理", "应急管理", "事故管理", "持续改进",
)
ELEMENT_OTHER = "其他"

FIELD_NAMES = (
    "标准编号", "年度", "标准条款", "依据", "要素归属", "指标键", "比较符",
    "目标值", "单位", "周期", "责任部门", "责任人", "上次完成日期",
    "人工核查结果", "备注",
)


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("fields") or {}


def _parse_row(record: dict[str, Any]) -> StandardRow:
    f = _fields(record)
    last_done = bd_fields.datetime_ms(f, "上次完成日期")
    return StandardRow(
        record_id=str(record.get("record_id") or ""),
        no=bd_fields.text(f, "标准编号") or "",
        year=bd_fields.select(f, "年度") or "",
        clause=bd_fields.text(f, "标准条款") or "",
        basis=bd_fields.text(f, "依据") or None,
        element=bd_fields.select(f, "要素归属") or None,
        metric_key=bd_fields.select(f, "指标键") or None,
        operator=bd_fields.select(f, "比较符") or None,
        target_value=_float_or_none(bd_fields.text(f, "目标值")),
        unit=bd_fields.select(f, "单位") or None,
        period=bd_fields.select(f, "周期") or None,
        department=tuple(bd_fields.multi(f, "责任部门")),
        owner=bd_fields.person(f, "责任人"),
        last_done_on=(last_done + timedelta(hours=8)).date() if last_done else None,
        manual_result=bd_fields.select(f, "人工核查结果") or None,
    )


def _float_or_none(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _row_payload(row: StandardRow, verdict: Any) -> dict[str, Any]:
    target = format_target(row.operator, row.target_value, row.unit)
    return {
        "record_id": row.record_id,
        "no": row.no,
        "clause": row.clause,
        "basis": row.basis,
        "element": row.element,
        "metric_key": row.metric_key,
        "period": row.period,
        "target_display": target,
        "department": list(row.department),
        "owner": row.owner,
        "auto": bool(row.metric_key),
        "status": verdict.status,
        "actual_display": verdict.actual_display,
        "residual_days": verdict.residual_days,
        "note": verdict.note,
    }


def _summary(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        ST_OK: 0, ST_IN_PROGRESS: 0, ST_MISSED: 0, ST_NO_DATA: 0,
    }
    for p in payloads:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    judged = counts[ST_OK] + counts[ST_MISSED]
    return {
        "total": len(payloads),
        "ok": counts[ST_OK],
        "in_progress": counts[ST_IN_PROGRESS],
        "missed": counts[ST_MISSED],
        "no_data": counts[ST_NO_DATA],
        "compliance_rate": round(counts[ST_OK] * 100 / judged) if judged else None,
    }


def _group(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for p in payloads:
        element = p["element"] if p["element"] in ELEMENT_ORDER else ELEMENT_OTHER
        buckets.setdefault(element, []).append(p)
    ordered = [e for e in (*ELEMENT_ORDER, ELEMENT_OTHER) if e in buckets]
    return [{"element": e, "rows": buckets[e]} for e in ordered]


def _envelope(
    status: str,
    summary: dict[str, Any] | None,
    groups: list[dict[str, Any]],
    errors: list[str],
    departments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "groups": groups,
        "departments": departments or [],
        "errors": errors,
    }


DEPT_UNASSIGNED = "未指派"


def _departments(
    rows: list[StandardRow], payloads: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """部门×四态汇总（联合责任：一行多部门计入每个部门；无部门行归「未指派」）。"""
    by_record = {p["record_id"]: p for p in payloads}
    agg: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = by_record.get(row.record_id)
        if payload is None:
            continue
        names = list(row.department) or [DEPT_UNASSIGNED]
        for name in names:
            bucket = agg.setdefault(
                name,
                {"name": name, "total": 0, "ok": 0, "in_progress": 0,
                 "missed": 0, "no_data": 0},
            )
            bucket["total"] += 1
            bucket[payload["status"]] += 1
    return sorted(
        agg.values(),
        key=lambda d: (-d["missed"], -d["total"], d["name"]),
    )


async def _collect_verdicts(
    rows: list[StandardRow],
    ctx: MetricContext,
    today: date,
    window_of: Callable[[StandardRow], PeriodWindow],
) -> list[tuple[StandardRow, MetricOutcome, Verdict]]:
    """逐行判定共享内核（实时页与周期定格共用）。

    window_of 由调用方注入：实时视图=window_for(period, today)（窗口恒含 today）；
    定格=目标历史周期窗口（评估日=定格日，engine ended 分支出终态）。
    同 (metric_key, 窗口) 取数去重——多行共享指标/多目标共享窗口不重复打源；
    唯一组合 asyncio.gather 并行取数（信号量限宽，防瞬间打爆 Bitable）。
    """
    # ctx.db 可能被多个指标共享（演练计数等 PG 查询）——SQLAlchemy 会话禁
    # 并发，包一层锁代理把 execute 串行化；Bitable 直读指标不触 db 不受影响
    locked_ctx = (
        MetricContext(db=cast(Any, _LockedDB(ctx.db)), opener=ctx.opener)
        if ctx.db is not None
        else ctx
    )

    combos: dict[tuple[str, str], tuple[str, PeriodWindow]] = {}
    for row in rows:
        if not row.metric_key:
            continue
        window = window_of(row)
        combos[(row.metric_key, window.key)] = (row.metric_key, window)

    outcome_cache: dict[tuple[str, str], MetricOutcome] = {}
    sem = asyncio.Semaphore(_METRIC_CONCURRENCY)

    async def _compute(key: str, window: PeriodWindow) -> None:
        metric = get_metric(key)
        async with sem:
            outcome = (
                await metric.compute(window, locked_ctx)
                if metric
                else MetricOutcome(no_data_reason="指标未注册")
            )
        outcome_cache[(key, window.key)] = outcome

    if combos:
        await asyncio.gather(*(
            _compute(key, window) for key, window in combos.values()
        ))

    triples: list[tuple[StandardRow, MetricOutcome, Verdict]] = []
    for row in rows:
        metric = get_metric(row.metric_key) if row.metric_key else None
        window = window_of(row)
        if not row.metric_key:
            outcome = MetricOutcome()
        else:
            outcome = outcome_cache[(row.metric_key, window.key)]
        verdict = judge(row, metric.spec if metric else None, outcome, window, today)
        triples.append((row, outcome, verdict))
    return triples


# 指标并行取数宽度（Bitable 全量直读路为主；太宽会瞬间压上飞书 API）
_METRIC_CONCURRENCY = 6


class _LockedDB:
    """AsyncSession 锁代理：并行 gather 下共享会话的禁并发保护。

    指标取数器只用 db.execute（PG 本地查询，串行代价可忽略）；属性透传
    内层会话，非调用点（如类型判断）不受影响。
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._lock = asyncio.Lock()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        async def _locked(*args: Any, **kwargs: Any) -> Any:
            async with self._lock:
                result = attr(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result

        return _locked


async def build_standard_check_page(
    *,
    db: Any | None = None,
    opener: Any | None = None,
    today: date | None = None,
    element: str | None = None,
    status: str | None = None,
    department: str | None = None,
    year: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """核查清单页数据（三态信封）+ 生产路径 TTL 结果缓存。

    缓存仅对生产装配（opener 未注入）生效，测试注入 opener/db 替身直算；
    force=True 绕过读缓存强制重算（后台预热刷新用），算完仍回填。
    """
    cacheable = opener is None and _PAGE_CACHE_TTL_SECONDS > 0
    cache_key = (
        today or _bj_today(), element or "", status or "", department or "",
        year,
    )
    if cacheable and not force:
        hit = _page_cache.get(cache_key)
        if hit is not None and time.monotonic() - hit[0] < _PAGE_CACHE_TTL_SECONDS:
            return hit[1]

    data = await _build_standard_check_page_uncached(
        db=db, opener=opener, today=today, element=element, status=status,
        department=department, year=year,
    )
    # 只缓存 live 信封：degraded/not_connected 是瞬态/未接入状态，缓存住
    # 会让恢复后的请求继续吃到旧降级（NOT_CONNECTED 缓存更会掩盖新接入）
    if cacheable and data.get("status") == "live":
        _page_cache[cache_key] = (time.monotonic(), data)
        if len(_page_cache) > _PAGE_CACHE_MAX_ENTRIES:
            for key in sorted(_page_cache, key=lambda k: _page_cache[k][0]):
                _page_cache.pop(key, None)
                if len(_page_cache) <= _PAGE_CACHE_MAX_ENTRIES:
                    break
    return data


# ── 页面级 TTL 结果缓存（2026-11-02 性能修复 P1）────────────────────────
# goals 指标全量直读即使并行取数仍要 10s+；驾驶舱/核查页对分钟级陈旧不
# 敏感（月/季合规数字），缓存 + 后台预热让用户请求恒命中热数据。
_PAGE_CACHE_TTL_SECONDS = int(
    os.getenv("SAFETY_STANDARD_CHECK_PAGE_CACHE_TTL_SECONDS", "300")
)
_PAGE_CACHE_MAX_ENTRIES = 16
_page_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}


async def _build_standard_check_page_uncached(
    *,
    db: Any | None = None,
    opener: Any | None = None,
    today: date | None = None,
    element: str | None = None,
    status: str | None = None,
    department: str | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """核查清单页数据（三态信封）。年份口径=当年（北京日，默认）或指定年。

    筛选（T5）：year 年度 / element 要素归属 / status 四态 / department 责任部门
    （multi 包含）；部门汇总 departments：一行多部门计入每个部门（联合责任口径），
    无部门行归「未指派」。注意窗口仍按 today 计算——历史年份查看是二期 snapshot 的事，
    当前行集只按年份过滤。
    """
    today = today or _bj_today()
    open_client = opener or bd_reader.resolve_client

    try:
        client = open_client(DOMAIN, KIND)
        records = await bd_reader.fetch_all_records(
            client, field_names=FIELD_NAMES, strict=True
        )
    except BitableConfigError:
        return _envelope("not_connected", None, [], [])
    except Exception as exc:  # noqa: BLE001 —— 读取失败=降级，不炸端点
        logger.warning("标准核查页读取降级: %r", exc)
        return _envelope("degraded", None, [], ["standard_check: 读取失败"])

    rows = [_parse_row(r) for r in records]
    target_year = str(year if year is not None else today.year)
    rows = [r for r in rows if r.year == target_year]

    ctx = MetricContext(db=db, opener=opener)
    triples = await _collect_verdicts(
        rows, ctx, today, lambda row: window_for(row.period or "年度", today)
    )
    payloads = [_row_payload(row, verdict) for row, _outcome, verdict in triples]

    if element:
        payloads = [p for p in payloads if p["element"] == element]
    if status:
        payloads = [p for p in payloads if p["status"] == status]
    if department:
        payloads = [p for p in payloads if department in p["department"]]

    return _envelope(
        "live", _summary(payloads), _group(payloads), [],
        departments=_departments(rows, payloads),
    )


async def collect_goals_health(
    *,
    db: Any | None = None,
    opener: Any | None = None,
) -> dict[str, Any]:
    """总览健康度墙 goals 卡（照 domain_pages.collect_domain_health 信约）。"""
    data = await build_standard_check_page(db=db, opener=opener)
    if data["status"] == "not_connected":
        return {"connected": False}
    if data["status"] == "degraded":
        # 降级口径对齐 domain_pages.collect_domain_health：向上抛，由 overview
        # gather 归入降级（part=None → 健康度卡 inactive·无指标，不与未接入混淆）
        raise RuntimeError("goals 标准核查表读取降级")
    summary = data["summary"]
    return {
        "connected": True,
        "health_status": "warn" if summary["missed"] > 0 else "ok",
        "health_metric": (
            f"达标 {summary['ok']}/{summary['ok'] + summary['missed']} · "
            f"未达标 {summary['missed']} · 无数据 {summary['no_data']}"
        ),
    }




async def build_standard_evidence(
    record_id: str,
    *,
    db: Any | None = None,
    opener: Any | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """单条标准的证据明细（点开凭据时调用；重算该行一次取数）。"""
    today = today or _bj_today()
    open_client = opener or bd_reader.resolve_client
    try:
        client = open_client(DOMAIN, KIND)
        records = await bd_reader.fetch_all_records(
            client, field_names=FIELD_NAMES, strict=True
        )
    except BitableConfigError:
        return {"status": "not_connected", "evidence": [], "no_data_reason": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("标准核查证据读取降级: %r", exc)
        return {"status": "degraded", "evidence": [], "no_data_reason": None}

    record = next((r for r in records if str(r.get("record_id")) == record_id), None)
    if record is None:
        return {"status": "not_found", "evidence": [], "no_data_reason": None}

    row = _parse_row(record)
    metric = get_metric(row.metric_key) if row.metric_key else None
    window = window_for(row.period or "年度", today)
    if row.metric_key:
        outcome = (
            await metric.compute(window, MetricContext(db=db, opener=opener))
            if metric
            else MetricOutcome(no_data_reason="指标未注册（依赖对应域接入）")
        )
    else:
        outcome = MetricOutcome()
    verdict = judge(row, metric.spec if metric else None, outcome, window, today)
    return {
        "status": "live",
        "record_id": row.record_id,
        "no": row.no,
        "clause": row.clause,
        "metric_key": row.metric_key,
        "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "verdict_status": verdict.status,
        "actual_display": verdict.actual_display,
        "evidence": [dict(e) for e in outcome.evidence],
        "no_data_reason": outcome.no_data_reason,
    }
