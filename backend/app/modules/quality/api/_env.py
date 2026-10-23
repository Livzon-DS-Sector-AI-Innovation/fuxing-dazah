"""环境监测 API：监测点台账 + 监测记录填报（警戒限/行动限双限三态判定）。

判定规则：超行动限 action（🚨 群预警）> 超警戒限 alert（台账标黄）> 其余 pass。
"""

import uuid
from io import BytesIO
from typing import Any
from urllib.parse import quote

from fastapi import Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.quality.api._common import router
from app.modules.quality.repository import (
    create_env_point,
    create_env_record,
    delete_env_point,
    delete_env_record,
    env_trend,
    get_env_point,
    handle_env_record,
    list_env_points,
    list_env_records,
    update_env_point,
)
from app.modules.quality.schemas import (
    EnvPointCreate,
    EnvPointOut,
    EnvPointUpdate,
    EnvRecordCreate,
    EnvRecordHandle,
    EnvRecordOut,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

MONITOR_TYPE_LABELS = {
    "settle": "沉降菌",
    "float": "浮游菌",
    "particle": "悬浮粒子",
    "temp_humidity": "温湿度",
    "pressure": "压差",
}
MONITOR_TYPE_CODES = {v: k for k, v in MONITOR_TYPE_LABELS.items()}
FREQ_LABELS = {"per_batch": "每批", "weekly": "每周", "monthly": "每月"}
FREQ_CODES = {v: k for k, v in FREQ_LABELS.items()}


def _env_judge(value: float | None, alert: float | None, action: float | None) -> str | None:
    """双限三态判定：超行动限 action / 超警戒限 alert / 其余 pass；无值不判定。"""
    if value is None:
        return None
    if action is not None and value > action:
        return "action"
    if alert is not None and value > alert:
        return "alert"
    return "pass"


async def _notify_env_action(room: str, point_no: str, monitor_type: str, record_date: str, value: float, action: float) -> None:
    """超行动限：质量群 🚨 预警（即时，独立于每日推送）。"""
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    label = MONITOR_TYPE_LABELS.get(monitor_type, monitor_type)
    text = (
        f"🚨 环境监测超行动限：{room} {point_no}（{label}）{record_date} "
        f"结果 {value}，行动限 {action}，请立即处理并评估是否发起偏差"
    )
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            pass


# ─── 监测点台账 ───


@router.get("/env/points", summary="环境监测点台账列表")
async def list_env_points_endpoint(
    room: str | None = Query(default=None, description="房间/区域模糊"),
    monitor_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None, description="点位编号模糊"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:env:read")),
) -> JSONResponse:
    rows = await list_env_points(db, room=room, monitor_type=monitor_type, status=status, keyword=keyword)
    items = [EnvPointOut.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@router.post("/env/points", summary="新增环境监测点", status_code=201)
async def create_env_point_endpoint(
    payload: EnvPointCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:env:manage")),
) -> JSONResponse:
    dup = [
        p for p in await list_env_points(db, room=payload.room, monitor_type=payload.monitor_type)
        if p.point_no == payload.point_no
    ]
    if dup:
        raise HTTPException(status_code=409, detail=f"房间 {payload.room} 已有点位 {payload.point_no}，请直接编辑")
    point = await create_env_point(db, {**payload.model_dump(), "created_by": user.id})
    return success_response(
        data=EnvPointOut.model_validate(point).model_dump(mode="json"),
        message="监测点已保存", status_code=201,
    )


@router.put("/env/points/{point_id}", summary="更新环境监测点")
async def update_env_point_endpoint(
    point_id: uuid.UUID,
    payload: EnvPointUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:env:manage")),
) -> JSONResponse:
    point = await get_env_point(db, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="监测点不存在")
    updated = await update_env_point(db, point_id, {**payload.model_dump(exclude_none=True), "updated_by": user.id})
    return success_response(
        data=EnvPointOut.model_validate(updated).model_dump(mode="json"),
        message="监测点已更新",
    )


@router.delete("/env/points/{point_id}", summary="删除环境监测点（软删除）")
async def delete_env_point_endpoint(
    point_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:env:manage")),
) -> JSONResponse:
    if not await delete_env_point(db, point_id):
        raise HTTPException(status_code=404, detail="监测点不存在")
    return success_response(message="已删除")


# ─── 监测记录 ───


@router.get("/env/trend", summary="点位监测趋势（近 N 天时间序列 + 警戒/行动限）")
async def env_trend_endpoint(
    point_id: uuid.UUID = Query(..., description="监测点"),
    days: int = Query(default=90, ge=7, le=730, description="近 N 天"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:env:read")),
) -> JSONResponse:
    data = await env_trend(db, point_id, days)
    if data is None:
        raise HTTPException(status_code=404, detail="监测点不存在")
    return success_response(data=data)


@router.get("/env/records", summary="环境监测记录列表")
async def list_env_records_endpoint(
    point_id: uuid.UUID | None = Query(default=None),
    judge: str | None = Query(default=None, description="pass/alert/action"),
    date_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    handle_status: str | None = Query(default=None, description="open 未处理 / handled 已处理"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:env:read")),
) -> JSONResponse:
    items = await list_env_records(
        db, point_id=point_id, judge=judge, date_from=date_from, date_to=date_to,
        handle_status=handle_status,
    )
    return success_response(data=[EnvRecordOut.model_validate(i).model_dump(mode="json") for i in items])


@router.post("/env/records", summary="填报环境监测记录（按点位双限自动判定）", status_code=201)
async def create_env_record_endpoint(
    payload: EnvRecordCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:env:manage")),
) -> JSONResponse:
    point = await get_env_point(db, payload.point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="监测点不存在")
    if point.status != "active":
        raise HTTPException(status_code=400, detail="监测点已停用，请先启用")
    judge = _env_judge(payload.result_value, point.alert_limit, point.action_limit)
    rec = await create_env_record(db, {
        "point_id": point.id,
        "record_date": payload.record_date,
        "result_value": payload.result_value,
        "alert_limit": point.alert_limit,
        "action_limit": point.action_limit,
        "judge": judge,
        "recorded_by": user.id,
        "created_by": user.id,
        "remark": payload.remark,
    })
    await db.commit()
    if judge == "action" and payload.result_value is not None and point.action_limit is not None:
        from app.modules.quality.service import spawn_background

        spawn_background(_notify_env_action(
            point.room, point.point_no, point.monitor_type,
            payload.record_date, payload.result_value, point.action_limit,
        ))
    rows = await list_env_records(db, point_id=point.id)
    item = next((r for r in rows if r["id"] == rec.id), None)
    return success_response(
        data=EnvRecordOut.model_validate(item).model_dump(mode="json") if item else None,
        message={
            "pass": "记录已保存（合格）",
            "alert": "记录已保存（超警戒限，请关注）",
            "action": "记录已保存（超行动限，已群预警）",
        }.get(judge or "", "记录已保存"),
        status_code=201,
    )


@router.delete("/env/records/{record_id}", summary="删除环境监测记录（软删除，填报纠错用）")
async def delete_env_record_endpoint(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:env:manage")),
) -> JSONResponse:
    if not await delete_env_record(db, record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return success_response(message="已删除")


@router.post("/env/records/{record_id}/handle", summary="超行动限记录闭环：标记已处理（处理人/日期自动记录）")
async def handle_env_record_endpoint(
    record_id: uuid.UUID,
    payload: EnvRecordHandle = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:env:manage")),
) -> JSONResponse:
    from app.core.time import today as _today
    from app.modules.quality.repository import get_env_record

    rec = await get_env_record(db, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if rec.judge != "action":
        raise HTTPException(status_code=400, detail="仅超行动限记录需要闭环处理")
    if rec.handle_status == "handled":
        raise HTTPException(status_code=409, detail="该记录已标记处理")
    await handle_env_record(db, record_id, {
        "handle_status": "handled",
        "handled_at": _today().isoformat(),
        "handled_by": user.id,
        "handled_remark": payload.handled_remark,
        "updated_by": user.id,
    })
    return success_response(
        data=EnvRecordOut.model_validate(
            next(
                (r for r in await list_env_records(db, point_id=rec.point_id) if r["id"] == rec.id),
                None,
            )
        ).model_dump(mode="json"),
        message="已标记处理（处理人/日期已留痕）",
    )


@router.get("/env/records/export", summary="环境监测记录导出 Excel")
async def export_env_records_endpoint(
    point_id: uuid.UUID | None = Query(default=None),
    judge: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:env:read")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    rows = await list_env_records(db, point_id=point_id, judge=judge, date_from=date_from, date_to=date_to)
    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    ws.title = "环境监测记录"
    ws.append(["房间", "点位", "类型", "监测日期", "结果值", "警戒限", "行动限", "判定", "处理状态", "处理日期", "处理人", "处理说明", "填报人", "备注"])
    judge_label = {"pass": "合格", "alert": "超警戒", "action": "超行动"}
    for r in rows:
        ws.append([
            r["room"], r["point_no"], MONITOR_TYPE_LABELS.get(r["monitor_type"], r["monitor_type"]),
            r["record_date"],
            r["result_value"] if r["result_value"] is not None else "-",
            r["alert_limit"] if r["alert_limit"] is not None else "-",
            r["action_limit"] if r["action_limit"] is not None else "-",
            judge_label.get(r["judge"] or "", r["judge"] or "-"),
            "已处理" if r["handle_status"] == "handled" else "未处理",
            r["handled_at"] or "-",
            r["handled_by_name"] or "-",
            r["handled_remark"] or "-",
            r["recorded_by_name"] or "-",
            r["remark"] or "-",
        ])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote("环境监测记录.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="env.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


# ─── Excel 批量导入 ───


@router.get("/env/import-template", summary="环境监测导入模板下载（points=监测点 / records=监测记录）")
async def env_import_template_endpoint(
    type_: str = Query(default="points", alias="type", description="points / records"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:env:read")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    if type_ == "records":
        ws.title = "监测记录导入"
        ws.append(["房间", "点位编号", "监测日期", "结果值", "备注"])
        ws.append(["灌装间", "P-001", "2026-10-23", 3, "示例行，导入前删除"])
        filename = "环境监测记录导入模板.xlsx"
    else:
        ws.title = "监测点导入"
        ws.append(["房间", "点位编号", "监测类型", "频次", "警戒限", "行动限", "备注"])
        ws.append(["灌装间", "P-001", "沉降菌", "每周", 5, 10, "示例行，导入前删除"])
        filename = "环境监测点导入模板.xlsx"
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote(filename)
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="env-import.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


@router.post("/env/points/import", summary="批量导入监测点（Excel，逐行校验，重复跳过）")
async def import_env_points_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:env:manage")),
) -> JSONResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    content = await file.read()
    wb = openpyxl.load_workbook(_io.BytesIO(content))
    ws = lc_template_parser.active_sheet(wb)
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        raise HTTPException(status_code=400, detail="Excel 为空或缺少表头")
    created = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(rows_iter, start=2):
        if not raw or all(v is None or str(v).strip() == "" for v in raw):
            continue
        room, point_no, type_label, freq_label, alert_v, action_v, remark = (list(raw) + [None] * 7)[:7]
        room = str(room or "").strip()
        point_no = str(point_no or "").strip()
        monitor_type = MONITOR_TYPE_CODES.get(str(type_label or "").strip(), "")
        frequency = FREQ_CODES.get(str(freq_label or "").strip())
        if not room or not point_no:
            errors.append({"row": idx, "reason": "房间/点位编号为空"})
            continue
        if not monitor_type:
            errors.append({"row": idx, "reason": f"监测类型「{type_label}」无法识别（沉降菌/浮游菌/悬浮粒子/温湿度/压差）"})
            continue
        dup = [
            p for p in await list_env_points(db, room=room, monitor_type=monitor_type)
            if p.point_no == point_no
        ]
        if dup:
            skipped += 1
            continue
        def _num(v: object) -> float | None:
            try:
                return float(str(v).strip()) if v is not None and str(v).strip() != "" else None
            except (TypeError, ValueError):
                return None

        await create_env_point(db, {
            "room": room, "point_no": point_no, "monitor_type": monitor_type,
            "frequency": frequency, "alert_limit": _num(alert_v), "action_limit": _num(action_v),
            "remark": str(remark).strip() if remark else None, "created_by": user.id,
        })
        created += 1
    return success_response(
        data={"created": created, "skipped": skipped, "errors": errors},
        message=f"导入完成：新增 {created}，跳过重复 {skipped}" + (f"，错误 {len(errors)} 行" if errors else ""),
    )


@router.post("/env/records/import", summary="批量导入监测记录（Excel，按房间+点位匹配，自动判定）")
async def import_env_records_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:env:manage")),
) -> JSONResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    content = await file.read()
    wb = openpyxl.load_workbook(_io.BytesIO(content))
    ws = lc_template_parser.active_sheet(wb)
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        raise HTTPException(status_code=400, detail="Excel 为空或缺少表头")
    created = 0
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(rows_iter, start=2):
        if not raw or all(v is None or str(v).strip() == "" for v in raw):
            continue
        room, point_no, date_str, value_v, remark = (list(raw) + [None] * 5)[:5]
        room = str(room or "").strip()
        point_no = str(point_no or "").strip()
        date_str = str(date_str or "").strip()[:10]
        if not room or not point_no or not date_str:
            errors.append({"row": idx, "reason": "房间/点位编号/监测日期为空"})
            continue
        matched = [
            p for p in await list_env_points(db, room=room)
            if p.point_no == point_no and p.status == "active"
        ]
        if len(matched) != 1:
            errors.append({"row": idx, "reason": f"点位 {point_no} 在房间 {room} 未找到或停用"})
            continue
        point = matched[0]
        try:
            value = float(str(value_v).strip()) if value_v is not None and str(value_v).strip() != "" else None
        except (TypeError, ValueError):
            errors.append({"row": idx, "reason": f"结果值「{value_v}」不是数字"})
            continue
        await create_env_record(db, {
            "point_id": point.id, "record_date": date_str, "result_value": value,
            "alert_limit": point.alert_limit, "action_limit": point.action_limit,
            "judge": _env_judge(value, point.alert_limit, point.action_limit),
            "recorded_by": user.id, "created_by": user.id,
            "remark": str(remark).strip() if remark else None,
        })
        created += 1
    return success_response(
        data={"created": created, "errors": errors},
        message=f"导入完成：新增 {created} 条记录" + (f"，错误 {len(errors)} 行" if errors else ""),
    )
