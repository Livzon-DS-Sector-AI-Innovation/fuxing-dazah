"""Safety API — 应用配置中心读写端点（env→DB 迁移）。

3 端点（实际前缀 ``/api/v1/safety``）：

======================  ==================================================
GET  /app-config                     全部注册项生效视图（值/来源/冲突标记）
PUT  /app-config/{key}               更新单键（审计+失效；secret 键值脱敏）
GET  /app-config/audits?key=&limit=  变更审计列表（append-only）
======================  ==================================================

生效优先级：进程 env（非空）> DB 活行 > registry 默认；env 与 DB 同设且
不同值时 ``env_overrides_db=true``（提示清除 .env 残留键）。

错误语义：未知键 → 404（detail 以「未知配置键」开头）；值非法 → 422。
权限：全部端点 ``Depends(get_current_user)``，登录即可（与 bitable/ai
配置中心一致）；写操作 ``operator_name = current_user.name``。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import success_response
from app.modules.safety.app_config import registry
from app.modules.safety.app_config.store import store
from app.modules.safety.models import AppConfigAudit
from app.modules.safety.schemas.app_config import AppConfigValueUpdate

logger = logging.getLogger(__name__)

app_config_router = APIRouter()


@app_config_router.get("/app-config")
async def list_app_config(
    _: CurrentUser,
) -> Any:
    """全部注册项生效视图（含 env/db/default 来源与冲突标记）。"""
    return success_response(
        data={
            "items": store.effective_items(),
            "categories": registry.CATEGORY_LABELS,
        }
    )


@app_config_router.put("/app-config/{key}")
async def update_app_config(
    key: str,
    payload: AppConfigValueUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """更新单键（写 DB + 审计 + 缓存失效），返回该键生效视图。"""
    try:
        view = await store.set_value(
            db,
            key,
            payload.value,
            enabled=payload.enabled,
            note=payload.note,
            operator_name=current_user.name if current_user else None,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("未知配置键"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    return success_response(data=view)


@app_config_router.get("/app-config/audits")
async def list_app_config_audits(
    key: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """变更审计列表（按时间倒序；key 过滤可选）。"""
    stmt = select(AppConfigAudit).order_by(
        AppConfigAudit.created_at.desc()
    ).limit(limit)
    if key:
        stmt = stmt.where(AppConfigAudit.key == key)
    rows = (await db.execute(stmt)).scalars().all()
    data = [
        {
            "key": row.key,
            "action": row.action,
            "before_json": row.before_json,
            "after_json": row.after_json,
            "operator_name": row.operator_name,
            "created_at": (
                row.created_at.astimezone(UTC).isoformat()
                if isinstance(row.created_at, datetime)
                else str(row.created_at)
            ),
        }
        for row in rows
    ]
    return success_response(data=data)
