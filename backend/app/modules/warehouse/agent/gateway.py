"""仓储 Agent gateway — 事件入口与组装层（S1 ticket 02 / S2 ticket 05）。

职责（spec Implementation Decisions 4/8）：
- 事件去重（Redis SETNX，仿 platform/integrations/feishu/event_handler）
- 机器人自身消息排除（sender_type=app / 机器人 open_id）
- 群聊仅 @提及响应；私聊全响应
- 会话定位（chat_id + open_id → warehouse_agent_sessions upsert）
- 消息类型路由：文本 → Runner（占位/结果卡片两段式发送）；图片 → 识别
  Pipeline（占位卡片 + create_task 后台：下载 im 原图 → vision 识别 →
  主数据对齐 → 确认卡片，失败降级话术含失败阶段 + audit）；其他类型忽略
- 卡片按钮回调路由（card.action.trigger → ConfirmService，按 scene 分发留扩展）
- 异常兜底：任何处理异常 → 降级话术卡片 + audit 记 error

发送通道只消费票01 的公共接口（warehouse/feishu/notification.py 的
send_card / send_card_to_user），测试经模块级 dry_run 或 _db_session 注入口隔离。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import (  # noqa: F401 — pipeline 导入即注册 scene=receipt 确认回调（票03 桩，票04 换 submit_receipt）；卡片回调路由依赖此注册
    confirm,
    pipeline,
)
from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.agent.cards import render_reply_card
from app.modules.warehouse.agent.pipeline import (
    align_receipt,
    create_receipt_draft,
    mark_aligned,
    recognize_receipt,
    send_confirm_card,
)
from app.modules.warehouse.agent.runner import get_runner
from app.modules.warehouse.feishu import media, notification
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


def _parse_content_dict(message: dict[str, Any]) -> dict[str, Any]:
    """消息 content（JSON 字符串或 dict）→ dict；解析失败返回空 dict。"""
    content = message.get("content")
    try:
        data = json.loads(content) if isinstance(content, str) else (content or {})
    except json.JSONDecodeError:
        logger.warning("仓库网关消息 content 解析失败: %s", str(content)[:100])
        return {}
    return data if isinstance(data, dict) else {}


def _extract_text(message: dict[str, Any]) -> str:
    """解析消息 content JSON 的 text 字段，并把 @占位符替换为可读名称。"""
    data = _parse_content_dict(message)
    text = str(data.get("text") or "")
    for mention in message.get("mentions") or []:
        key = str(mention.get("key") or "")
        if key:
            text = text.replace(key, f"@{mention.get('name') or ''}".strip())
    return text.strip()


def _extract_image_key(message: dict[str, Any]) -> str:
    """图片消息 content 中的图片 key（im.message.receive_v1 实测为
    ``{"image_key": "img_v3_…"}``；download_im_image 的 file_key 参数）。"""
    data = _parse_content_dict(message)
    return str(data.get("image_key") or data.get("file_key") or "")


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


def _build_image_processing_card() -> dict[str, Any]:
    """图片消息占位卡片（票05：识别 Pipeline 后台异步，完成后另发确认卡片）。"""
    return _build_card(
        title="🖼 正在识别，请稍候…",
        template="blue",
        markdown="已收到图片，正在识别送货单信息，完成后会发送确认卡片。",
    )


def _build_image_unsupported_card() -> dict[str, Any]:
    """图片格式不支持降级卡片（手机拍照 HEIC 等格式嗅探命中）。"""
    return _build_card(
        title="📷 图片格式暂不支持",
        template="orange",
        markdown=(
            "目前仅支持 JPG / PNG 格式的送货单图片。\n"
            "请用手机相机重新拍摄后发送，或将图片转换为 JPG / PNG 再试。"
        ),
    )


def _build_receipt_failed_card(stage: str) -> dict[str, Any]:
    """图片识别失败降级卡片（含失败阶段，spec 决策 8）。"""
    return _build_card(
        title="⚠️ 图片识别失败",
        template="red",
        markdown=(
            f"图片处理在「{stage}」阶段失败，已记录并排查。\n"
            "请稍后重试；也可直接用文字描述入库信息。"
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


# ── 图片识别后台任务（票05：占位卡片即回，Pipeline 异步执行）──
# 持强引用防 create_task 结果被 GC（asyncio 官方推荐模式）；完成自动移除。
# 测试经 await asyncio.wait(gateway._background_tasks) 等待后台任务收尾。

_background_tasks: set[asyncio.Task[None]] = set()


def _spawn_receipt_task(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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


def _scene_hint(text: str) -> str | None:
    """登记意图的场景预判（确定性路由提示，注入本轮上下文）。

    背景：同会话第二段登记易被第一段的历史/草稿带偏（live 实测），静态
    系统提示词约束不足——按关键词把场景提示作为近因消息注入，遵循度高。
    """
    t = text.lower().replace(" ", "").replace("　", "")
    if "登记" in t and ("gmp" in t or "gmp" in text.lower()):
        return (
            "【场景提示】本次任务为 GMP 物料出库登记：必须调用 create_gmp_draft "
            "收集字段，禁止调用其他登记工具。"
        )
    if "登记" in t and "成品出库" in t:
        return (
            "【场景提示】本次任务为成品出库登记：必须调用 create_finished_outbound_draft "
            "收集字段，禁止调用其他登记工具。"
        )
    return None

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

    # 3.5 收到确认：回复 OK 表情（add_reaction 内部吞错，不阻断主流程）
    if message_id:
        await notification.add_reaction(message_id, "OK")

    # 4. 消息类型路由
    if msg_type == "image":
        image_key = _extract_image_key(message)
        if not message_id or not image_key:
            # content 缺 image_key（或事件缺 message_id）：无法下载，直接降级
            logger.warning(
                "仓库网关图片事件缺少定位信息: message_id=%s image_key=%r",
                message_id, image_key[:20],
            )
            try:
                await _send_card_to(
                    chat_id=chat_id, chat_type=chat_type, open_id=open_id,
                    card=_build_receipt_failed_card("读取图片信息"),
                )
            except Exception:
                logger.exception("仓库网关图片降级卡片发送失败")
            await _record_gateway_audit(
                started=started,
                tool_name="gateway",
                args_summary={"chat_type": chat_type, "message_type": "image"},
                result_status="error",
                error_code="missing_image_key",
            )
            return
        # 占位卡片先回（识别为分钟级耗时，Pipeline 后台异步跑）
        try:
            await _send_card_to(
                chat_id=chat_id, chat_type=chat_type, open_id=open_id,
                card=_build_image_processing_card(),
            )
        except Exception:
            logger.exception("仓库网关图片占位卡片发送失败")
        _spawn_receipt_task(
            _process_receipt_image(
                chat_id=chat_id,
                chat_type=chat_type,
                open_id=open_id,
                message_id=message_id,
                image_key=image_key,
                started=started,
            )
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


async def _patch_confirm_card(draft: Any, state: str) -> None:
    """PATCH 更新原确认卡片状态（登记中/已登记/失败），message_id 取 Redis。"""

    from app.core.redis import redis_client
    from app.modules.warehouse.agent import cards
    from app.modules.warehouse.feishu import notification

    try:
        raw = await redis_client.get(f"wh:draft:card:{draft.id}")
        if not raw:
            return
        message_id = raw.decode() if isinstance(raw, bytes) else str(raw)
        if state == "processing":
            card = cards.render_confirm_status_card(
                draft, state="processing", title="⏳ 登记中"
            )
        else:
            card = cards.render_confirm_status_card(
                draft, state="done", title="✅ 登记完成"
            )
        await notification.update_card(message_id, card)
    except Exception:  # noqa: BLE001 — 卡片状态更新失败不阻断主流程
        logger.warning("确认卡片状态更新失败: draft_no=%s state=%s", draft.draft_no, state)


async def _run_submit_background(draft_id: uuid.UUID) -> None:
    """后台执行登记提交（submit 类场景确认后）：回调 → 回执按原渠道发送。

    独立 DB 会话（确认门事务已提交 confirmed 状态）；异常置 failed + 失败
    回执，不静默。回执渠道：draft.chat_id（群/私聊原渠道）优先，缺失回落
    发起人私聊。
    """
    from app.modules.warehouse.agent.pipeline.draft_flow import (
        SCENE_CONFIG,
        DraftFlowError,
    )

    try:
        async with _db_session() as db:
            draft = await agent_repository.get_agent_draft(db, draft_id)
            if draft is None or draft.status != "confirmed":
                return  # 幂等：状态已被处理/作废
            cfg = SCENE_CONFIG.get(draft.scene)
            submit_fn = cfg.submit if cfg else None
            if submit_fn is None:
                return
            try:
                await submit_fn(db, draft)
                await _patch_confirm_card(draft, "done")
            except DraftFlowError as exc:
                logger.error("后台登记执行失败: draft_no=%s err=%s", draft.draft_no, exc)
                await agent_repository.set_agent_draft_status(db, draft, "failed")
                await _send_failure_reply(draft, str(exc))
                await _patch_confirm_card(draft, "failed")
    except Exception:  # noqa: BLE001 — 后台任务顶层兜底
        logger.exception("后台登记任务异常: draft_id=%s", draft_id)
        try:
            async with _db_session() as db:
                draft = await agent_repository.get_agent_draft(db, draft_id)
                if draft is not None and draft.status == "confirmed":
                    await agent_repository.set_agent_draft_status(db, draft, "failed")
                    await _send_failure_reply(draft, "登记执行异常，请重新发起识别或登记")
        except Exception:  # noqa: BLE001
            logger.exception("后台登记失败回执发送异常: draft_id=%s", draft_id)


async def _send_failure_reply(draft: Any, reason: str) -> None:
    """登记失败回执：按发起渠道发送（chat_id 优先，回落私聊）。"""
    from app.modules.warehouse.feishu import notification

    card = {
        "config": {"update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "⚠️ 登记未完成"}, "template": "red"},
        "elements": [
            {
                "tag": "markdown",
                "content": "**草稿**："
                + draft.draft_no
                + "\n**原因**："
                + reason
                + "\n请重新发起。",
            }
        ],
    }
    chat_id = (draft.chat_id or "").strip()
    try:
        if chat_id:
            await notification.send_card(chat_id, card)
        else:
            open_id = (draft.created_by_open_id or "").strip()
            if open_id:
                await notification.send_card_to_user(open_id, card)
    except Exception:  # noqa: BLE001
        logger.exception("失败回执发送异常: draft_no=%s", draft.draft_no)


async def _process_receipt_image(
    *,
    chat_id: str,
    chat_type: str,
    open_id: str,
    message_id: str,
    image_key: str,
    started: float,
) -> None:
    """图片识别 Pipeline 后台任务（票05，spec 决策 8）。

    下载 im 原图（格式嗅探，非 JPG/PNG 降级）→ vision 识别 → 对齐 →
    草稿落库 → 确认卡片；原图先经 upload_image 挂到 material_receipt
    Base 名下拿 file_token 存 draft.source_image（spec 决策 3：submit
    时写附件列，上传失败不阻塞识别）。任何一步失败 → 降级话术卡片
    （含失败阶段）+ audit error。
    """
    stage = "下载图片"
    try:
        content = await media.download_im_image(message_id, image_key)
        fmt = media.sniff_image_format(content)
        if fmt not in media.SUPPORTED_IMAGE_FORMATS:
            logger.warning(
                "仓库网关图片格式不支持: message_id=%s fmt=%s", message_id, fmt
            )
            await _send_card_to(
                chat_id=chat_id, chat_type=chat_type, open_id=open_id,
                card=_build_image_unsupported_card(),
            )
            await _record_gateway_audit(
                started=started,
                tool_name="gateway",
                args_summary={
                    "chat_type": chat_type,
                    "message_type": "image",
                    "stage": stage,
                    "format": fmt,
                },
                result_status="error",
                error_code="unsupported_image_format",
            )
            return

        # 原图挂到 Base（submit 写附件列的 source_image）；失败仅降级为无附件
        image_file_token: str | None = None
        try:
            image_file_token = await media.upload_image(
                content, f"{message_id}.{'png' if fmt == 'png' else 'jpg'}"
            )
        except Exception:  # noqa: BLE001 — 附件上传失败不阻塞识别主链路
            logger.exception("仓库网关原图上传失败（识别继续，无附件）: message_id=%s", message_id)

        stage = "图片识别"
        content_type = "image/png" if fmt == "png" else "image/jpeg"
        image_b64 = base64.b64encode(content).decode()
        recognized = await recognize_receipt(image_b64, content_type)

        stage = "对齐与草稿"
        draft_no = ""
        match_confidence = ""
        async with _db_session() as db:
            draft = await create_receipt_draft(
                db,
                recognized=recognized,
                image_file_token=image_file_token,
                open_id=open_id,
                chat_id=chat_id,
            )
            aligned = await align_receipt(recognized)
            await mark_aligned(db, draft, aligned)
            # 群聊发群卡片、私聊发发起人（与 _send_card_to 通道选择同口径）
            # chat_id 统一传（p2p 会话也有 chat_id，确认后 PATCH/回执
            # 按原渠道回复；open_id 作为无 chat_id 时的回落）
            await send_confirm_card(
                db,
                draft,
                chat_id=chat_id,
                open_id=open_id if not chat_id else None,
            )
            draft_no = draft.draft_no
            match_confidence = aligned.match_confidence
    except Exception as exc:
        logger.exception(
            "仓库网关图片识别处理失败: stage=%s message_id=%s", stage, message_id
        )
        try:
            await _send_card_to(
                chat_id=chat_id, chat_type=chat_type, open_id=open_id,
                card=_build_receipt_failed_card(stage),
            )
        except Exception:
            logger.exception("仓库网关图片失败降级卡片发送失败")
        error_code = str(getattr(exc, "code", "") or type(exc).__name__)[:30]
        await _record_gateway_audit(
            started=started,
            tool_name="gateway",
            args_summary={
                "chat_type": chat_type,
                "message_type": "image",
                "stage": stage,
            },
            result_status="error",
            error_code=error_code,
        )
        return

    logger.info(
        "仓库网关图片识别完成: message_id=%s draft_no=%s match=%s",
        message_id, draft_no, match_confidence,
    )
    await _record_gateway_audit(
        started=started,
        tool_name="gateway",
        args_summary={
            "chat_type": chat_type,
            "message_type": "image",
            "draft_no": draft_no,
            "match": match_confidence,
        },
        result_status="ok",
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
        # 收到确认由 OK 表情承担（add_reaction）；不再发「正在处理」占位卡片
        # （用户反馈：与表情功能重复，2026-09-08）
        reply = await get_runner().run(runner_session, text, scene_hint=_scene_hint(text))
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

    # 结果卡片（Reply.data 命中查询工具 → 专用卡片；登记类工具 → 简短引导
    # 卡片替代 LLM 复述（用户反馈：字段核对以登记卡片为准，不重复展示）；
    # 否则兜底文本卡片，ticket 04）
    data = reply.data if isinstance(reply.data, dict) else {}
    tool_name = str(data.get("tool") or "")
    result_raw = data.get("result")
    result = result_raw if isinstance(result_raw, dict) else {}
    draft_no = str(result.get("draft_no") or "")
    if (
        tool_name.startswith("create_")
        and tool_name.endswith("_draft")
        and draft_no
    ):
        # 草稿真正创建才替换为简短引导卡；missing/追问场景保留 LLM 文本
        card = {
            "config": {"update_multi": True},
            "header": {"title": {"tag": "plain_text", "content": "📝 等待你确认"}, "template": "blue"},
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"**草稿 {draft_no or '已创建'}** 已生成，确认卡片在上方消息中。\n"
                        "请核对字段后点「确认登记」；要修改直接回复消息（如「数量改成 30」）。"
                    ),
                }
            ],
        }
    else:
        card = render_reply_card(reply)
    await _send_card_to(
        chat_id=chat_id, chat_type=chat_type, open_id=open_id,
        card=card,
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

    # submit 类场景（SceneConfig.submit 已注册）：确认门只置状态，ACK 更新
    # 卡片为「登记中」，submit 移后台执行，回执按发起渠道（draft.chat_id）
    # 发送——执行含 Base 写入+读回核对，可能超过 2.9s ACK 窗口
    from app.modules.warehouse.agent.pipeline.draft_flow import SCENE_CONFIG

    scene_cfg = SCENE_CONFIG.get(scene)
    submit_scene = scene_cfg is not None and scene_cfg.submit is not None
    if submit_scene and str(value.get("action") or "") == "confirm":
        try:
            async with _db_session() as db:
                outcome = await asyncio.shield(
                    confirm.handle_action(
                        db, value=value, operator_open_id=operator_open_id, execute=False
                    )
                )
                draft = outcome.draft
        except Exception:
            logger.exception("仓库网关登记确认处理异常")
            return {
                "config": {"update_multi": True},
                "elements": [
                    {"tag": "markdown", "content": "⚠️ 处理失败，请稍后重试"}
                ],
            }
        if outcome.ok and draft is not None:
            # PATCH 原确认卡片为「登记中」（按钮移除）——不依赖卡片回调 ACK
            # 协议（lark_oapi SDK 对 CARD 帧不处理，回调响应更新不可靠，实测）
            asyncio.create_task(_patch_confirm_card(draft, "processing"))
            _spawn_receipt_task(_run_submit_background(draft.id))
            return {"code": 200}  # ACK 通用信封（卡片更新走 PATCH）
        return {
            "config": {"update_multi": True},
            "elements": [
                {"tag": "markdown", "content": f"⚠️ {outcome.message}"}
            ],
        }

    # 非submit场景（send_card 等）：原同步路径
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
