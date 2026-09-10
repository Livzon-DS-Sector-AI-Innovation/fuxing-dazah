"""AI 调用审计查询 API。

GET /api/v1/safety/ai-audits          → 分页列表（input/output 仅预览）
GET /api/v1/safety/ai-audits/stats    → 近 N 天按场景聚合统计
GET /api/v1/safety/ai-audits/{id}     → 单条详情（含全文）

审计数据含 prompt 全文，前端页面与 Agent 工具侧均限 safety_admin 使用；
API 层认证沿用现有占位机制（前端 SSO 接入后统一收紧）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.safety.ai_audit.schemas import (
    PREVIEW_CHARS,
    AICallAuditDetail,
    AICallAuditListItem,
)

logger = logging.getLogger(__name__)

ai_audits_router = APIRouter()


def _preview(text: str | None) -> str | None:
    if text is None:
        return None
    return text[:PREVIEW_CHARS] + ("…" if len(text) > PREVIEW_CHARS else "")


@ai_audits_router.get("/ai-audits", summary="AI 调用审计列表")
async def list_ai_audits(
    scenario: str | None = Query(None, description="场景过滤"),
    status: str | None = Query(None, description="success / failed"),
    channel: str | None = Query(None, description="渠道过滤：web / feishu / system"),
    resource_id: uuid.UUID | None = Query(None, description="业务对象 ID（如隐患 ID）"),
    user_name: str | None = Query(None, description="用户姓名（模糊）"),
    keyword: str | None = Query(None, description="输入/输出全文关键字"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """分页查询 AI 调用审计记录。"""
    from app.modules.safety.ai_audit.store import list_audits

    rows, total = await list_audits(
        db,
        scenario=scenario,
        status=status,
        channel=channel,
        resource_id=resource_id,
        user_name=user_name,
        keyword=keyword,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    items = [
        AICallAuditListItem.model_validate(row)
        .model_copy(update={
            "input_preview": _preview(row.input_text),
            "output_preview": _preview(row.output_text),
        })
        .model_dump(mode="json")
        for row in rows
    ]
    return success_response(
        data=items,
        meta={"page": page, "page_size": page_size, "total": total},
    )


@ai_audits_router.get("/ai-audits/stats", summary="AI 调用审计统计")
async def ai_audit_stats(
    days: int = Query(7, ge=1, le=366),
    date_from: datetime | None = Query(None, description="显式起点（优先于 days）"),
    date_to: datetime | None = Query(None, description="显式终点（默认当前时间）"),
    db: AsyncSession = Depends(get_db),
):
    """时间窗内按场景聚合 + 按天序列 + 上一周期环比基数。"""
    from app.modules.safety.ai_audit.store import get_stats

    return success_response(
        data=await get_stats(db, days=days, date_from=date_from, date_to=date_to)
    )


@ai_audits_router.get("/ai-audits/{audit_id}", summary="AI 调用审计详情")
async def get_ai_audit(
    audit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """单条审计详情（含输入/输出全文、引用法规、禁语命中）。"""
    from app.modules.safety.ai_audit.store import get_audit

    row = await get_audit(db, audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="审计记录不存在")
    detail = AICallAuditDetail.model_validate(row).model_copy(update={
        "input_preview": _preview(row.input_text),
        "output_preview": _preview(row.output_text),
    })
    return success_response(data=detail.model_dump(mode="json"))
