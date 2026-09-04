"""仓储 Agent gateway — 事件入口与组装层（S1 ticket 02）。

职责（spec Implementation Decisions 4）：
- 事件去重（Redis SETNX，仿 platform/integrations/feishu/event_handler）
- 机器人自身消息排除（sender_type=app / 机器人 open_id）
- 群聊仅 @提及响应；私聊全响应
- 会话定位（chat_id + open_id → warehouse_agent_sessions upsert）
- 消息类型路由：文本 → Runner（占位/结果卡片两段式发送）；图片 → 友好引导；
  其他类型忽略
- 卡片按钮回调路由（card.action.trigger → ConfirmService，按 scene 分发留扩展）
- 异常兜底：任何处理异常 → 降级话术卡片 + audit 记 error

发送通道只消费票01 的公共接口（warehouse/feishu/notification.py 的
send_card / send_card_to_user），测试经模块级 dry_run 或 _db_session 注入口隔离。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import confirm
from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.agent.cards import render_reply_card
from app.modules.warehouse.agent.runner import get_runner
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.feishu.event_client import on_event
from app.modules.warehouse.models import WarehouseAgentSession

logger = logging.getLogger(__name__)

# 仓库管理机器人 open_id（spec：去重时排除机器人自身消息）
BOT_OPEN_ID = "ou_260db4ff7c9b361b9374c9516d3766ab"

# Redis 去重（仿 platform event_handler：feishu:msg:{message_id} SETNX EX 120）
DEDUP_KEY_PREFIX = "feishu:msg:"
DEDUP_TTL_SECONDS = 120

# 会话历史保留条数（user+assistant 交替，24 条 ≈ 12 轮，对齐 SESSION_ROUNDS=12）
HISTORY_MAX_MESSAGES = 24


# ── 数据库会话注入口 ──
# 生产：应用全局工厂，ctx 退出统一 commit（gateway 不在各步骤散落 commit）。
# 测试：monkeypatch gateway._db_session 为包装测试 session 的无 commit 上下文，
#       随 conftest db_session fixture 的 rollback 一并回滚，保证用例间隔离。


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# ── 事件解析 helper（纯函数）──


def _sender_open_id(event: dict[str, Any]) -> str:
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    if isinstance(sender_id, dict):
        return str(sender_id.get("open_id") or "")
    return ""


def _mentioned_bot(mentions: list[dict[str, Any]] | None) -> bool:
    """群聊 @提及检测：mentions 中任一 id.open_id 为机器人即命中。"""
    for mention in mentions or []:
        mention_id = mention.get("id") or {}
        if isinstance(mention_id, dict) and mention_id.get("open_id") == BOT_OPEN_ID:
            return True
    return False


def _extract_text(message: dict[str, Any]) -> str:
    """解析消息 content JSON 的 text 字段，并把 @占位符替换为可读名称。"""
    content = message.get("content")
    try:
        data = json.loads(content) if isinstance(content, str) else (content or {})
    except json.JSONDecodeError:
        logger.warning("仓库网关消息 content 解析失败: %s", str(content)[:100])
        return ""
    if not isinstance(data, dict):
        return ""
    text = str(data.get("text") or "")
    for mention in message.get("mentions") or []:
        key = str(mention.get("key") or "")
        if key:
            text = text.replace(key, f"@{mention.get('name') or ''}".strip())
    return text.strip()


async def _try_acquire_dedup(message_id: str) -> bool:
    """Redis SETNX 去重；Redis 异常时降级放行（不因缓存故障丢消息）。"""
    from app.core.redis import redis_client

    try:
        acquired = await redis_client.set(
            f"{DEDUP_KEY_PREFIX}{message_id}", "1", ex=DEDUP_TTL_SECONDS, nx=True
        )
        return bool(acquired)
    except Exception:
        logger.exception("仓库网关去重 Redis 异常，降级放行")
        return True


# ── 卡片构建（飞书卡片 1.0 结构，与票01 测试样例同构）──


def _build_card(
    *, title: str, template: str, markdown: str
) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "elements": [{"tag": "markdown", "content": markdown}],
    }


def _build_placeholder_card() -> dict[str, Any]:
    return _build_card(
        title="⏳ 正在处理…",
        template="blue",
        markdown="已收到你的消息，正在处理，请稍候…",
    )


def _build_image_guidance_card() -> dict[str, Any]:
    return _build_card(
        title="📷 图片消息",
        template="orange",
        markdown=(
            "图片识别功能即将上线，敬请期待。\n\n"
            "当前请直接用文字描述你的需求，例如：\n"
            "「硫酸还有多少放行的」「查一下批号 A1 的库存」"
        ),
    )


def _build_error_card() -> dict[str, Any]:
    return _build_card(
        title="⚠️ 处理失败",
        template="red",
        markdown=(
            "抱歉，刚才的处理出了点问题，已记录并在排查。\n"
            "请稍后重试，或换个问法再试试。"
        ),
    )


async def _send_card_to(
    *, chat_id: str, chat_type: str, open_id: str, card: dict[str, Any]
) -> None:
    """按会话形态选择发送通道：群聊 send_card / 私聊 send_card_to_user。

    发送失败（notification 返回失败语义）只记日志不抛异常——不能因发送
    通道抖动中断后续处理。
    """
    if chat_type == "group":
        message_id = await notification.send_card(chat_id, card)
        if message_id is None:
            logger.warning("仓库网关群卡片发送失败: chat_id=%s", chat_id)
    else:
        sent = await notification.send_card_to_user(open_id, card)
        if not sent:
            logger.warning("仓库网关私聊卡片发送失败: open_id=%s", open_id)


async def _record_gateway_audit(
    *,
    started: float,
    tool_name: str,
    args_summary: dict[str, Any],
    result_status: str,
    session_id: uuid.UUID | None = None,
    error_code: str | None = None,
) -> None:
    """独立事务写审计；写失败只记日志（审计不阻断主流程）。"""
    try:
        async with _db_session() as db:
            await agent_repository.insert_agent_audit(
                db,
                tool_name=tool_name,
                args_summary=args_summary,
                result_status=result_status,
                error_code=error_code,
                duration_ms=_elapsed_ms(started),
                session_id=session_id,
            )
    except Exception:
        logger.exception("仓库网关审计写入失败")


# ── im.message.receive_v1 处理器 ──


@on_event("im.message.receive_v1")
async def handle_im_message(event: dict[str, Any]) -> None:
    """飞书消息事件入口（event_client._dispatch 分发的 event dict）。"""
    started = time.monotonic()
    message = event.get("message") or {}
    message_id = str(message.get("message_id") or "")
    chat_id = str(message.get("chat_id") or "")
    chat_type = str(message.get("chat_type") or "")
    msg_type = str(message.get("message_type") or "")
    open_id = _sender_open_id(event)
    mentions = message.get("mentions")
    logger.info(
        "仓库网关收到消息: type=%s chat_type=%s sender=%s message_id=%s",
        msg_type, chat_type, open_id[:20], message_id,
    )

    # 1. 机器人自身消息排除（事件标记 sender_type=app 或机器人 open_id）
    sender_type = str((event.get("sender") or {}).get("sender_type") or "")
    if sender_type == "app" or open_id == BOT_OPEN_ID:
        return

    # 2. Redis 去重（同 message_id 二次投递只处理一次）
    if message_id and not await _try_acquire_dedup(message_id):
        logger.info("仓库网关重复消息忽略: message_id=%s", message_id)
        return

    # 3. 群聊仅响应 @提及；私聊全响应
    if chat_type == "group" and not _mentioned_bot(mentions):
        return

    # 4. 消息类型路由
    if msg_type == "image":
        try:
            await _send_card_to(
                chat_id=chat_id,
                chat_type=chat_type,
                open_id=open_id,
                card=_build_image_guidance_card(),
            )
            await _record_gateway_audit(
                started=started,
                tool_name="gateway",
                args_summary={"chat_type": chat_type, "message_type": "image"},
                result_status="ok",
            )
        except Exception as exc:
            logger.exception("仓库网关图片引导失败")
            await _record_gateway_audit(
                started=started,
                tool_name="gateway",
                args_summary={"chat_type": chat_type, "message_type": "image"},
                result_status="error",
                error_code=type(exc).__name__[:30],
            )
        return

    if msg_type != "text":
        return  # 其他类型（文件/音频/合并转发等）忽略

    text = _extract_text(message)
    if not text:
        return
    await _handle_text_message(
        chat_id=chat_id, chat_type=chat_type, open_id=open_id, text=text, started=started
    )


async def _handle_text_message(
    *, chat_id: str, chat_type: str, open_id: str, text: str, started: float
) -> None:
    """文本消息主链路：会话定位 → 占位卡片 → Runner → 结果卡片 → 历史+审计。"""
    session_id: uuid.UUID | None = None
    located: WarehouseAgentSession | None = None
    try:
        # 会话定位（upsert）
        async with _db_session() as db:
            located = await agent_repository.get_or_create_session(
                db, chat_id=chat_id, user_open_id=open_id
            )
            session_id = located.id
        runner_session = located
        if runner_session is None:  # 理论不可达（get_or_create_session 必返回或抛异常）
            raise RuntimeError("仓库网关会话定位失败")
        # 占位卡片先发（S1 不做卡片 patch 更新，完成后直接新发结果卡片——S2 升级）
        await _send_card_to(
            chat_id=chat_id, chat_type=chat_type, open_id=open_id,
            card=_build_placeholder_card(),
        )
        reply = await get_runner().run(runner_session, text)
    except Exception as exc:
        logger.exception("仓库网关文本处理失败: message=%r", text[:50])
        try:
            await _send_card_to(
                chat_id=chat_id, chat_type=chat_type, open_id=open_id,
                card=_build_error_card(),
            )
        except Exception:
            logger.exception("仓库网关降级卡片发送失败")
        await _record_gateway_audit(
            started=started,
            tool_name="gateway",
            args_summary={"chat_type": chat_type, "text": text[:100]},
            result_status="error",
            session_id=session_id,
            error_code=type(exc).__name__[:30],
        )
        return

    # 结果卡片（Reply.data 命中查询工具 → 专用卡片；否则兜底文本卡片，ticket 04）
    await _send_card_to(
        chat_id=chat_id, chat_type=chat_type, open_id=open_id,
        card=render_reply_card(reply),
    )
    # 会话历史追加 + 审计（ok）
    duration_ms = _elapsed_ms(started)
    async with _db_session() as db:
        history = dict(located.history or {}) if located is not None else {}
        messages = list(history.get("messages") or [])
        messages.append({"role": "user", "content": text})
        messages.append({"role": "assistant", "content": reply.text})
        history["messages"] = messages[-HISTORY_MAX_MESSAGES:]
        if session_id is not None:
            await agent_repository.update_session_history(db, session_id, history)
        await agent_repository.insert_agent_audit(
            db,
            tool_name="gateway",
            args_summary={"chat_type": chat_type, "text": text[:100]},
            result_status="ok",
            duration_ms=duration_ms,
            session_id=session_id,
        )


# ── card.action.trigger 处理器 ──


@on_event("card.action.trigger")
async def handle_card_action_trigger(event: dict[str, Any]) -> dict[str, Any] | None:
    """卡片按钮回调入口：解析 value 按 scene 分发。

    返回卡片更新 dict（event_client 包装为 base64 Response 信封 ACK）；
    非本服务的 scene 返回 None（ACK 通用信封，S2 其他场景扩展位）。
    """
    action = event.get("action") or {}
    value = action.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            logger.warning("仓库网关卡片回调 value 解析失败: %s", value[:100])
            return None
    if not isinstance(value, dict):
        value = {}

    scene = str(value.get("scene") or "")
    # 票07：除通用确认场景外，已注册执行回调的场景（如 office 的 send_card）
    # 也进入确认门处理；未注册场景返回 None（ACK 通用信封，S2 识别确认等扩展位）
    if scene != confirm.CONFIRM_SCENE and not confirm.is_registered_scene(scene):
        return None

    operator = event.get("operator") or {}
    operator_open_id = str(operator.get("open_id") or "")
    logger.info(
        "仓库网关卡片操作: scene=%s action=%s operator=%s",
        scene, value.get("action"), operator_open_id[:20],
    )

    try:
        async with _db_session() as db:
            # shield：event_client 2.9s ACK 超时取消外层等待时，内部处理继续跑完，
            # 避免 confirmed 状态随事务回滚到 pending 导致重复发送
            outcome = await asyncio.shield(
                confirm.handle_action(db, value=value, operator_open_id=operator_open_id)
            )
    except asyncio.CancelledError:
        logger.warning("仓库网关卡片回调 ACK 超时，后台继续执行")
        raise
    except Exception:
        logger.exception("仓库网关卡片回调处理异常")
        outcome = confirm.ConfirmOutcome(
            ok=False, status="error", message="处理失败，请稍后重试"
        )

    return {
        "config": {"update_multi": True},
        "elements": [
            {
                "tag": "markdown",
                "content": f"{'✅' if outcome.ok else '⚠️'} {outcome.message}",
            }
        ],
    }
