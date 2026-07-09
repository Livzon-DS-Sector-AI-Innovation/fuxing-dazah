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

        # 换 Feishu App 后 open_id 会变，但 feishu_user_id 不变，
        # 回退按 feishu_user_id 查找已有用户并更新 open_id，避免 UniqueViolationError
        if user is None and feishu_user_id:
            user = await self._user_repo.get_by_feishu_user_id(session, feishu_user_id)

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
            user.feishu_open_id = feishu_open_id or user.feishu_open_id
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

    # -- Impersonation --

    IMPERSONATE_EXPIRE_SECONDS = 7200  # 2 hours

    def generate_impersonate_jwt(self, target_user: User, admin_user: User) -> str:
        """生成代理身份 JWT，sub=目标用户，impersonated_by=管理员。"""
        payload = {
            "sub": str(target_user.id),
            "impersonated_by": str(admin_user.id),
            "iat": datetime.datetime.now(tz=datetime.UTC),
            "exp": datetime.datetime.now(tz=datetime.UTC)
            + datetime.timedelta(seconds=self.IMPERSONATE_EXPIRE_SECONDS),
        }
        return jwt.encode(
            payload,
            self._settings.SECRET_KEY,
            algorithm="HS256",
        )

    def decode_impersonate_jwt(self, token: str) -> dict | None:
        """解析代理 JWT，验证签名和过期。返回 payload 或 None。"""
        try:
            return jwt.decode(
                token,
                self._settings.SECRET_KEY,
                algorithms=["HS256"],
            )
        except jwt.InvalidTokenError:
            return None
