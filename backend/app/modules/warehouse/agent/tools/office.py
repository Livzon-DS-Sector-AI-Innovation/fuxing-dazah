"""仓储 Agent 办公工具（S1 ticket 07，spec Implementation Decisions 6）。

2 个 Harness 工具 + 确认门业务回调，与查询/计划/记忆工具共用
``tools/query.py`` 的注册表（``TOOL_FUNCS`` / ``TOOLS``）：

- ``send_card``：替用户向指定目标发卡片——**HITL 确认门，不直接发送**。
  先经 ConfirmService.request_confirm 落 drafts 表（scene=send_card，
  pending_confirm + TTL 10min）并向发起人所在会话发预览卡片
  （[✅ 确认发送][❌ 取消]）；仅发起人在 TTL 内点「确认发送」才执行真实
  发送（``_execute_send_card`` 回调，模块导入时注册），取消/超时走 drafts
  状态机（cancelled/expired），绝不发送。target 仅接受 ``user:<open_id>``
  / ``group:<chat_id>`` 两种格式；用户只给人名/群名而 ID 不可得时返回
  error 提示 LLM 向用户索取，不猜测。
- ``create_reminder``：到点提醒——LLM 把自然语言时间转成 ISO（工具校验
  必须为未来时间；naive 时间按北京时间 UTC+8 解释），调度用**轻量方案**：
  不接 platform scheduler（启动期静态注册，不适合运行期动态任务），改用
  模块级 asyncio 延时任务表（``_reminder_tasks``）+ asyncio.create_task，
  到点发提醒卡片；同时落库 drafts 表（scene=reminder，expires_at=触发
  时间）作审计记录。进程重启后未触发提醒不恢复——完整方案（重启扫表
  重调度）V1.1 再做，S1 进程内 + 落库记录。

drafts 状态机补充（reminder 场景；models 列注释保持不动以避免迁移噪音）：
    scheduled ──到点触发──▶ fired（发送失败 → failed）
    scheduled ──cancel───▶ cancelled

工具上下文/数据库访问模式与 plan.py 相同：``execute_tool`` 注入 ``_ctx``
（{"session_id", "chat_id", "open_id"}）；工具内自开事务（``_db_session``
注入口），校验失败返回 ``{"error": ...}`` 不中断 Runner。卡片渲染在
cards.py（office → cards → runner → query 模块环，运行时延迟 import）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import confirm, repository
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseAgentDraft

logger = logging.getLogger(__name__)

# 场景标识（drafts.scene；send_card 同时是确认回调注册表与卡片按钮 value.scene）
SEND_CARD_SCENE = "send_card"
REMINDER_SCENE = "reminder"

# send_card 确认有效期（秒）：spec pending 状态 TTL 10min（测试可 monkeypatch 注入短 TTL）
CONFIRM_TTL_SECONDS = confirm.DEFAULT_TTL_SECONDS

# 载荷上限（对齐防呆：超长截断，外发内容以落库载荷为准）
TITLE_MAX_CHARS = 200
CONTENT_MAX_CHARS = 2000

# 提醒延时下限（秒）：略大于 0，避免未来时间的同秒触发竞态
MIN_DELAY_SECONDS = 0.05

# 北京时间（门店全部在国内、无夏令时，固定 +8；naive 时间按此解释）
_CN_TZ = timezone(timedelta(hours=8))


# ── 数据库会话注入口（与 plan.py 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


# ── 公共 helper ──


# 目标 ID 形态校验（飞书 open_id 固定 ou_ 前缀、chat_id 固定 oc_ 前缀）——
# 把人名/群名当 ID 传入（如 user:陈玉英）一律视为无效，由 _target_error 引导 LLM
# 向用户索取确切 ID，不猜测
_ID_PREFIXES = {"user": "ou_", "group": "oc_"}


def parse_target(target: str) -> tuple[str, str] | None:
    """target → (kind, id)；仅接受 user:<ou_…> / group:<oc_…>，否则 None。"""
    text = (target or "").strip()
    for prefix, kind in (("user:", "user"), ("group:", "group")):
        if text.startswith(prefix):
            ident = text[len(prefix):].strip()
            if ident.startswith(_ID_PREFIXES[kind]):
                return kind, ident
            return None
    return None


def _target_error(target: str) -> dict[str, Any]:
    """无效目标的工具返回（引导 LLM 向用户索取确切 ID，不猜测）。"""
    return {
        "error": f"target {target!r} 不是有效目标",
        "hint": (
            "target 必须是 user:<open_id>（发给个人）或 group:<chat_id>"
            "（发给群聊）。若用户只给了人名/群名而无法从会话上下文得到确切"
            " ID，请向用户询问目标，不要猜测。"
        ),
    }


def parse_trigger_time(value: str) -> datetime | None:
    """ISO 时间字符串 → UTC datetime；无法解析返回 None。

    naive 时间按北京时间（UTC+8）解释；带时区则换算为 UTC。
    """
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_CN_TZ)
    return parsed.astimezone(UTC)


def _display_time(trigger: datetime) -> str:
    """触发时间 → 北京时间展示文本（提醒卡片用）。"""
    return trigger.astimezone(_CN_TZ).strftime("%Y-%m-%d %H:%M")


def _generate_reminder_no() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"RM-{stamp}-{uuid.uuid4().hex[:6].upper()}"


# ── send_card：HITL 确认门 ──


async def request_card_send(
    *,
    target: str,
    title: str,
    content: str,
    requester_open_id: str,
    chat_id: str | None = None,
    session_id: uuid.UUID | None = None,
    expires_in_seconds: int = CONFIRM_TTL_SECONDS,
) -> dict[str, Any]:
    """发起一次外发确认：校验 → drafts 落库（pending_confirm）→ 预览卡片发发起人。

    返回 ``{"error"}`` 或 {"status": "pending_confirm", "draft_id", ...}；
    真实发送在确认回调 ``_execute_send_card`` 中执行（仅发起人点击可达）。
    """
    parsed = parse_target(target)
    if parsed is None:
        return _target_error(target)
    title_text = (title or "").strip()
    content_text = (content or "").strip()
    if not title_text:
        return {"error": "title 不能为空"}
    if not content_text:
        return {"error": "content 不能为空"}
    if not requester_open_id:
        return {"error": "缺少发起人上下文（open_id），无法发起确认"}

    kind, target_id = parsed
    payload: dict[str, Any] = {
        "target": f"{kind}:{target_id}",
        "target_kind": kind,
        "target_id": target_id,
        "title": title_text[:TITLE_MAX_CHARS],
        "content": content_text[:CONTENT_MAX_CHARS],
        "requester_open_id": requester_open_id,
        "chat_id": chat_id or "",
        "session_id": str(session_id) if session_id else "",
    }
    kind_cn = "用户" if kind == "user" else "群聊"
    summary = f"向{kind_cn} {target_id} 发送卡片「{title_text[:60]}」"
    try:
        async with _db_session() as db:
            draft = await confirm.request_confirm(
                db,
                requester_open_id=requester_open_id,
                summary=summary,
                payload=payload,
                scene=SEND_CARD_SCENE,
                expires_in_seconds=expires_in_seconds,
            )
    except Exception as exc:  # noqa: BLE001 — 落库失败不中断 Runner
        logger.exception("外发确认草稿创建失败: target=%s", payload["target"])
        return {"error": f"确认请求创建失败: {type(exc).__name__}: {exc}"}

    # 预览卡片发给发起人所在会话（无 chat_id 时私聊发发起人本人）；
    # 发送失败则本次确认无法进行，返回 error 由 LLM 告知用户重试。
    from app.modules.warehouse.agent.cards import render_confirm_preview_card

    card = render_confirm_preview_card(
        payload, scene=SEND_CARD_SCENE, draft_id=str(draft.id)
    )
    if chat_id:
        sent = await notification.send_card(chat_id, card) is not None
    else:
        sent = await notification.send_card_to_user(requester_open_id, card)
    if not sent:
        logger.warning(
            "外发确认预览卡片发送失败: draft_no=%s requester=%s",
            draft.draft_no, requester_open_id[:20],
        )
        return {"error": "确认预览卡片发送失败，请稍后重试"}

    return {
        "status": "pending_confirm",
        "draft_id": str(draft.id),
        "target": payload["target"],
        "message": (
            "已向发起人发送确认预览卡片（10 分钟内有效）：只有发起人点击"
            "「确认发送」后才会真正发出，点击「取消」或超时则不会发送。"
            "请在回复中提醒用户到卡片上确认。"
        ),
    }


async def _execute_send_card(
    db: AsyncSession, draft: WarehouseAgentDraft
) -> str | None:
    """确认门回调（scene=send_card）：用户点「确认发送」后执行真实发送。

    由 confirm.handle_action 在校验链通过后调用（同事务）；发送失败抛异常
    → 草稿保持 pending_confirm 可重试、audit 记 error。
    """
    payload = dict((draft.aligned or {}).get("payload") or {})
    parsed = parse_target(str(payload.get("target") or ""))
    if parsed is None:
        raise ValueError(f"确认草稿载荷目标无效: {payload.get('target')!r}")
    kind, target_id = parsed

    from app.modules.warehouse.agent.cards import render_outgoing_card

    card = render_outgoing_card(
        str(payload.get("title") or ""), str(payload.get("content") or "")
    )
    if kind == "user":
        sent = await notification.send_card_to_user(target_id, card)
        if not sent:
            raise RuntimeError(f"卡片发送失败（user:{target_id}）")
    else:
        message_id = await notification.send_card(target_id, card)
        if message_id is None:
            raise RuntimeError(f"卡片发送失败（group:{target_id}）")
    logger.info(
        "仓库办公工具确认后卡片已发送: target=%s:%s draft_no=%s",
        kind, target_id, draft.draft_no,
    )
    return f"已发送到 {kind}:{target_id}"


# ── create_reminder：asyncio 延时任务表（轻量调度）──

# reminder_id(str UUID) → 延时任务（模块级；任务结束自清理，cancel_reminder 取消）
_reminder_tasks: dict[str, asyncio.Task[None]] = {}


def _resolve_reminder_destination(payload: dict[str, Any]) -> tuple[str, str]:
    """提醒投递目标 → (通道, 接收方)：显式 target > 发起会话 > 发起人私聊。"""
    parsed = parse_target(str(payload.get("target") or ""))
    if parsed is not None:
        return ("open_id", parsed[1]) if parsed[0] == "user" else ("chat_id", parsed[1])
    chat_id = str(payload.get("chat_id") or "")
    if chat_id:
        return "chat_id", chat_id
    return "open_id", str(payload.get("requester_open_id") or "")


async def _mark_reminder(
    reminder_id: str, status: str, *, error_code: str | None = None
) -> None:
    """提醒终态落库（fired/failed/cancelled）+ audit；失败只记日志。"""
    try:
        async with _db_session() as db:
            draft = await repository.get_agent_draft(db, uuid.UUID(reminder_id))
            if draft is None:
                return
            await repository.set_agent_draft_status(db, draft, status)
            await repository.insert_agent_audit(
                db,
                tool_name="reminder",
                args_summary={"reminder_id": reminder_id[:30], "status": status},
                result_status="error" if status == "failed" else "ok",
                error_code=error_code,
                draft_id=draft.id,
            )
    except Exception:  # noqa: BLE001 — 提醒状态更新失败不影响已发出的卡片
        logger.exception("仓库提醒状态更新失败: reminder_id=%s", reminder_id)


async def _fire_reminder(reminder_id: str, payload: dict[str, Any]) -> None:
    """到点触发：渲染提醒卡片 → 投递 → 落终态（fired/failed）。"""
    from app.modules.warehouse.agent.cards import render_reminder_card

    channel, receiver = _resolve_reminder_destination(payload)
    card = render_reminder_card(
        {
            "content": str(payload.get("content") or ""),
            "trigger_at": str(payload.get("trigger_display") or ""),
        }
    )
    try:
        if channel == "chat_id":
            sent = await notification.send_card(receiver, card) is not None
        else:
            sent = await notification.send_card_to_user(receiver, card)
    except Exception as exc:  # noqa: BLE001 — 发送异常按失败落库
        logger.exception("仓库提醒卡片发送异常: reminder_id=%s", reminder_id)
        await _mark_reminder(reminder_id, "failed", error_code=type(exc).__name__[:30])
        return
    if not sent:
        await _mark_reminder(reminder_id, "failed", error_code="send_failed")
        return
    logger.info("仓库提醒已触发: reminder_id=%s receiver=%s", reminder_id, receiver[:20])
    await _mark_reminder(reminder_id, "fired")


async def _fire_reminder_after(
    reminder_id: str, delay: float, payload: dict[str, Any]
) -> None:
    """延时任务体：sleep → 触发；被取消静默退出；异常落 failed 终态。"""
    try:
        await asyncio.sleep(max(delay, MIN_DELAY_SECONDS))
        await _fire_reminder(reminder_id, payload)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — 兜底：任何未预期异常落 failed
        logger.exception("仓库提醒触发失败: reminder_id=%s", reminder_id)
        await _mark_reminder(reminder_id, "failed", error_code="unexpected")
    finally:
        _reminder_tasks.pop(reminder_id, None)


async def schedule_reminder(
    *,
    time: str,
    content: str,
    requester_open_id: str,
    chat_id: str | None = None,
    target: str | None = None,
    session_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """创建到点提醒：校验（未来时间/目标格式）→ drafts 落库 → 注册延时任务。

    返回 ``{"error"}`` 或 {"reminder_id", "trigger_at", ...}。
    """
    content_text = (content or "").strip()
    if not content_text:
        return {"error": "content 不能为空（一句话提醒内容）"}
    if not requester_open_id:
        return {"error": "缺少发起人上下文（open_id），无法创建提醒"}

    target_text = (target or "").strip()
    if target_text and parse_target(target_text) is None:
        return _target_error(target_text)

    trigger = parse_trigger_time(time)
    if trigger is None:
        return {
            "error": f"time {time!r} 无法解析",
            "hint": (
                "time 需为 ISO 格式的未来时间，如 2026-09-05T08:00:00"
                "（按北京时间解释）或带时区 2026-09-05T08:00:00+08:00"
            ),
        }
    now = datetime.now(UTC)
    if trigger <= now:
        return {
            "error": "time 必须是未来时间",
            "now": now.isoformat(),
            "hint": "请把用户的相对时间表达（如「明早 8 点」）换算成未来的 ISO 时间",
        }

    aligned: dict[str, Any] = {
        "content": content_text[:500],
        "trigger_at": trigger.isoformat(),
        "target": target_text,
        "chat_id": chat_id or "",
    }
    try:
        async with _db_session() as db:
            draft = await repository.create_agent_draft(
                db,
                draft_no=_generate_reminder_no(),
                scene=REMINDER_SCENE,
                status="scheduled",
                created_by_open_id=requester_open_id,
                aligned=aligned,
                expires_at=trigger,  # 触发时间即草稿过期时间（防重启恢复的依据，V1.1）
            )
    except Exception as exc:  # noqa: BLE001 — 落库失败不中断 Runner
        logger.exception("提醒草稿创建失败: content=%s", content_text[:30])
        return {"error": f"提醒创建失败: {type(exc).__name__}: {exc}"}

    reminder_id = str(draft.id)
    delay = (trigger - now).total_seconds()
    task_payload = {
        **aligned,
        "requester_open_id": requester_open_id,
        "trigger_display": _display_time(trigger),
    }
    _reminder_tasks[reminder_id] = asyncio.create_task(
        _fire_reminder_after(reminder_id, delay, task_payload)
    )
    return {
        "reminder_id": reminder_id,
        "trigger_at": trigger.isoformat(),
        "target": target_text or (f"group:{chat_id}" if chat_id else f"user:{requester_open_id}"),
        "message": "提醒已设置，到点将自动发送提醒卡片。请向用户确认提醒时间与内容。",
    }


async def cancel_reminder(reminder_id: str) -> bool:
    """取消提醒：撤销延时任务 + 草稿置 cancelled；无可取消对象返回 False。"""
    task = _reminder_tasks.pop(reminder_id, None)
    if task is not None and not task.done():
        task.cancel()
    try:
        draft_id = uuid.UUID(reminder_id)
    except ValueError:
        return False
    try:
        async with _db_session() as db:
            draft = await repository.get_agent_draft(db, draft_id)
            if draft is None or draft.scene != REMINDER_SCENE:
                return False
            if draft.status != "scheduled":
                return False
            await repository.set_agent_draft_status(db, draft, "cancelled")
    except Exception:  # noqa: BLE001 — 取消失败返回 False，不中断调用方
        logger.exception("仓库提醒取消失败: reminder_id=%s", reminder_id)
        return False
    return True


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入，见模块注释）──


async def send_card(
    target: str, title: str, content: str, _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """向指定目标发送卡片（HITL：先出预览卡片，发起人确认后才真正发出）。"""
    ctx = _ctx or {}
    return await request_card_send(
        target=target,
        title=title,
        content=content,
        requester_open_id=str(ctx.get("open_id") or ""),
        chat_id=str(ctx.get("chat_id") or "") or None,
        session_id=ctx.get("session_id"),
    )


async def create_reminder(
    time: str,
    content: str,
    target: str | None = None,
    _ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """设置到点提醒（到点自动发提醒卡片；time 传 ISO 格式的未来时间）。"""
    ctx = _ctx or {}
    return await schedule_reminder(
        time=time,
        content=content,
        requester_open_id=str(ctx.get("open_id") or ""),
        chat_id=str(ctx.get("chat_id") or "") or None,
        target=target,
        session_id=ctx.get("session_id"),
    )


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

OFFICE_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "send_card": send_card,
    "create_reminder": create_reminder,
}

OFFICE_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "send_card",
            "description": (
                "替用户向指定目标发送卡片消息（如把报告/清单/通知发给某人或某群）。"
                "对外发送有确认门：调用后系统先向发起人发预览卡片，"
                "发起人点「确认发送」后才会真正发出（10 分钟内有效）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "发送目标：user:<open_id>（发给个人）或 group:<chat_id>"
                            "（发给群聊）。用户只给人名/群名而无法从上下文确定 ID 时，"
                            "先向用户询问，不要猜测"
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": "卡片标题（一句话，如「呆料批次清单」）",
                    },
                    "content": {
                        "type": "string",
                        "description": "卡片正文（markdown；数据必须来自工具查询结果）",
                    },
                },
                "required": ["target", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": (
                "设置到点提醒（用户说「到点提醒我…」时用）：到点自动向目标发送"
                "提醒卡片。time 必须是未来的 ISO 时间，相对表达按今天推算。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {
                        "type": "string",
                        "description": (
                            "触发时间，ISO 格式（如 2026-09-05T08:00:00，按北京时间"
                            "解释；相对表达如「明早 8 点」需换算成未来时间）"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "提醒内容（一句话，到点展示在提醒卡片上）",
                    },
                    "target": {
                        "type": "string",
                        "description": (
                            "可选提醒目标 user:<open_id> / group:<chat_id>；"
                            "缺省发回当前会话"
                        ),
                    },
                },
                "required": ["time", "content"],
            },
        },
    },
]

# 模块导入即注册 send_card 确认回调（查询工具注册表 import 本模块时生效；
# 重复注册抛 ValueError，模块单次导入语义下不会发生）
confirm.register_confirm_callback(SEND_CARD_SCENE, _execute_send_card)
