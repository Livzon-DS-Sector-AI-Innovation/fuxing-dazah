import asyncio
import datetime
import logging
import secrets

import jwt
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.response import success_response
from app.platform.identity.deps import CurrentUser
from app.platform.identity.repository import DepartmentRepository, UserRepository
from app.platform.identity.schemas import (
    DepartmentResponse,
    DepartmentTreeNode,
    PersonnelItem,
    PersonnelListResponse,
    UserResponse,
)
from app.platform.identity.service import IdentityService
from app.platform.integrations.feishu.client import FeishuClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["身份认证"])
user_router = APIRouter(tags=["用户信息"])
dept_router = APIRouter(prefix="/departments", tags=["组织架构"])
personnel_router = APIRouter(prefix="/personnel", tags=["人员名单"])
sync_router = APIRouter(prefix="/sync", tags=["飞书同步"])


def get_feishu_client(
    settings: Settings = Depends(get_settings),
) -> FeishuClient:
    return FeishuClient(settings)


def get_identity_service(
    settings: Settings = Depends(get_settings),
    feishu_client: FeishuClient = Depends(get_feishu_client),
) -> IdentityService:
    return IdentityService(
        settings=settings,
        feishu_client=feishu_client,
        user_repo=UserRepository(),
    )


# ── SSO ─────────────────────────────────────────────────────────────


@router.get("/login", summary="飞书 SSO 登录")
async def sso_login(
    service: IdentityService = Depends(get_identity_service),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Redirect to Feishu OAuth authorize page."""
    state_payload = {
        "nonce": secrets.token_urlsafe(32),
        "iat": datetime.datetime.now(tz=datetime.UTC),
        "exp": datetime.datetime.now(tz=datetime.UTC)
        + datetime.timedelta(minutes=5),
    }
    state = jwt.encode(state_payload, settings.SECRET_KEY, algorithm="HS256")
    url = service.build_login_url(state)
    return RedirectResponse(url, status_code=302)


@router.get("/callback", summary="飞书 SSO 回调")
async def sso_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
    service: IdentityService = Depends(get_identity_service),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Handle Feishu OAuth callback: exchange code, upsert user, issue JWT."""
    try:
        jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?error=invalid_state",
            status_code=302,
        )

    try:
        token = await service.handle_callback(db, code)
    except Exception as exc:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Feishu callback failed")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?error=auth_failed&detail={exc}",
            status_code=302,
        )

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/auth/callback?token={token}",
        status_code=302,
    )


@user_router.get("/me", response_model=UserResponse, summary="获取当前用户信息")
async def get_current_user_info(
    user: CurrentUser = None,
) -> UserResponse:
    """Return the current authenticated user's profile."""
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="未登录")
    return UserResponse.model_validate(user)


# ── Departments ─────────────────────────────────────────────────────


def _build_department_tree(
    depts: list, parent_id: str | None = None,
) -> list[DepartmentTreeNode]:
    """递归构建部门树。"""
    result: list[DepartmentTreeNode] = []
    for d in depts:
        if d.parent_feishu_department_id == parent_id or (
            parent_id is None and not d.parent_feishu_department_id
        ):
            node = DepartmentTreeNode(
                id=d.id,
                feishu_department_id=d.feishu_department_id,
                name=d.name,
                member_count=d.member_count,
                leader_user_id=d.leader_user_id,
                order=d.order,
                children=_build_department_tree(
                    depts, d.feishu_department_id,
                ),
            )
            result.append(node)
    return result


@dept_router.get("", summary="获取部门列表 / 组织架构树")
async def list_departments(
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取所有部门。传 ?tree=true 返回层级组织架构树。"""
    repo = DepartmentRepository()
    depts = await repo.list_all(db)

    if tree:
        nodes = _build_department_tree(depts, parent_id=None)
        return success_response(data=[n.model_dump() for n in nodes])

    return success_response(
        data=[DepartmentResponse.model_validate(d).model_dump() for d in depts],
    )


@dept_router.get("/{dept_id}", summary="获取部门详情")
async def get_department(
    dept_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """按 open_department_id 获取单个部门详情。"""
    repo = DepartmentRepository()
    dept = await repo.get_by_feishu_id(db, dept_id)
    if dept is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="部门不存在")
    return success_response(data=DepartmentResponse.model_validate(dept).model_dump())


# ── Personnel ───────────────────────────────────────────────────────


@personnel_router.get("", summary="获取人员名单")
async def list_personnel(
    department_id: str | None = Query(None, description="按部门 ID 筛选"),
    keyword: str | None = Query(None, description="按姓名搜索"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """分页获取所有人员名单，支持按部门和姓名筛选。"""
    repo = UserRepository()
    users, total = await repo.list_all(
        db,
        department_id=department_id,
        keyword=keyword,
        offset=offset,
        limit=limit,
    )

    items = [PersonnelItem.model_validate(u).model_dump() for u in users]
    resp = PersonnelListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )
    return success_response(data=resp.model_dump())


# ── Sync ────────────────────────────────────────────────────────────


@sync_router.post("/departments", summary="触发飞书组织架构同步（异步）")
async def trigger_sync_departments(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """POST 触发一次飞书组织架构同步，后台执行不阻塞，立即返回。"""
    root_id = settings.FEISHU_SYNC_ROOT_DEPT_ID
    if not root_id:
        return JSONResponse(
            status_code=400,
            content={"message": "未配置 FEISHU_SYNC_ROOT_DEPT_ID"},
        )

    from app.platform.integrations.feishu.sync import sync_departments

    asyncio.create_task(sync_departments(root_id))
    logger.info("Department sync triggered for root=%s", root_id)
    return success_response(
        data={"message": "组织架构同步已触发", "root_dept_id": root_id},
    )


@sync_router.post("/members", summary="触发飞书成员同步（异步）")
async def trigger_sync_members(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """POST 触发一次飞书成员同步，后台执行不阻塞，立即返回。"""
    target_id = settings.FEISHU_SYNC_MEMBER_DEPT_ID
    if not target_id:
        return JSONResponse(
            status_code=400,
            content={"message": "未配置 FEISHU_SYNC_MEMBER_DEPT_ID"},
        )

    from app.platform.integrations.feishu.sync import sync_members

    asyncio.create_task(sync_members(target_id))
    logger.info("Member sync triggered for target=%s", target_id)
    return success_response(
        data={"message": "成员同步已触发", "target_dept_id": target_id},
    )
