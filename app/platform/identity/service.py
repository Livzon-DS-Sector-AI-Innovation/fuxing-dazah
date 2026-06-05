import datetime

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.platform.identity.models import User
from app.platform.identity.repository import UserRepository
from app.platform.integrations.feishu.client import FeishuClient


class IdentityService:
    def __init__(
        self,
        settings: Settings,
        feishu_client: FeishuClient,
        user_repo: UserRepository,
    ) -> None:
        self._settings = settings
        self._feishu = feishu_client
        self._user_repo = user_repo

    def build_login_url(self, state: str) -> str:
        return self._feishu.build_authorize_url(state)

    async def handle_callback(
        self, session: AsyncSession, code: str
    ) -> str:
        """Exchange code for user info, upsert user, return JWT."""
        resp = await self._feishu.exchange_code(code)
        if not resp.success():
            raise RuntimeError(
                f"Feishu token exchange failed: code={resp.code}, msg={resp.msg}"
            )

        body = resp.data
        if not body:
            raise RuntimeError("Feishu token response has no data")

        feishu_open_id = body.open_id or ""
        feishu_user_id = getattr(body, "user_id", "") or ""

        user = await self._user_repo.get_by_feishu_open_id(session, feishu_open_id)
        if user is None:
            user = await self._user_repo.create(
                session,
                name=body.name or "",
                feishu_user_id=feishu_user_id,
                feishu_open_id=feishu_open_id,
                employee_no=getattr(body, "employee_no", None),
                email=getattr(body, "email", None),
                mobile=getattr(body, "mobile", None),
                avatar_url=getattr(body, "avatar_url", None),
            )
        else:
            user.name = body.name or user.name
            user.email = getattr(body, "email", None) or user.email
            user.mobile = getattr(body, "mobile", None) or user.mobile
            user.avatar_url = getattr(body, "avatar_url", None) or user.avatar_url

        return self._generate_jwt(user)

    def _generate_jwt(self, user: User) -> str:
        payload = {
            "sub": str(user.id),
            "open_id": user.feishu_open_id,
            "iat": datetime.datetime.now(tz=datetime.UTC),
            "exp": datetime.datetime.now(tz=datetime.UTC)
            + datetime.timedelta(seconds=self._settings.JWT_EXPIRE_SECONDS),
        }
        return jwt.encode(
            payload,
            self._settings.SECRET_KEY,
            algorithm="HS256",
        )

    def verify_jwt(self, token: str) -> dict:
        return jwt.decode(
            token,
            self._settings.SECRET_KEY,
            algorithms=["HS256"],
        )
