"""仓储 Agent 长期记忆工具（S1 ticket 06，spec Implementation Decisions 6）。

MemoryService（业务函数）+ 2 个 Harness 工具（save_memory / recall_memory），
与查询/计划工具共用 ``tools/query.py`` 的注册表（``TOOL_FUNCS`` / ``TOOLS``）。

职责：
- ``save_memory``：LLM 按规则判定记忆类型，scope 随类型推导（用户个人口味=
  preference/user；业务通用做法=convention/global；术语别名=alias/global），
  memories 表落库，content 超 200 字符截断并提示；
- ``recall_memory``：检索该用户的 + 全局的记忆（keyword 可选 ILIKE 过滤），
  被返回条目 hit_count 累加（淘汰依据）；
- ``inject_context``：会话开始注入——该用户偏好 top3 + 全局惯例/别名 top5
  （均按 updated_at 倒序），拼成提示词片段，无记忆返回空串（调用方据此
  省略记忆段）。

红线（spec）：记忆只影响表达与默认参数，不参与数据正确性——注入失败/为空
都不阻断会话，数字永远来自查询工具结果。

工具上下文传递：``execute_tool(name, arguments, ctx=...)`` 注入
{"session_id", "chat_id", "open_id"}（runner._run_tool 构造），声明 `_ctx`
形参的工具自动接收（inspect.signature 判定，同 plan.py 模式）。user 记忆
的 owner 取 ctx.open_id；global 记忆 owner 置空（全部门店共用）。

数据库访问：工具内自开事务（``_db_session`` 注入口，与 plan.py 同模式），
不复用 Runner 调用方事务；业务校验失败返回 ``{"error": ...}``，异常兜底
不向上抛——绝不中断 Runner 循环。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import repository

logger = logging.getLogger(__name__)

# 记忆类型与作用域（memories 表契约；类型 → 默认 scope 推导规则）
MEMORY_TYPES = ("preference", "convention", "alias")
MEMORY_SCOPES = ("user", "global")
TYPE_DEFAULT_SCOPE: dict[str, str] = {
    "preference": "user",  # 用户个人口味/习惯 → 存给该用户
    "convention": "global",  # 业务通用做法 → 全局惯例
    "alias": "global",  # 术语别名 → 全局通用
}

# content 长度上限（超长截断 + 提示；memories.content 为 Text 列，业务定限）
CONTENT_MAX_CHARS = 200

# recall 返回条数上限（Runner 侧另有 4KB/条结果截断兜底）
RECALL_LIMIT = 20

# 注入条数上限（spec：用户偏好 top3 + 全局惯例 top5）
PREFERENCE_TOP = 3
CONVENTION_TOP = 5


# ── 数据库会话注入口（与 plan.py 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


# ── MemoryService：业务函数（组件直测接缝，不依赖工具上下文）──


def memory_view(memory: Any) -> dict[str, Any]:
    """WarehouseAgentMemory → 可序列化 dict（工具返回用）。"""
    return {
        "memory_id": str(memory.id),
        "scope": memory.scope,
        "owner_open_id": memory.owner_open_id or "",
        "memory_type": memory.memory_type,
        "content": memory.content,
        "hit_count": int(memory.hit_count or 0),
    }


async def save(
    *,
    scope: str,
    owner_open_id: str | None,
    memory_type: str,
    content: str,
) -> dict[str, Any]:
    """保存一条长期记忆：校验 → 超长截断 → memories 表落库。

    返回记忆视图（含 truncated/message）；校验失败返回 ``{"error": ...}``。
    """
    scope_norm = (scope or "").strip()
    type_norm = (memory_type or "").strip()
    if scope_norm not in MEMORY_SCOPES:
        return {"error": f"scope 仅支持 {'/'.join(MEMORY_SCOPES)}，收到 {scope!r}"}
    if type_norm not in MEMORY_TYPES:
        return {
            "error": (
                f"memory_type 仅支持 {'/'.join(MEMORY_TYPES)}，收到 {memory_type!r}"
            )
        }
    text = (content or "").strip()
    if not text:
        return {"error": "content 不能为空（一句话描述要记住的内容）"}

    owner = (owner_open_id or "").strip() or None
    if scope_norm == "user":
        if not owner:
            return {"error": "user 记忆需要 owner_open_id（当前无会话上下文，无法归属用户）"}
    else:
        owner = None  # global 记忆不归属个人

    truncated = False
    if len(text) > CONTENT_MAX_CHARS:
        text = text[:CONTENT_MAX_CHARS]
        truncated = True

    try:
        async with _db_session() as db:
            memory = await repository.insert_memory(
                db,
                scope=scope_norm,
                owner_open_id=owner,
                memory_type=type_norm,
                content=text,
            )
    except Exception as exc:  # noqa: BLE001 — 记忆落库失败不中断 Runner
        logger.exception("记忆保存失败: scope=%s type=%s", scope_norm, type_norm)
        return {"error": f"记忆保存失败: {type(exc).__name__}: {exc}"}

    view = memory_view(memory)
    view["truncated"] = truncated
    view["message"] = "已记住。" + (
        f"（内容超过 {CONTENT_MAX_CHARS} 字，已截断）" if truncated else ""
    )
    return view


async def recall(*, owner_open_id: str, keyword: str | None = None) -> dict[str, Any]:
    """检索长期记忆：该用户的 + 全局的，keyword 可选 ILIKE 过滤。

    被返回条目 hit_count 累加；查询失败返回 ``{"error": ...}``。
    """
    try:
        async with _db_session() as db:
            rows = await repository.list_recallable_memories(
                db, owner_open_id=owner_open_id, keyword=keyword, limit=RECALL_LIMIT
            )
            await repository.bump_memory_hit_counts(db, rows)
    except Exception as exc:  # noqa: BLE001 — 记忆检索失败不中断 Runner
        logger.exception("记忆检索失败: owner=%s", owner_open_id[:20])
        return {"error": f"记忆检索失败: {type(exc).__name__}: {exc}"}
    return {"total": len(rows), "memories": [memory_view(m) for m in rows]}


async def inject_context(*, owner_open_id: str) -> str:
    """会话开始注入片段：该用户偏好 top3 + 全局惯例/别名 top5（updated_at 倒序）。

    被注入条目 hit_count 累加；无记忆返回空串，注入失败也返回空串
    （红线：记忆只是辅助，不得阻断会话）。
    """
    prefs: list[Any] = []
    global_items: list[Any] = []
    try:
        async with _db_session() as db:
            prefs = await repository.list_user_preferences(
                db, owner_open_id=owner_open_id, limit=PREFERENCE_TOP
            )
            global_items = await repository.list_global_knowledge(
                db, limit=CONVENTION_TOP
            )
            await repository.bump_memory_hit_counts(db, [*prefs, *global_items])
    except Exception:  # noqa: BLE001 — 注入失败不阻断会话
        logger.exception("记忆注入失败: owner=%s", owner_open_id[:20])
        return ""

    lines: list[str] = []
    if prefs:
        lines.append("该用户的偏好：")
        lines.extend(f"- {m.content}" for m in prefs)
    if global_items:
        lines.append("全局惯例与术语别名：")
        lines.extend(f"- {m.content}" for m in global_items)
    return "\n".join(lines)


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入，见模块注释）──


async def save_memory(
    memory_type: str, content: str, _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """保存长期记忆（scope 随 memory_type 推导：preference→user，其余→global）。"""
    type_norm = (memory_type or "").strip()
    scope = TYPE_DEFAULT_SCOPE.get(type_norm)
    if scope is None:
        return {
            "error": (
                f"memory_type 仅支持 {'/'.join(MEMORY_TYPES)}，收到 {memory_type!r}"
            )
        }
    ctx = _ctx or {}
    return await save(
        scope=scope,
        owner_open_id=str(ctx.get("open_id") or ""),
        memory_type=type_norm,
        content=content,
    )


async def recall_memory(
    keyword: str | None = None, _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """检索长期记忆（当前用户的偏好 + 全局惯例/别名），keyword 可选模糊过滤。"""
    ctx = _ctx or {}
    kw = (keyword or "").strip() or None
    return await recall(owner_open_id=str(ctx.get("open_id") or ""), keyword=kw)


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

MEMORY_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "save_memory": save_memory,
    "recall_memory": recall_memory,
}

MEMORY_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "保存长期记忆（跨会话生效）。判定规则：用户个人口味/习惯"
                "（如「以后报表别带包材」「只看危化品」）→ preference；"
                "业务通用做法（如「批号默认按入库日期倒序」）→ convention；"
                "术语别名（如「元明粉就是硫酸钠」）→ alias。"
                "用户显式纠正偏好或要求记住（「以后别…」「记住我…」）时必须"
                "调用本工具，并在回复中向用户确认已记住。content 一句话、"
                "≤200 字符（超长自动截断）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_type": {
                        "type": "string",
                        "enum": list(MEMORY_TYPES),
                        "description": (
                            "preference=用户个人偏好 / convention=业务通用惯例 / "
                            "alias=术语别名"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容（一句话，≤200 字符）",
                    },
                },
                "required": ["memory_type", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": (
                "检索长期记忆（当前用户的偏好 + 全局惯例/术语别名），keyword 可选"
                "按内容模糊过滤。回答涉及用户习惯/历史偏好、或需要确认某个术语"
                "时先用本工具查询。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "关键词（可选，按记忆内容模糊匹配）",
                    },
                },
                "required": [],
            },
        },
    },
]
