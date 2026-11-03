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
    BatchReleaseCreate,
    BatchReleaseOut,
    BatchReleaseRelease,
    EnvPointCreate,
    EnvPointOut,
    EnvPointUpdate,
    EnvRecordCreate,
    EnvRecordHandle,
    EnvRecordOut,
    ShiftConfigIn,
    ShiftTeamIn,
    ShiftTeamOut,
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


@router.get("/env/plans", summary="环境监测周期计划（某日应测清单，查看时自动补生成）")
async def env_plans_endpoint(
    date: str | None = Query(default=None, description="YYYY-MM-DD，默认今天"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:env:read")),
) -> JSONResponse:
    from datetime import date as _date

    from app.core.time import today as _today
    from app.modules.quality.repository import generate_env_plans, list_env_plans

    on_date = date or _today().isoformat()
    try:
        _date.fromisoformat(on_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="date 格式应为 YYYY-MM-DD")
    await generate_env_plans(db, on_date)
    items = await list_env_plans(db, on_date)
    return success_response(data={"date": on_date, "items": items})


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


# ─── 批放行记录 ───


async def _build_release_snapshot(db: AsyncSession, task_id: uuid.UUID) -> dict[str, object] | None:
    """发起放行时的检验汇总快照：判定/填报/复核/报告单/留样状态。"""
    from app.modules.quality.repository import (
        get_test_task,
        list_report_records_by_task,
        list_retained_samples,
        list_task_reviews_with_names,
        list_test_results,
    )

    task = await get_test_task(db, task_id)
    if task is None:
        return None
    rows = await list_test_results(db, task.id)
    filled = sum(1 for r in rows if r.is_pass is not None)
    reviews = await list_task_reviews_with_names(db, task.id)
    reports = await list_report_records_by_task(db, task.id)
    retained = await list_retained_samples(db, batch_no=task.batch_number)
    ret = retained[0] if retained and retained[0].batch_no == task.batch_number else None
    return {
        "task_status": task.status,
        "all_pass": all(r.is_pass for r in rows if r.is_pass is not None) if rows else None,
        "filled": filled,
        "total": len(rows),
        "reviewers": [r["reviewer_name"] for r in reviews if r.get("reviewer_name")],
        "report_serials": [r.serial_no for r in reports if r.serial_no],
        "retained": (
            {
                "qty": ret.qty, "location": ret.location,
                "destroy_due_date": ret.destroy_due_date, "status": ret.status,
            }
            if ret else None
        ),
    }


@router.post("/release-records", summary="发起批放行（已完成检验任务 → 放行记录 + 汇总快照）", status_code=201)
async def create_batch_release_endpoint(
    payload: BatchReleaseCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    from app.modules.quality.repository import (
        create_batch_release,
        get_batch_release_by_batch,
        get_test_task,
    )

    task = await get_test_task(db, payload.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="检验任务不存在")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail=f"任务状态为 {task.status}，仅已完成任务可发起放行")
    existing = await get_batch_release_by_batch(db, task.batch_number)
    if existing:
        raise HTTPException(status_code=409, detail=f"批号 {task.batch_number} 已有放行记录（{existing.status}），请直接处理")
    snapshot = await _build_release_snapshot(db, task.id)
    rec = await create_batch_release(db, {
        "batch_no": task.batch_number,
        "product_name": task.product_name,
        "task_id": task.id,
        "snapshot": snapshot,
        "remark": payload.remark,
        "created_by": user.id,
    })
    return success_response(
        data=BatchReleaseOut.model_validate(rec).model_dump(mode="json"),
        message="放行记录已创建（含检验汇总快照）", status_code=201,
    )


@router.get("/release-records", summary="批放行记录列表")
async def list_batch_releases_endpoint(
    batch_no: str | None = Query(default=None),
    status: str | None = Query(default=None, description="pending/released"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:report:read")),
) -> JSONResponse:
    from app.modules.quality.repository import list_batch_releases

    rows = await list_batch_releases(db, batch_no=batch_no, status=status)
    items = []
    for r in rows:
        item = BatchReleaseOut.model_validate(r).model_dump(mode="json")
        if r.released_by:
            from app.platform.identity.repository import UserRepository

            u = await UserRepository().get_by_id(db, r.released_by)
            item["released_by_name"] = u.name if u else None
        items.append(item)
    return success_response(data=items)


@router.post("/release-records/{record_id}/release", summary="专员放行（记录放行人/日期/备注）")
async def release_batch_record_endpoint(
    record_id: uuid.UUID,
    payload: BatchReleaseRelease = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    from app.core.time import today as _today
    from app.modules.quality.repository import get_batch_release, update_batch_release

    rec = await get_batch_release(db, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="放行记录不存在")
    if rec.status != "pending":
        raise HTTPException(status_code=400, detail=f"放行记录状态为 {rec.status}，不可放行")
    updated = await update_batch_release(db, record_id, {
        "status": "released",
        "released_by": user.id,
        "released_at": _today().isoformat(),
        "release_remark": payload.release_remark,
        "updated_by": user.id,
    })
    return success_response(
        data=BatchReleaseOut.model_validate(updated).model_dump(mode="json"),
        message="已放行（放行人/日期已留痕）",
    )


# ─── 排班班组与轮换 ───


@router.get("/shift/teams", summary="排班班组列表（含成员姓名）")
async def list_shift_teams_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:read")),
) -> JSONResponse:
    from app.modules.quality.repository import list_shift_teams

    teams = await list_shift_teams(db)
    items = []
    for t in teams:
        ids = t.member_ids or []
        names: list[str] = []
        if ids:
            from sqlalchemy import select as _select

            from app.platform.identity.models import User as IdentityUser

            stmt = _select(IdentityUser).where(IdentityUser.id.in_(ids))
            name_map = {str(u.id): u.name for u in (await db.execute(stmt)).scalars()}
            names = [name_map.get(str(i), "未知") for i in ids]
        items.append(ShiftTeamOut(
            id=t.id, name=t.name, group_key=t.group_key,
            member_ids=[str(i) for i in ids],
            member_names=names, seq=t.seq, remark=t.remark,
        ).model_dump(mode="json"))
    return success_response(data=items)


@router.post("/shift/teams", summary="新增排班班组", status_code=201)
async def create_shift_team_endpoint(
    payload: ShiftTeamIn = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    from app.modules.quality.repository import upsert_shift_team, user_shift_groups

    # 组别权限：编入班组的用户只能管理本组班组
    groups = await user_shift_groups(db, user.id)
    if groups and payload.group_key not in groups:
        raise HTTPException(status_code=403, detail="只能管理本组班组")

    team = await upsert_shift_team(db, None, {
        "name": payload.name, "group_key": payload.group_key,
        "member_ids": [str(i) for i in payload.member_ids],
        "seq": payload.seq, "remark": payload.remark, "created_by": user.id,
    })
    return success_response(data={"id": str(team.id), "name": team.name}, message="班组已保存", status_code=201)


@router.put("/shift/teams/{team_id}", summary="更新排班班组")
async def update_shift_team_endpoint(
    team_id: uuid.UUID,
    payload: ShiftTeamIn = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    from app.modules.quality.repository import (
        get_shift_team,
        upsert_shift_team,
        user_shift_groups,
    )

    # 组别权限：编入班组的用户只能管理本组班组
    groups = await user_shift_groups(db, user.id)
    if groups:
        existing = await get_shift_team(db, team_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="班组不存在")
        if existing.group_key not in groups or payload.group_key not in groups:
            raise HTTPException(status_code=403, detail="只能管理本组班组")

    team = await upsert_shift_team(db, team_id, {
        "name": payload.name, "group_key": payload.group_key,
        "member_ids": [str(i) for i in payload.member_ids],
        "seq": payload.seq, "remark": payload.remark, "updated_by": user.id,
    })
    return success_response(data={"id": str(team.id), "name": team.name}, message="班组已更新")


@router.delete("/shift/teams/{team_id}", summary="删除排班班组（软删除）")
async def delete_shift_team_endpoint(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    from app.modules.quality.repository import (
        delete_shift_team,
        get_shift_team,
        user_shift_groups,
    )

    # 组别权限：编入班组的用户只能管理本组班组
    groups = await user_shift_groups(db, user.id)
    if groups:
        existing = await get_shift_team(db, team_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="班组不存在")
        if existing.group_key not in groups:
            raise HTTPException(status_code=403, detail="只能管理本组班组")

    if not await delete_shift_team(db, team_id):
        raise HTTPException(status_code=404, detail="班组不存在")
    return success_response(message="已删除")


@router.get("/shift/config", summary="排班轮换配置")
async def get_shift_config_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:read")),
) -> JSONResponse:
    from app.modules.quality.repository import get_shift_config

    cfg = await get_shift_config(db, "rotation")
    default: dict[str, Any] = {"start_date": None, "period_days": 3, "duty_teams": 2, "team_order": []}
    return success_response(data=cfg.value if cfg and cfg.value else default)


@router.put("/shift/config", summary="保存排班轮换配置（group 为空=全局，否则按组）")
async def save_shift_config_endpoint(
    payload: ShiftConfigIn = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    from app.modules.quality.repository import upsert_shift_config, user_shift_groups

    # 组别权限：轮换配置为全局设置，编入班组的用户不可修改
    if await user_shift_groups(db, user.id):
        raise HTTPException(status_code=403, detail="轮换配置为全局设置，仅管理人员可修改")

    # 轮换顺序归一化：去空白、按原顺序去重
    team_order: list[str] = []
    for name in payload.team_order or []:
        n = name.strip()
        if n and n not in team_order:
            team_order.append(n)
    key = f"rotation:{payload.group}" if payload.group else "rotation"
    value = {
        "start_date": payload.start_date,
        "period_days": payload.period_days,
        "duty_teams": payload.duty_teams,
        "team_order": team_order,
    }
    await upsert_shift_config(db, key, value)
    return success_response(message="轮换配置已保存")


@router.get("/shift/groups", summary="组别概览（各组班组/轮换配置/当日当班成员）")
async def shift_groups_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:read")),
) -> JSONResponse:
    from app.core.time import today as _today
    from app.modules.quality.repository import (
        get_shift_config,
        group_duty,
        group_member_ids,
        list_shift_teams,
        user_shift_groups,
    )

    on_date = _today().isoformat()
    group_keys: list[str] = []
    for t in await list_shift_teams(db):
        if t.group_key not in group_keys:
            group_keys.append(t.group_key)
    cfg = await get_shift_config(db, "item_groups")
    mapping = (cfg.value if cfg else None) or {}
    for g in mapping:
        if g not in group_keys:
            group_keys.append(g)
    groups = []
    for g in group_keys:
        duty = await group_duty(db, g, on_date)
        members = duty["members"]
        all_ids = list(await group_member_ids(db, g))
        names: dict[str, str] = {}
        if members or all_ids:
            from sqlalchemy import select as _select

            from app.platform.identity.models import User as IdentityUser

            stmt = _select(IdentityUser).where(IdentityUser.id.in_(set(members) | set(all_ids)))
            names = {str(u.id): u.name for u in (await db.execute(stmt)).scalars()}
        groups.append({
            "group": g,
            "configured": duty["configured"],
            "teams": duty["teams"],
            "members": [{"id": i, "name": names.get(i, "未知")} for i in members],
            "all_members": [{"id": i, "name": names.get(i, "未知")} for i in all_ids],
        })
    # 组别范围：编入班组的用户只看到本组（前端据此隐藏其他组页签与全局配置页签）
    user_groups = await user_shift_groups(db, user.id)
    meta = {"scope_groups": sorted(user_groups)} if user_groups else None
    return success_response(data={"groups": groups, "mapping": mapping}, meta=meta)


@router.get("/shift/item-groups", summary="项目组别映射配置（项目名关键词 → 组别）")
async def shift_item_groups_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:read")),
) -> JSONResponse:
    from app.modules.quality.repository import get_shift_config

    cfg = await get_shift_config(db, "item_groups")
    return success_response(data=(cfg.value if cfg else None) or {
        "仪器组": ["杂质", "含量", "有关物质", "组分", "残留溶剂", "色谱"],
        "生物组": ["微生物", "菌", "效价", "内毒素", "无菌"],
        "理化组": ["pH", "水分", "干燥失重", "炽灼残渣", "澄清", "颜色", "熔点"],
    })


@router.put("/shift/item-groups", summary="保存项目组别映射配置")
async def save_shift_item_groups_endpoint(
    payload: dict[str, object] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    from app.modules.quality.repository import upsert_shift_config, user_shift_groups

    # 组别权限：项目组别映射为全局设置，编入班组的用户不可修改
    if await user_shift_groups(db, user.id):
        raise HTTPException(status_code=403, detail="项目组别映射为全局设置，仅管理人员可修改")

    await upsert_shift_config(db, "item_groups", payload)
    return success_response(message="项目组别映射已保存")


@router.get("/shift/duty", summary="当日当班班组与成员（排班选人时优先展示）")
async def shift_duty_endpoint(
    date: str | None = Query(default=None, description="YYYY-MM-DD，默认今天"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:read")),
) -> JSONResponse:
    from app.core.time import today as _today
    from app.modules.quality.repository import (
        get_shift_config,
        list_shift_teams,
        shift_duty_teams,
    )

    on_date = date or _today().isoformat()
    cfg = await get_shift_config(db, "rotation")
    value = cfg.value if cfg and cfg.value else {}
    start_date = value.get("start_date")
    period_days = int(value.get("period_days") or 3)
    duty_count = int(value.get("duty_teams") or 2)
    team_order = value.get("team_order") or []
    teams = await list_shift_teams(db)
    team_dicts = [{"id": str(t.id), "name": t.name, "group_key": t.group_key, "member_ids": t.member_ids or []} for t in teams]
    duty = shift_duty_teams(team_dicts, start_date or on_date, period_days, duty_count, on_date, team_order) if start_date else []
    member_ids: list[str] = []
    for t in duty:
        member_ids.extend(t["member_ids"])
    names: dict[str, str] = {}
    if member_ids:
        from sqlalchemy import select as _select

        from app.platform.identity.models import User as IdentityUser

        stmt = _select(IdentityUser).where(IdentityUser.id.in_(member_ids))
        names = {str(u.id): u.name for u in (await db.execute(stmt)).scalars()}
    return success_response(data={
        "date": on_date,
        "configured": bool(start_date),
        "teams": [{"id": t["id"], "name": t["name"]} for t in duty],
        "members": [{"id": i, "name": names.get(i, "未知")} for i in member_ids],
    })
