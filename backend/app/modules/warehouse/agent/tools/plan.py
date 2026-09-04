"""仓储 Agent 任务计划工具（S1 ticket 05，spec Implementation Decisions 6）。

PlanService（业务函数）+ 3 个 Harness 工具（plan_task / update_plan / get_plan），
与查询工具共用 ``tools/query.py`` 的注册表（``TOOL_FUNCS`` / ``TOOLS``）。

职责：
- ``plan_task``：预计 ≥3 步的任务先规划（软约束写在系统提示词）；plans 表
  落库（plan_no = WP+日期+当日序号，如 WP20260904-001）+ 进度卡片首帧；
- ``update_plan``：步骤状态迁移（pending/in_progress/done/skipped/failed，
  可附 note）+ steps JSONB 更新 + 进度卡片重发（S1 简化：不做卡片 patch，
  每次发新卡）；全部步骤终态（done/skipped/failed）→ plan.status=done；
- ``get_plan``：中断恢复入口——用户要继续之前的任务时取回计划详情
  （plan_no 缺省取最近进行中的计划，优先当前会话、其次按发起人）。

工具上下文传递方式：``execute_tool(name, arguments, ctx=...)`` 的可选 ctx
参数（Runner 构造 {"session_id", "chat_id", "open_id"}，见 runner._run_tool）；
注册表中声明 ``_ctx`` 形参的工具自动接收（inspect.signature 判定），
其余工具签名不变。ctx 缺失（组件直测）时跳过卡片发送——计划落库不依赖
发送成功。

数据库访问：工具内自开事务（runner/gateway 同款 ``_db_session`` 注入口），
不复用 Runner 调用方事务（runner.py 头注释契约）。业务校验失败返回
``{"error": ...}``，不向上抛——绝不中断 Runner 循环（同 query.py 模式）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import date
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import repository
from app.modules.warehouse.feishu import notification

logger = logging.getLogger(__name__)

# 步骤状态机（update_plan 合法值；终态 = 计划完结判定）
STEP_STATUSES = ("pending", "in_progress", "done", "skipped", "failed")
TERMINAL_STATUSES = ("done", "skipped", "failed")

# 单计划步骤数上限（防 LLM 无限拆分；提示词引导 3~8 步）
MAX_STEPS = 10

# plan_no 序号重试次数（唯一索引并发冲突兜底；序号补零 3 位，>999/日字典序
# 会乱但当日千计划不现实，接受）
PLAN_NO_RETRIES = 3


# ── 数据库会话注入口（与 runner/gateway 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


# ── PlanService：业务函数（组件直测接缝，不依赖工具上下文）──


def plan_view(plan: Any) -> dict[str, Any]:
    """WarehouseAgentPlan → 可序列化 dict（工具返回 / 卡片渲染输入）。"""
    return {
        "plan_no": plan.plan_no,
        "title": plan.title,
        "status": plan.status,
        "steps": [dict(step) for step in (plan.steps or [])],
    }


def _init_steps(descriptions: list[str]) -> list[dict[str, Any]]:
    return [
        {"no": no, "desc": desc, "status": "pending"}
        for no, desc in enumerate(descriptions, 1)
    ]


def _progress(steps: list[dict[str, Any]]) -> str:
    finished = sum(1 for s in steps if s.get("status") in TERMINAL_STATUSES)
    return f"{finished}/{len(steps)}"


async def _generate_plan_no(db: AsyncSession) -> str:
    """plan_no = WP + YYYYMMDD + '-' + 当日 3 位序号（并发由唯一索引兜底重试）。"""
    prefix = f"WP{date.today().strftime('%Y%m%d')}-"
    last = await repository.get_latest_plan_no_on_prefix(db, prefix=prefix)
    seq = 1
    if last:
        try:
            seq = int(last.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    return f"{prefix}{seq:03d}"


async def create_plan(
    *,
    title: str,
    steps: list[str],
    session_id: uuid.UUID | None = None,
    open_id: str | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:
    """创建任务计划：校验 → plans 表落库 → 进度卡片首帧。返回 {"error"} 或计划视图。"""
    clean_title = (title or "").strip()
    if not clean_title:
        return {"error": "title 不能为空"}
    descriptions = [str(s).strip() for s in steps if str(s).strip()] if isinstance(
        steps, list
    ) else []
    if not descriptions:
        return {"error": "steps 不能为空（请拆成有序的步骤描述列表）"}
    if len(descriptions) > MAX_STEPS:
        return {"error": f"步骤过多（>{MAX_STEPS}），请精简或把任务拆小"}
    clean_title = clean_title[:200]  # 模型列 String(200)

    try:
        async with _db_session() as db:
            for _ in range(PLAN_NO_RETRIES):
                plan_no = await _generate_plan_no(db)
                try:
                    plan = await repository.insert_plan(
                        db,
                        plan_no=plan_no,
                        title=clean_title,
                        steps=_init_steps(descriptions),
                        session_id=session_id,
                        created_by_open_id=open_id,
                    )
                except IntegrityError:
                    await db.rollback()  # 序号冲突，重新生成（本事务仅此一写）
                    continue
                break
            else:
                return {"error": "计划编号生成冲突，请重试"}
    except Exception as exc:  # noqa: BLE001 — 计划落库失败不中断 Runner
        logger.exception("计划创建失败: title=%s", clean_title[:30])
        return {"error": f"计划创建失败: {type(exc).__name__}: {exc}"}

    view = plan_view(plan)
    await _send_plan_card(view, chat_id)
    return {
        **view,
        "message": (
            f"计划 {plan.plan_no} 已创建并展示给用户。请立即开始执行第 1 步；"
            "每完成（或跳过/失败）一步都调用 update_plan 更新状态；"
            "全部步骤完成后向用户输出总结。"
        ),
    }


async def update_step(
    *,
    plan_no: str,
    step_no: int,
    status: str,
    note: str | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:
    """更新计划步骤状态 + 重发进度卡片。返回 {"error"} 或步骤更新结果。"""
    status_norm = (status or "").strip()
    if status_norm not in STEP_STATUSES:
        return {
            "error": (
                f"status 仅支持 {'/'.join(STEP_STATUSES)}，收到 {status!r}"
            )
        }
    try:
        async with _db_session() as db:
            plan = await repository.get_plan_by_no(db, plan_no=plan_no)
            if plan is None:
                return {"error": f"计划 {plan_no} 不存在"}
            steps = [dict(s) for s in (plan.steps or [])]
            target = next((s for s in steps if s.get("no") == step_no), None)
            if target is None:
                nos = "、".join(str(s.get("no")) for s in steps)
                return {"error": f"步骤 {step_no} 不存在（该计划步骤: {nos}）"}
            target["status"] = status_norm
            if note is not None:
                target["note"] = str(note)[:200]
            plan.steps = steps  # JSONB 需重新赋值才触发 UPDATE
            if all(s.get("status") in TERMINAL_STATUSES for s in steps):
                plan.status = "done"
            await db.flush()
    except Exception as exc:  # noqa: BLE001 — 状态更新失败不中断 Runner
        logger.exception("计划步骤更新失败: plan_no=%s step_no=%s", plan_no, step_no)
        return {"error": f"步骤更新失败: {type(exc).__name__}: {exc}"}

    view = plan_view(plan)
    await _send_plan_card(view, chat_id)
    finished = all(s.get("status") in TERMINAL_STATUSES for s in view["steps"])
    return {
        **view,
        "step_no": step_no,
        "status": status_norm,
        "plan_status": view["status"],
        "progress": _progress(view["steps"]),
        "message": (
            f"步骤 {step_no} 已更新为 {status_norm}（进度 {_progress(view['steps'])}）。"
            + (
                "计划全部完成，请向用户总结结果。"
                if finished
                else "请继续执行下一步骤。"
            )
        ),
    }


async def get_plan_detail(
    *,
    plan_no: str | None = None,
    session_id: uuid.UUID | None = None,
    open_id: str | None = None,
) -> dict[str, Any]:
    """取计划详情：plan_no 指定直查；缺省取最近 active 计划（本会话优先，其次发起人）。"""
    try:
        async with _db_session() as db:
            if plan_no:
                plan = await repository.get_plan_by_no(db, plan_no=plan_no)
                if plan is None:
                    return {"error": f"计划 {plan_no} 不存在"}
            else:
                found = await repository.get_active_plans(
                    db, session_id=session_id, limit=1
                )
                plan = found[0] if found else None
                if plan is None:
                    found = await repository.get_active_plans(
                        db, created_by_open_id=open_id, limit=1
                    )
                    plan = found[0] if found else None
                if plan is None:
                    return {
                        "found": False,
                        "message": "没有进行中的计划。可请用户描述任务，"
                        "或用 get_plan(plan_no=...) 查指定计划。",
                    }
    except Exception as exc:  # noqa: BLE001 — 查询失败不中断 Runner
        logger.exception("计划查询失败: plan_no=%s", plan_no)
        return {"error": f"计划查询失败: {type(exc).__name__}: {exc}"}
    return {"found": True, "plan": plan_view(plan)}


# ── 进度卡片发送（工具侧通道，S1 不做卡片 patch：每次发新卡）──


async def _send_plan_card(plan_view_dict: dict[str, Any], chat_id: str | None) -> None:
    """发进度卡片到当前会话；失败/无 chat_id 只记日志——辅助视图不影响计划数据。"""
    if not chat_id:
        return
    try:
        # 延迟 import：cards → runner → query → plan 存在模块环，运行时已加载完毕
        from app.modules.warehouse.agent.cards import render_progress_card

        card = render_progress_card(plan_view_dict)
        message_id = await notification.send_card(chat_id, card)
        if message_id is None:
            logger.warning(
                "计划进度卡片发送失败: plan_no=%s chat_id=%s",
                plan_view_dict.get("plan_no"), chat_id,
            )
    except Exception:  # noqa: BLE001 — 卡片发送失败不影响计划更新
        logger.exception(
            "计划进度卡片发送异常: plan_no=%s", plan_view_dict.get("plan_no")
        )


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入，见模块注释）──


async def plan_task(
    title: str, steps: list[str], _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """创建任务计划（≥3 步任务先规划再执行，系统提示词强制）。"""
    ctx = _ctx or {}
    return await create_plan(
        title=title,
        steps=steps,
        session_id=ctx.get("session_id"),
        open_id=ctx.get("open_id"),
        chat_id=ctx.get("chat_id"),
    )


async def update_plan(
    plan_no: str,
    step_no: int,
    status: str,
    note: str | None = None,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """更新计划步骤状态（用户在进度卡片看到进展）。"""
    ctx = _ctx or {}
    try:
        step = int(step_no)
    except (TypeError, ValueError):
        return {"error": f"step_no 应为整数，收到 {step_no!r}"}
    return await update_step(
        plan_no=plan_no,
        step_no=step,
        status=status,
        note=note,
        chat_id=ctx.get("chat_id"),
    )


async def get_plan(
    plan_no: str | None = None, _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """取回计划详情（中断恢复：继续之前的任务前先取回剩余步骤）。"""
    ctx = _ctx or {}
    return await get_plan_detail(
        plan_no=plan_no, session_id=ctx.get("session_id"), open_id=ctx.get("open_id")
    )


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

PLAN_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "plan_task": plan_task,
    "update_plan": update_plan,
    "get_plan": get_plan,
}

PLAN_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "plan_task",
            "description": (
                "创建任务计划（多步任务先规划再执行）：预计需要 3 步及以上的任务"
                "（盘点并汇总、批量催办、跨表核对等）必须先用本工具制定计划。"
                "创建后系统会向用户展示进度卡片，之后必须逐个步骤执行，"
                "每完成一步调用 update_plan 更新状态。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "任务标题（一句话概括，如「盘点呆料并按大类分组汇总」）",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "步骤描述列表（按执行顺序 3~8 个，每步一句话、可独立执行）",
                    },
                },
                "required": ["title", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": (
                "更新任务计划的步骤状态（用户在进度卡片上看到进展）。"
                "每完成/跳过/失败一步都要立即调用，可附简短 note 说明结果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_no": {"type": "string", "description": "计划编号（如 WP20260904-001）"},
                    "step_no": {"type": "integer", "description": "步骤序号（从 1 开始）"},
                    "status": {
                        "type": "string",
                        "enum": list(STEP_STATUSES),
                        "description": "步骤状态：in_progress/done/skipped/failed/pending",
                    },
                    "note": {
                        "type": "string",
                        "description": "结果说明（简短一句话，如「共 12 条呆料批次」），可选",
                    },
                },
                "required": ["plan_no", "step_no", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan",
            "description": (
                "取回任务计划详情（继续或查看之前的任务时先用本工具恢复上下文）。"
                "plan_no 省略时返回最近进行中的计划；从剩余步骤接着执行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_no": {
                        "type": "string",
                        "description": "计划编号；省略时取最近进行中的计划",
                    },
                },
                "required": [],
            },
        },
    },
]
