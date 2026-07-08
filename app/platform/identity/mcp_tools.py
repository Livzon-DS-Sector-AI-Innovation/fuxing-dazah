"""平台级 MCP Tools：用户查询与解析。

query_user 是所有业务模块 MCP tools 的基础能力，放到 platform/identity
而非某个业务模块，避免循环依赖和跨模块直接 import 内部实现。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastmcp.tools.base import ToolResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.models import User
from app.platform.identity.repository import UserRepository
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp

# ─────────────────────────────────────────────────────────────
# Shared helpers（供其他模块的 MCP tools 使用）
# ─────────────────────────────────────────────────────────────


def _user_to_dict(u: User) -> dict[str, Any]:
    """User ORM → 字典"""
    return {
        "id": str(u.id),
        "name": u.name,
        "employee_no": u.employee_no or "",
        "department": u.department or "",
        "position": u.position or "",
        "email": u.email or "",
        "mobile": u.mobile or "",
        "feishu_user_id": u.feishu_user_id or "",
    }


async def resolve_user(db: AsyncSession, operator_id: str) -> User:
    """将 operator_id 解析为 User 对象。

    解析优先级：UUID → 飞书 user_id → 姓名模糊搜索。
    """
    try:
        uid = uuid.UUID(operator_id)
        user = await db.get(User, uid)
        if user and not user.is_deleted:
            return user
    except ValueError:
        pass

    repo = UserRepository()
    user = await repo.get_by_feishu_user_id(db, operator_id)
    if user:
        return user

    users, total = await repo.list_all(db, keyword=operator_id, limit=10)
    if total == 1:
        return users[0]
    if total > 1:
        raise ValueError(f"找到多个匹配用户（{total}人），请提供更精确的 user_id")

    raise ValueError(f"未找到用户：{operator_id}")


# ─────────────────────────────────────────────────────────────
# MCP Tool: 查询用户身份
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def query_user(keyword: str) -> ToolResult:
    """
    根据姓名或 user_id 查询系统用户信息。

    查询优先级：
    1. 先尝试按 UUID 精确匹配
    2. 再尝试按飞书 user_id（union_id）精确匹配
    3. 最后按姓名模糊搜索

    适用于 Agent 在替用户操作前，需要先确认用户身份和 user_id 的场景。

    Args:
        keyword: 用户 UUID、飞书 user_id（union_id）、姓名（支持模糊匹配）或工号
    """
    db = get_db()
    repo = UserRepository()

    # 1) 尝试 UUID 精确匹配
    try:
        uid = uuid.UUID(keyword)
        user = await db.get(User, uid)
        if user and not user.is_deleted:
            u = _user_to_dict(user)
            return ToolResult(
                content=f"找到用户：{u['name']}（工号{u['employee_no']}）· {u['department']} · {u['position']}",
                structured_content={"users": [u]},
            )
    except ValueError:
        pass

    # 2) 尝试飞书 user_id 精确匹配
    user = await repo.get_by_feishu_user_id(db, keyword)
    if user:
        u = _user_to_dict(user)
        return ToolResult(
            content=f"找到用户：{u['name']}（工号{u['employee_no']}）· {u['department']} · {u['position']}",
            structured_content={"users": [u]},
        )

    # 3) 按姓名模糊搜索
    users, _total = await repo.list_all(db, keyword=keyword, limit=20)
    user_list = [_user_to_dict(u) for u in users]
    if not user_list:
        return ToolResult(
            content=f"未找到匹配「{keyword}」的用户。",
            structured_content={"users": []},
        )
    if len(user_list) == 1:
        u = user_list[0]
        return ToolResult(
            content=f"找到用户：{u['name']}（工号{u['employee_no']}）· {u['department']} · {u['position']}",
            structured_content={"user_list": user_list},
        )
    lines = [f"找到 {len(user_list)} 个匹配「{keyword}」的用户："]
    for u in user_list:
        lines.append(f"- {u['name']}（工号{u['employee_no']}）· {u['department']} · {u['position']}")
    return ToolResult(content="\n".join(lines), structured_content={"users": user_list})
