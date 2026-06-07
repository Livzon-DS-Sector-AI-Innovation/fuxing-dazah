import datetime
import json
import logging

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.platform.identity.models import User
from app.platform.identity.repository import UserRepository
from app.platform.integrations.feishu.client import FeishuClient

logger = logging.getLogger(__name__)


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
        self, session: AsyncSession, code: str,
    ) -> str:
        """Exchange code → upsert user → enrich department/position → return JWT."""
        resp = await self._feishu.exchange_code(code)
        if not resp.success():
            raise RuntimeError(
                f"Feishu token exchange failed: code={resp.code}, msg={resp.msg}",
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

        # ── 补全部门/职位信息 ──
        if feishu_user_id and (
            not user.department or not user.position or not user.feishu_department_ids
        ):
            try:
                from app.platform.integrations.feishu.contact import get_user_detail

                detail = await get_user_detail(feishu_user_id, user_id_type="user_id")
                if detail:
                    if detail.get("department_ids"):
                        user.feishu_department_ids = json.dumps(
                            detail["department_ids"], ensure_ascii=False,
                        )
                    if detail.get("positions"):
                        major = next(
                            (p for p in detail["positions"] if p.get("is_major")),
                            None,
                        )
                        if major:
                            if major.get("position_name"):
                                user.position = major["position_name"]
                    elif detail.get("job_title"):
                        user.position = detail["job_title"]
            except Exception:
                logger.exception("Failed to enrich user detail for %s", feishu_user_id)

        await session.flush()
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
