"""Safety API — 特种设备遥测监控（facilities-p2）。

- 票 01：GET /telemetry/latest（实时读数）、GET /telemetry/history（趋势序列）；
- 票 02：GET /telemetry/rules（生效规则）、GET /telemetry/alarms（报警列表）；
- 票 04：POST /telemetry/alarms/{id}/ack · resolve（处置闭环）、
  GET /telemetry/pending-reviews · POST /{id}/confirm（人工补录）。
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.models import TelemetryAlarmRecord
from app.modules.safety.schemas.telemetry import (
    TelemetryAlarmAckIn,
    TelemetryAlarmResolveIn,
    TelemetryHistoryOut,
    TelemetryLatestOut,
    TelemetryPendingConfirmIn,
)
from app.modules.safety.telemetry.lifecycle import (
    AlarmStateError,
    ack_alarm,
    confirm_pending_review,
    get_alarm,
    list_pending_reviews,
    resolve_alarm,
)
from app.modules.safety.telemetry.query import history_series, latest_values
from app.modules.safety.telemetry.rules import effective_rules
from app.shared.schemas import ApiResponse

telemetry_router = APIRouter()


def _alarm_out(r: TelemetryAlarmRecord) -> dict:
    """报警行出参（列表与处置端点共用，单一序列化点）。"""
    return {
        "id": str(r.id),
        "equipment_no": r.equipment_no,
        "metric": r.metric,
        "value": r.value,
        "recorded_at": r.recorded_at,
        "rule_desc": r.rule_desc,
        "level": r.level,
        "status": r.status,
        "acked_at": r.acked_at,
        "acked_by": r.acked_by,
        "resolved_at": r.resolved_at,
        "resolution_note": r.resolution_note,
        "created_at": r.created_at,
    }


# history 缺省窗口：近 7 天（抄表密度下足够覆盖复盘）
_DEFAULT_WINDOW_DAYS = 7


def _parse_dt(raw: str | None, *, field: str) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} 时间格式非法（需 ISO 8601）") from None


@telemetry_router.get(
    "/telemetry/latest",
    response_model=ApiResponse,
    summary="实时读数（每设备每指标最新值）",
)
async def get_telemetry_latest(
    equipment_no: str | None = Query(None),
    db=Depends(get_db),
) -> ApiResponse:
    items = await latest_values(db, equipment_no=equipment_no)
    return ApiResponse(data=TelemetryLatestOut(items=items).model_dump(mode="json"))


@telemetry_router.get(
    "/telemetry/history",
    response_model=ApiResponse,
    summary="趋势序列（按小时/按日桶聚合）",
)
async def get_telemetry_history(
    equipment_no: str = Query(..., min_length=1),
    metric: str = Query(..., min_length=1),
    interval: str = Query("hour", pattern="^(hour|day)$"),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    db=Depends(get_db),
) -> ApiResponse:
    now = datetime.now(timezone.utc)
    start = _parse_dt(from_, field="from") or (now - timedelta(days=_DEFAULT_WINDOW_DAYS))
    end = _parse_dt(to, field="to") or now
    if start > end:
        raise HTTPException(status_code=422, detail="from 不得晚于 to")
    try:
        points = await history_series(
            db, equipment_no, metric, from_=start, to=end, interval=interval
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data = TelemetryHistoryOut(
        equipment_no=equipment_no, metric=metric, interval=interval, points=points
    )
    return ApiResponse(data=data.model_dump(mode="json"))


@telemetry_router.get(
    "/telemetry/rules",
    response_model=ApiResponse,
    summary="当前生效阈值规则（代码默认+app_config 覆写合并后）",
)
async def get_telemetry_rules() -> ApiResponse:
    override = _app_config_store.get_str("SAFETY_TELEMETRY_RULES", "")
    rules = effective_rules(override or None)
    default_keys = {
        (r.metric, r.equipment_no, r.category) for r in effective_rules(None)
    }
    items = [
        {
            **r.to_dict(),
            "source": "default" if (r.metric, r.equipment_no, r.category) in default_keys else "override",
        }
        for r in rules
    ]
    return ApiResponse(data={"items": items})


@telemetry_router.get(
    "/telemetry/alarms",
    response_model=ApiResponse,
    summary="报警列表（状态筛选 + 分页，时间倒序）",
)
async def get_telemetry_alarms(
    status: str | None = Query(None, pattern="^(firing|acked|resolved)$"),
    equipment_no: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
) -> ApiResponse:
    from sqlalchemy import func

    stmt = select(TelemetryAlarmRecord).where(TelemetryAlarmRecord.is_deleted.is_(False))
    if status:
        stmt = stmt.where(TelemetryAlarmRecord.status == status)
    if equipment_no:
        stmt = stmt.where(TelemetryAlarmRecord.equipment_no == equipment_no)
    total = int(
        await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    )
    rows = (
        await db.execute(
            stmt.order_by(TelemetryAlarmRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return ApiResponse(
        data={
            "items": [_alarm_out(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


def _operator_of(current_user: CurrentUser | None) -> str:
    return getattr(current_user, "open_id", None) or "admin"


@telemetry_router.post(
    "/telemetry/alarms/{alarm_id}/ack",
    response_model=ApiResponse,
    summary="值班确认（firing → acked，留痕）",
)
async def ack_telemetry_alarm(
    alarm_id: uuid.UUID,
    payload: TelemetryAlarmAckIn | None = None,
    db=Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    alarm = await get_alarm(db, alarm_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="报警不存在")
    try:
        await ack_alarm(db, alarm, operator=_operator_of(current_user))
    except AlarmStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return ApiResponse(data=_alarm_out(alarm))


@telemetry_router.post(
    "/telemetry/alarms/{alarm_id}/resolve",
    response_model=ApiResponse,
    summary="处置关闭（acked → resolved，处置说明必填）",
)
async def resolve_telemetry_alarm(
    alarm_id: uuid.UUID,
    payload: TelemetryAlarmResolveIn,
    db=Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    note = (payload.note or "").strip()
    if not note:
        raise HTTPException(status_code=422, detail="处置说明必填")
    alarm = await get_alarm(db, alarm_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="报警不存在")
    try:
        await resolve_alarm(db, alarm, note=note, operator=_operator_of(current_user))
    except AlarmStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return ApiResponse(data=_alarm_out(alarm))


@telemetry_router.get(
    "/telemetry/pending-reviews",
    response_model=ApiResponse,
    summary="解析失败待补录列表（原文摘录 + 已抽出数值预填）",
)
async def list_telemetry_pending_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
) -> ApiResponse:
    items, total = await list_pending_reviews(db, page=page, page_size=page_size)
    return ApiResponse(
        data={"items": items, "total": total, "page": page, "page_size": page_size}
    )


@telemetry_router.post(
    "/telemetry/pending-reviews/{snapshot_id}/confirm",
    response_model=ApiResponse,
    summary="人工补录确认（pending 行转正为 manual 快照）",
)
async def confirm_telemetry_pending_review(
    snapshot_id: uuid.UUID,
    payload: TelemetryPendingConfirmIn,
    db=Depends(get_db),
) -> ApiResponse:
    equipment_no = (payload.equipment_no or "").strip()
    if not equipment_no:
        raise HTTPException(status_code=422, detail="设备编号必填")
    if not payload.readings:
        raise HTTPException(status_code=422, detail="至少补录一条读数")
    try:
        final = await confirm_pending_review(
            db, snapshot_id, equipment_no=equipment_no, readings=payload.readings
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AlarmStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return ApiResponse(
        data={
            "confirmed": True,
            "snapshots": [
                {
                    "id": str(s.id),
                    "equipment_no": s.equipment_no,
                    "metric": s.metric,
                    "value": s.value,
                    "unit": s.unit,
                    "recorded_at": s.recorded_at,
                    "parse_method": s.parse_method,
                }
                for s in final
            ],
        }
    )
