"""工具箱权限业务：工具访问判定与授权名单管理。

权限语义：
- 超级管理员（permission:role:manage）恒放行使用与配置。
- 工具无任何授权行 → 使用默认开放（全员可用），配置仅超管。
- 工具存在授权行 → 使用 = 使用名单 ∪ 配置名单，配置 = 仅配置名单。
- 存储上 can_use 仅记录使用名单成员；配置名单隐含使用统一在读取时推导
  （row.can_use or row.can_config），策略判定只实现在 resolve_access_map 一处。
"""

import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.toolbox.models import ToolGrant
from app.modules.toolbox.registry import Tool
from app.modules.toolbox.repository import ToolboxGrantRepository
from app.modules.toolbox.schemas import GrantUserOut, ToolGrantsOut
from app.platform.identity.models import User
from app.platform.permission.deps import get_user_permissions

ADMIN_PERMISSION = "permission:role:manage"


class ToolGrantError(Exception):
    """授权校验预期内失败，消息直接透传给用户。"""


def _to_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _safe_uuid(value: object) -> uuid.UUID | None:
    try:
        return _to_uuid(value)
    except (ValueError, TypeError):
        return None


class ToolboxGrantService:
    """工具使用/配置权限判定与名单管理。"""

    def __init__(self) -> None:
        self._repo = ToolboxGrantRepository()

    async def is_admin(self, db: AsyncSession, user: User) -> bool:
        try:
            perms = await get_user_permissions(str(user.id), db)
        except (ValueError, TypeError):
            return False
        return ADMIN_PERMISSION in perms

    async def resolve_access(
        self, db: AsyncSession, user: User, tool_id: str
    ) -> tuple[bool, bool]:
        """单工具判定；复用批量实现，保证策略只实现在一处。"""
        return (await self.resolve_access_map(db, user, [tool_id]))[tool_id]

    async def resolve_access_map(
        self, db: AsyncSession, user: User, tool_ids: list[str]
    ) -> dict[str, tuple[bool, bool]]:
        """批量判定（GET /tools 用，避免逐工具查询）。返回 {tool_id: (can_use, can_config)}。"""
        if await self.is_admin(db, user):
            return {tool_id: (True, True) for tool_id in tool_ids}
        uid = _to_uuid(user.id)
        row_map = {r.tool_id: r for r in await self._repo.get_user_grants(db, uid)}
        restricted = await self._repo.list_tool_ids_with_grants(db)
        result: dict[str, tuple[bool, bool]] = {}
        for tool_id in tool_ids:
            row = row_map.get(tool_id)
            if row is not None:
                result[tool_id] = (
                    row.can_use or row.can_config,
                    row.can_config,
                )
            else:
                result[tool_id] = (tool_id not in restricted, False)
        return result

    async def list_tool_ids_with_grants(self, db: AsyncSession) -> set[str]:
        """已配置授权（进入限制模式）的工具 ID 集合。"""
        return cast(
            set[str], await self._repo.list_tool_ids_with_grants(db)
        )

    def _grants_out(
        self,
        tool_id: str,
        tool_name: str,
        entries: list[tuple[ToolGrant, User]],
    ) -> ToolGrantsOut:
        use_users: list[GrantUserOut] = []
        config_users: list[GrantUserOut] = []
        for grant, user in entries:
            gu = GrantUserOut(
                user_id=user.id,
                name=user.name,
                employee_no=user.employee_no,
                department=user.department,
            )
            if grant.can_use or grant.can_config:
                use_users.append(gu)
            if grant.can_config:
                config_users.append(gu)
        return ToolGrantsOut(
            tool_id=tool_id,
            tool_name=tool_name,
            use_users=use_users,
            config_users=config_users,
        )

    async def list_tool_grants(
        self, db: AsyncSession, tools: list[Tool]
    ) -> list[ToolGrantsOut]:
        """全部工具（含未配置的）的授权名单。

        不在注册表中的孤儿授权行（工具改名/下线遗留）附在末尾，
        供管理员在界面上清空，避免残留行仍参与限制判定却不可见。
        """
        rows = await self._repo.list_tool_grants(db)
        by_tool: dict[str, list[tuple[ToolGrant, User]]] = {}
        for grant, user in rows:
            by_tool.setdefault(grant.tool_id, []).append((grant, user))

        out = [
            self._grants_out(tool.id, tool.name, by_tool.get(tool.id, []))
            for tool in tools
        ]
        known = {tool.id for tool in tools}
        for tool_id, entries in sorted(by_tool.items()):
            if tool_id not in known:
                out.append(self._grants_out(tool_id, tool_id, entries))
        return out

    async def update_tool_grants(
        self,
        db: AsyncSession,
        admin: User,
        tool_id: str,
        use_ids: list[uuid.UUID],
        config_ids: list[uuid.UUID],
    ) -> None:
        """整体替换工具授权名单；名单引用不存在的用户时抛 ToolGrantError。"""
        wanted = set(use_ids) | set(config_ids)
        missing = await self._missing_user_ids(db, wanted)
        if missing:
            raise ToolGrantError(
                "用户不存在: " + ", ".join(str(uid) for uid in missing)
            )
        await self._repo.replace_tool_grants(
            db,
            tool_id,
            set(use_ids),
            set(config_ids),
            _safe_uuid(admin.id),
        )

    async def _missing_user_ids(
        self, db: AsyncSession, user_ids: set[uuid.UUID]
    ) -> list[uuid.UUID]:
        if not user_ids:
            return []
        stmt = select(User.id).where(
            User.id.in_(user_ids),
            User.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        found = set(result.scalars())
        return sorted(user_ids - found, key=str)
