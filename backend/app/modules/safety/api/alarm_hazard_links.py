"""R1 报警→隐患联动台账 REST（§9.3 含项；管理/排障唯一面，一期无前端页）。

- 列表：分页+筛选，处置状态由 links 现况派生（succeeded/failed/executing），
  附 alarm_snapshot 摘要——状态机由底座 decision/agent_tasks 承载（§9.2），
  本表不自管状态；status 筛选下推 SQL（派生条件的等价表达式），total 同口径。
- refresh-hazard-no：① 轮询分配编号后直读隐患表回填（展示用，可空）。
- retry：失败受阻任务重投 system input → TaskRunner 下轮重跑执行器
  （执行器幂等：links 已有 hazard_record_id 即跳过）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, NotFoundException
from app.core.response import success_response
from app.modules.safety.models.alarm_hazard_link import AlarmHazardLink
from app.modules.safety.service.alarm_hazard_r1.closure import plain_text
from app.platform.permission.deps import RequireAdmin, RequireUser

alarm_hazard_links_router = APIRouter()

_TZ = ZoneInfo("Asia/Shanghai")

#: 派生状态 → SQL 等价条件（分页/total 同口径下推；见 _derive_status）
_STATUS_CONDITIONS: dict[str, list[ColumnElement[bool]]] = {
    "succeeded": [AlarmHazardLink.hazard_record_id.is_not(None)],
    "failed": [
        AlarmHazardLink.hazard_record_id.is_(None),
        AlarmHazardLink.error_message.is_not(None),
    ],
    "executing": [
        AlarmHazardLink.hazard_record_id.is_(None),
        AlarmHazardLink.error_message.is_(None),
    ],
}


def _derive_status(link: AlarmHazardLink) -> str:
    if link.hazard_record_id:
        return "succeeded"
    if link.error_message:
        return "failed"
    return "executing"


def _serialize(link: AlarmHazardLink) -> dict[str, Any]:
    return {
        "id": str(link.id),
        "alarm_domain": link.alarm_domain,
        "alarm_record_id": link.alarm_record_id,
        "alarm_fingerprint": link.alarm_fingerprint,
        "hazard_record_id": link.hazard_record_id,
        "hazard_no": link.hazard_no,
        "task_id": str(link.task_id) if link.task_id else None,
        "decided_by": link.decided_by,
        "status": _derive_status(link),
        "error_message": link.error_message,
        "alarm_snapshot": link.alarm_snapshot,
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "updated_at": link.updated_at.isoformat() if link.updated_at else None,
    }


def _parse_local_dt(raw: str) -> datetime:
    """北京时间口径解析（naive 视为 Asia/Shanghai；对 timestamptz 列比较）。"""
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt


@alarm_hazard_links_router.get(
    "/alarm-hazard-links", summary="联动台账列表（分页+筛选）",
)
async def list_links(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    domain: str | None = None,
    record_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: Any = RequireUser,
) -> JSONResponse:
    if status is not None and status not in _STATUS_CONDITIONS:
        raise AppException(
            status_code=400,
            message=f"status 取值仅支持 {'/'.join(_STATUS_CONDITIONS)}",
        )
    cond: list[ColumnElement[bool]] = [AlarmHazardLink.is_deleted.is_(False)]
    if domain:
        cond.append(AlarmHazardLink.alarm_domain == domain)
    if record_id:
        cond.append(AlarmHazardLink.alarm_record_id == record_id)
    if status:
        cond.extend(_STATUS_CONDITIONS[status])
    if date_from:
        cond.append(AlarmHazardLink.created_at >= _parse_local_dt(date_from))
    if date_to:
        cond.append(AlarmHazardLink.created_at < _parse_local_dt(date_to))

    rows = (
        await db.execute(
            select(AlarmHazardLink).where(*cond)
            .order_by(AlarmHazardLink.created_at.desc())
            .limit(page_size).offset((page - 1) * page_size)
        )
    ).scalars().all()
    total = (
        await db.execute(select(func.count()).select_from(AlarmHazardLink).where(*cond))
    ).scalar_one()

    return success_response(
        data=[_serialize(r) for r in rows],
        meta={"page": page, "page_size": page_size, "total": total},
    )


async def _get_link_or_404(db: AsyncSession, link_id: str) -> AlarmHazardLink:
    try:
        lid = uuid.UUID(link_id)
    except ValueError as exc:
        raise NotFoundException("联动记录不存在") from exc
    link = (
        await db.execute(
            select(AlarmHazardLink).where(
                AlarmHazardLink.id == lid, AlarmHazardLink.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundException("联动记录不存在")
    return link


@alarm_hazard_links_router.post(
    "/alarm-hazard-links/{link_id}/refresh-hazard-no", summary="回读隐患编号（① 轮询分配后）",
)
async def refresh_hazard_no(
    link_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: Any = RequireAdmin,
) -> JSONResponse:
    link = await _get_link_or_404(db, link_id)
    if link.hazard_no:
        return success_response(data={"id": str(link.id), "hazard_no": link.hazard_no})
    if not link.hazard_record_id:
        raise AppException(status_code=409, message="尚未生成隐患记录，无可回读编号")

    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    record = await SafetyBitableClient().get_record(link.hazard_record_id)
    fields = ((record or {}).get("record") or {}).get("fields") or {}
    hazard_no = plain_text(fields.get("隐患编号")).strip()
    if not hazard_no:
        raise AppException(status_code=409, message="隐患编号尚未分配（① 轮询 ≤300s 后再试）")
    link.hazard_no = hazard_no
    await db.commit()
    return success_response(data={"id": str(link.id), "hazard_no": hazard_no})


@alarm_hazard_links_router.post(
    "/alarm-hazard-links/{link_id}/retry", summary="失败重试（重投任务输入触发执行器重跑）",
)
async def retry_link(
    link_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: Any = RequireAdmin,
) -> JSONResponse:
    link = await _get_link_or_404(db, link_id)
    if not link.task_id:
        raise AppException(status_code=409, message="该记录无关联任务（仅转正/自动路径可重试）")

    from app.platform.superagent.models import AgentInput, AgentTask

    task = await db.get(AgentTask, link.task_id)
    if task is None:
        raise NotFoundException("关联任务不存在")
    if task.status != "open":
        raise AppException(status_code=409, message=f"任务已终态（{task.outcome or 'ended'}），不可重试")

    existing_retry = (
        await db.execute(
            select(func.count()).select_from(AgentInput).where(
                AgentInput.task_id == task.id,
                AgentInput.kind == "system",
                AgentInput.read_at.is_(None),
            )
        )
    ).scalar_one()
    if existing_retry:
        return success_response(data={"id": str(link.id), "queued": True,
                                      "note": "已有未读重试输入"})

    db.add(AgentInput(
        task_id=task.id, kind="system",
        payload={"type": "retry", "link_id": str(link.id), "at": datetime.now(UTC).isoformat()},
        delivered_at=datetime.now(UTC),
    ))
    await db.commit()
    return success_response(data={"id": str(link.id), "queued": True})
