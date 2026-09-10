"""Safety API — Bitable 配置中心读写端点（backend-design §4）。

9 端点（实际前缀 ``/api/v1/safety``）：

======================  ==================================================
GET  /bitable-config/domains                     14 域总览（kind + 配置状态）
GET  /bitable-config/connections?domain=         连接列表（按域过滤，省略=全部）
GET  /bitable-config/connections/{domain}        单域全部 kind 连接
PUT  /bitable-config/connections/{domain}/{kind} 更新连接（审计+失效+重订阅）
GET  /bitable-config/mappings/{domain}/{kind}    读字段映射（DB 或 registry 默认）
PUT  /bitable-config/mappings/{domain}/{kind}    全量替换映射（审计+失效）
POST /bitable-config/test-connection             只读拉表/字段校验（不写审计）
POST /bitable-config/resubscribe/{domain}        手动重订阅（写 resubscribe 审计）
GET  /bitable-config/audits?domain=&limit=       变更审计列表（append-only）
======================  ==================================================

错误语义（§4.2）：未知域名/表类型 → 404（detail 以「未知域名」/「未知表类型」
开头，与 scheduler 惯例一致）；Pydantic 请求体校验失败 → 422；飞书侧失败 →
400（客户端错误）/ 502（上游异常）。

权限与审计（§4.3）：全部端点 ``Depends(get_current_user)``，登录即可；
写操作 ``operator_name = current_user.name``；set_connection / set_mappings
的 before/after 审计由 store 事务内写入，resubscribe 由本文件单独记
action="resubscribe"（before/after=None, kind="*"）；test_connection 不写审计。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import success_response
from app.modules.safety.bitable_config.event_hooks import resubscribe_domain
from app.modules.safety.bitable_config.registry import (
    REGISTRY,
    DomainInfo,
    get_domain,
)
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.models import BitableConfigAudit, BitableFieldMapping
from app.modules.safety.schemas.bitable_config import (
    AuditRow,
    ConnectionUpdate,
    ConnectionViewOut,
    MappingsUpdate,
    TestConnectionRequest,
)

logger = logging.getLogger(__name__)

bitable_config_router = APIRouter()

# store 连接 status（db/default/disabled/missing）→ 域总览 kind 状态语义
_KIND_STATUS_MAP = {
    "db": "configured",
    "default": "default",
    "disabled": "disabled",
    "missing": "missing",
}


def _get_domain_or_404(domain: str) -> DomainInfo:
    """未知域名 → 404（detail 以「未知域名」开头）。"""
    try:
        return get_domain(domain)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _get_kind_or_404(domain_info: DomainInfo, kind: str) -> None:
    """未知表类型 → 404（detail 以「未知表类型」开头）。"""
    try:
        domain_info.get_kind(kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _connection_out(view: ConnectionView) -> dict[str, Any]:
    """store.ConnectionView → 响应 dict（status 四态原样输出）。"""
    return ConnectionViewOut.model_validate(view).model_dump(mode="json")


def _domain_config_status(kind_statuses: set[str]) -> str:
    """域级 config_status 四态：configured / partial / disabled / missing。

    - 全部 db+default → configured（registry 默认值 = 现状行为，功能可用）；
    - 全部 disabled → disabled；全部 missing → missing；
    - 其余混合（含任一 disabled/missing 组合）→ partial。
    """
    if kind_statuses <= {"db", "default"}:
        return "configured"
    if kind_statuses == {"disabled"}:
        return "disabled"
    if kind_statuses == {"missing"}:
        return "missing"
    return "partial"


# ═══════════════════════════════════════════════════════════════
# 读端点
# ═══════════════════════════════════════════════════════════════


@bitable_config_router.get("/bitable-config/domains", summary="Bitable 域清单总览（14 域）")
async def list_bitable_domains(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """域总览：14 域 + kind 清单 + 每 kind 连接/映射配置状态。"""
    map_rows = (
        await db.execute(
            select(BitableFieldMapping).where(
                BitableFieldMapping.is_deleted.is_(False)
            )
        )
    ).scalars().all()
    db_mapping_keys = {(r.domain, r.kind) for r in map_rows}

    items: list[dict[str, Any]] = []
    for domain_info in REGISTRY.values():
        domain_view = store.get_domain_view(domain_info.key)
        kinds: list[dict[str, Any]] = []
        for kind_info in domain_info.kinds:
            conn = domain_view.connections[kind_info.kind]
            kinds.append(
                {
                    "kind": kind_info.kind,
                    "label": kind_info.label,
                    "app_token": conn.app_token,
                    "table_id": conn.table_id,
                    "enabled": conn.enabled,
                    "status": _KIND_STATUS_MAP[conn.status],
                    "mapping_status": (
                        "db"
                        if (domain_info.key, kind_info.kind) in db_mapping_keys
                        else "default"
                    ),
                }
            )
        items.append(
            {
                "key": domain_info.key,
                "label": domain_info.label,
                "purpose": domain_info.purpose,
                "subscribe": domain_info.subscribe,
                "config_status": _domain_config_status(
                    {c.status for c in domain_view.connections.values()}
                ),
                "kinds": kinds,
            }
        )
    return success_response(data=items)


@bitable_config_router.get("/bitable-config/connections", summary="Bitable 连接列表（按域过滤）")
async def list_bitable_connections(
    domain: str | None = Query(None, description="按域过滤；省略返回全部 14 域"),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """连接列表（含 disabled/missing 视图，status 区分，供配置页展示）。"""
    if domain is not None:
        _get_domain_or_404(domain)
        domain_keys = [domain]
    else:
        domain_keys = list(REGISTRY)
    items: list[dict[str, Any]] = []
    for key in domain_keys:
        views = store.get_domain_view(key).connections.values()
        items.extend(_connection_out(v) for v in views)
    return success_response(data=items)


@bitable_config_router.get("/bitable-config/connections/{domain}", summary="单域全部 kind 连接")
async def get_bitable_connections_by_domain(
    domain: str,
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """该域全部 kind 连接视图（含 disabled/missing）。"""
    _get_domain_or_404(domain)
    views = store.get_domain_view(domain).connections.values()
    return success_response(data=[_connection_out(v) for v in views])


@bitable_config_router.get(
    "/bitable-config/mappings/{domain}/{kind}", summary="读字段映射"
)
async def get_bitable_mappings(
    domain: str,
    kind: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """读映射：DB 行优先；无行回退 registry 默认（status=default）。"""
    domain_info = _get_domain_or_404(domain)
    _get_kind_or_404(domain_info, kind)
    row = (
        await db.execute(
            select(BitableFieldMapping).where(
                BitableFieldMapping.domain == domain,
                BitableFieldMapping.kind == kind,
                BitableFieldMapping.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    if row is not None:
        mappings: list[dict[str, Any]] = list(row.mappings)
        status = "db"
    else:
        mappings = store.get_domain_view(domain).mappings[kind]
        status = "default"
    return success_response(
        data={"domain": domain, "kind": kind, "status": status, "mappings": mappings}
    )


# ═══════════════════════════════════════════════════════════════
# 写端点
# ═══════════════════════════════════════════════════════════════


@bitable_config_router.put(
    "/bitable-config/connections/{domain}/{kind}", summary="更新 Bitable 连接"
)
async def update_bitable_connection(
    domain: str,
    kind: str,
    data: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """更新连接：store 事务内写审计 before/after + 失效缓存 + 触发重订阅。

    保存即生效（§4.3）：响应在重订阅完成前返回（fire-and-forget），不阻塞。
    """
    domain_info = _get_domain_or_404(domain)
    _get_kind_or_404(domain_info, kind)
    if domain != "central_alarm" and data.extra_table_ids is not None:
        raise HTTPException(
            status_code=422, detail="extra_table_ids 仅 central_alarm 域支持"
        )
    operator_name = current_user.name if current_user else None
    try:
        view = await store.set_connection(
            db,
            domain,
            kind,
            data.model_dump(exclude_unset=True),
            operator_name=operator_name,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("未知"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return success_response(data=_connection_out(view))


@bitable_config_router.put(
    "/bitable-config/mappings/{domain}/{kind}", summary="全量替换字段映射"
)
async def update_bitable_mappings(
    domain: str,
    kind: str,
    data: MappingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """全量替换映射：store 事务内写审计 before/after + 失效缓存（不触发重订阅）。"""
    domain_info = _get_domain_or_404(domain)
    _get_kind_or_404(domain_info, kind)
    operator_name = current_user.name if current_user else None
    payload = [m.model_dump(exclude_none=True) for m in data.mappings]
    try:
        mappings = await store.set_mappings(
            db, domain, kind, payload, operator_name=operator_name
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("未知"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return success_response(
        data={"domain": domain, "kind": kind, "status": "db", "mappings": mappings}
    )


@bitable_config_router.post(
    "/bitable-config/test-connection", summary="校验 app_token/table_id（只读）"
)
async def test_bitable_connection(
    data: TestConnectionRequest,
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """只读拉表/字段校验，不写库不写审计（§4.3）。

    失败语义：客户端错误（table_id 不存在/无权限）→ 400；
    飞书侧异常（网络/上游 5xx）→ 502。
    """
    try:
        result = await store.test_connection(data.app_token, data.table_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # 飞书上游异常（网络/5xx）统一映射 502
        logger.exception("Bitable test-connection 飞书侧异常")
        raise HTTPException(status_code=502, detail=f"飞书服务异常: {exc}") from exc
    return success_response(
        data={
            "ok": True,
            "app_token": data.app_token,
            "table_id": data.table_id,
            "meta": result.get("meta"),
        }
    )


@bitable_config_router.post(
    "/bitable-config/resubscribe/{domain}", summary="手动重订阅（兜底）"
)
async def resubscribe_bitable_domain(
    domain: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """对域内 drive 订阅重跑 ensure（幂等）；写 action=resubscribe 审计。"""
    _get_domain_or_404(domain)
    operator_name = current_user.name if current_user else None
    try:
        result = await resubscribe_domain(domain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(
        BitableConfigAudit(
            domain=domain,
            kind="*",
            action="resubscribe",
            before_json=None,
            after_json=None,
            operator_name=operator_name,
        )
    )
    await db.flush()
    return success_response(data=result)


# ═══════════════════════════════════════════════════════════════
# 审计端点
# ═══════════════════════════════════════════════════════════════


@bitable_config_router.get(
    "/bitable-config/audits", summary="Bitable 配置变更审计列表"
)
async def list_bitable_config_audits(
    domain: str | None = Query(None, description="按域过滤"),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """变更审计列表（append-only，最新在前）。"""
    if domain is not None:
        _get_domain_or_404(domain)
    stmt = (
        select(BitableConfigAudit)
        .where(BitableConfigAudit.is_deleted.is_(False))
        .order_by(BitableConfigAudit.created_at.desc())
        .limit(limit)
    )
    if domain is not None:
        stmt = stmt.where(BitableConfigAudit.domain == domain)
    rows = (await db.execute(stmt)).scalars().all()
    items = [AuditRow.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)
