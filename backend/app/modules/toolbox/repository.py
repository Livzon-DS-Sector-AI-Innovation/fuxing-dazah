"""工具箱数据访问：tool_grants 表查询与替换、tool_configs 工具配置读写。"""

import functools
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.toolbox.models import ToolConfig, ToolGrant
from app.platform.identity.models import User


def _missing_table_as[T](default_factory: Callable[[], T]) -> Callable[..., Any]:
    """tool_grants 表尚未建立（部署窗口）时按无数据降级，其余错误照常抛出。

    表不存在 = 从未配置过授权 = 默认开放，与空表语义一致。
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(
            self: Any, db: AsyncSession, *args: Any, **kwargs: Any
        ) -> Any:
            try:
                return await fn(self, db, *args, **kwargs)
            except ProgrammingError as exc:
                if getattr(exc.orig, "sqlstate", None) == "42P01":
                    return default_factory()
                raise

        return wrapper

    return decorator


class ToolboxGrantRepository:
    """工具授权持久化。关联行采用硬删除（同 UserRole 惯例，规避软删除与唯一约束冲突）。"""

    @_missing_table_as(list)
    async def get_user_grants(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> list[ToolGrant]:
        stmt = select(ToolGrant).where(
            ToolGrant.user_id == user_id,
            ToolGrant.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    @_missing_table_as(set)
    async def list_tool_ids_with_grants(self, db: AsyncSession) -> set[str]:
        """已配置授权（即进入限制模式）的工具 ID 集合。

        与 list_tool_grants 同口径过滤软删除用户，避免其授权行锁死工具却在管理列表不可见。
        """
        stmt = (
            select(ToolGrant.tool_id)
            .join(User, User.id == ToolGrant.user_id)
            .where(
                ToolGrant.is_deleted == False,  # noqa: E712
                User.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        return set(result.scalars())

    @_missing_table_as(list)
    async def list_tool_grants(
        self, db: AsyncSession
    ) -> list[tuple[ToolGrant, User]]:
        """全部授权行，inner join identity.users 取展示信息。"""
        stmt = (
            select(ToolGrant, User)
            .join(User, User.id == ToolGrant.user_id)
            .where(
                ToolGrant.is_deleted == False,  # noqa: E712
                User.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def replace_tool_grants(
        self,
        db: AsyncSession,
        tool_id: str,
        use_ids: set[uuid.UUID],
        config_ids: set[uuid.UUID],
        created_by: uuid.UUID | None,
    ) -> None:
        """整体替换某工具的全部授权行：硬删除旧行后插入新行。

        先取事务级咨询锁串行化并发保存（先删后插无法用行锁防幻读），
        避免两个并发 PUT 撞 (user_id, tool_id) 唯一约束。
        """
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtext(f"toolbox:grant:{tool_id}")
                )
            )
        )
        await db.execute(
            delete(ToolGrant).where(ToolGrant.tool_id == tool_id)
        )
        for user_id in use_ids | config_ids:
            db.add(
                ToolGrant(
                    user_id=user_id,
                    tool_id=tool_id,
                    can_use=user_id in use_ids,
                    can_config=user_id in config_ids,
                    created_by=created_by,
                )
            )
        await db.flush()


async def get_tool_config(
    db: AsyncSession, tool_id: str
) -> ToolConfig | None:
    """读取工具配置行；未配置返回 None。"""
    result = await db.execute(
        select(ToolConfig).where(
            ToolConfig.tool_id == tool_id,
            ToolConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def upsert_tool_config(
    db: AsyncSession, tool_id: str, config: dict[str, Any]
) -> None:
    """写入工具配置（存在则更新，不存在则新增）。"""
    stmt = pg_insert(ToolConfig).values(
        tool_id=tool_id,
        config=config,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_toolbox_tool_configs_tool_id",
        set_={"config": config},
    )
    await db.execute(stmt)
