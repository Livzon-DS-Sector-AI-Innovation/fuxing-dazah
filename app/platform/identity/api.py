import datetime
import secrets

import jwt
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.platform.identity.deps import CurrentUser
from app.platform.identity.repository import UserRepository
from app.platform.identity.schemas import UserResponse
from app.platform.identity.service import IdentityService
from app.platform.integrations.feishu.client import FeishuClient

router = APIRouter(prefix="/auth", tags=["身份认证"])
user_router = APIRouter(tags=["用户信息"])


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
