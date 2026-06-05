from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.models import User


class UserRepository:
    async def get_by_feishu_open_id(
        self, session: AsyncSession, open_id: str
    ) -> User | None:
        result = await session.execute(
            select(User).where(User.feishu_open_id == open_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        session: AsyncSession,
        *,
        name: str,
        feishu_user_id: str,
        feishu_open_id: str,
        employee_no: str | None = None,
        email: str | None = None,
        mobile: str | None = None,
        avatar_url: str | None = None,
    ) -> User:
        user = User(
            name=name,
            feishu_user_id=feishu_user_id,
            feishu_open_id=feishu_open_id,
            employee_no=employee_no,
            email=email,
            mobile=mobile,
            avatar_url=avatar_url,
        )
        session.add(user)
        await session.flush()
        return user
