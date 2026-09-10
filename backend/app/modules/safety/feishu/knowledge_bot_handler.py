"""Feishu bot handler — 安全知识库智能问答（已合并到 business_agent_bot_handler）。

本文件保留卡片构建和发送工具函数，不再独立注册事件处理器。
所有文本消息统一由 business_agent_bot_handler 的 Agent 处理（模型通过 knowledge_search 工具调用 RAG 管线）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.core.database import async_session_factory
from app.modules.safety.feishu.client import (
    get_safety_feishu_client,
    get_safety_tenant_token,
)
from app.modules.safety.knowledge.query_service import run_knowledge_chat

logger = logging.getLogger(__name__)

# ── Debug file log (临时调试日志，问题解决后删除) ──
_DEBUG_LOG = Path(__file__).resolve().parent.parent.parent.parent.parent / "debug_bot.log"

def _debug_log(msg: str) -> None:
    """写入临时调试日志文件。"""
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass

# ── Card content limits ──
_MAX_ANSWER_LEN = 12000   # Feishu markdown element practical limit
_MAX_SOURCES = 8          # Max reference items in card
_CARD_TITLE = "📖 安全知识库"


def _json_dumps(obj) -> str:
    """JSON 序列化，自动将 UUID 转为字符串。"""
    return json.dumps(obj, ensure_ascii=False, default=lambda o: str(o) if isinstance(o, UUID) else o)


# ── Message sending ──


async def _send_card_to_chat(chat_id: str, card: dict) -> str | None:
    """发送飞书卡片消息到指定会话。

    Args:
        chat_id: 飞书 chat_id（支持 p2p 和 group）
        card: 完整的飞书卡片 JSON dict

    Returns:
        成功返回 message_id，失败返回 None
    """
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        card_json = _json_dumps(card)

        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(card_json)
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.acreate(req)
        if not resp.success():
            logger.error(
                "知识库机器人发送卡片失败: chat_id=%s, code=%s, msg=%s",
                chat_id, resp.code, resp.msg,
            )
            return None
        message_id = resp.data.message_id if resp.data else None
        logger.info("知识库机器人卡片已发送: chat_id=%s, message_id=%s", chat_id, message_id)
        return message_id
    except Exception:
        logger.exception("知识库机器人发送卡片异常: chat_id=%s", chat_id)
        return None


async def _send_text_to_chat(chat_id: str, text: str) -> str | None:
    """发送纯文本消息到指定会话（用于错误提示）。"""
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        content = _json_dumps({"text": text})

        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(content)
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.acreate(req)
        if not resp.success():
            logger.error("知识库机器人发送文本失败: chat_id=%s, code=%s, msg=%s",
                         chat_id, resp.code, resp.msg)
            return None
        return resp.data.message_id if resp.data else None
    except Exception:
        logger.exception("知识库机器人发送文本异常: chat_id=%s", chat_id)
        return None


# ── Card builder ──


def _build_knowledge_card(answer: str, sources: list[dict], query: str) -> dict:
    """构建知识库问答回复卡片。

    Args:
        answer: AI 生成的自然语言回答（含 [N] 引用标记）
        sources: 去重后的法规来源列表
        query: 用户原始问题

    Returns:
        飞书卡片 JSON dict
    """
    # ── Build answer section ──
    answer_text = answer.strip()
    if len(answer_text) > _MAX_ANSWER_LEN:
        answer_text = answer_text[:_MAX_ANSWER_LEN] + "\n\n…（回答过长已截断，请在平台网页端查看完整回答）"

    # ── Build reference section ──
    ref_lines: list[str] = []
    if sources:
        ref_lines.append("**📚 参考法规**")
        for i, s in enumerate(sources[:_MAX_SOURCES], 1):
            title = s.get("doc_title", "未知文档")
            url = s.get("feishu_url", "")

            # Doc name + inline 查看原文 link
            line = f"**[{i}] 《{title}》**"
            if url:
                line += f"  <a href='{url}'>查看原文</a>"
            ref_lines.append(line)

        if len(sources) > _MAX_SOURCES:
            ref_lines.append(f"*…等共 {len(sources)} 部法规*")
    else:
        ref_lines.append("*未找到相关法规条款*")

    ref_text = "\n".join(ref_lines)

    # ── Assemble card ──
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": _CARD_TITLE},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": answer_text},
            {"tag": "hr"},
            {"tag": "markdown", "content": ref_text},
        ],
    }

    # Add footer with query context
    card["elements"].append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text", "content": f"🔍 查询：{query[:100]}"},
        ],
    })

    return card


# ── 公开函数（供外部调用）──


async def handle_knowledge_query(chat_id: str, query: str, event_data: dict) -> None:
    """处理知识库检索并回复卡片（已废弃，统一由 Agent 的 knowledge_search 工具处理）。"""
    _debug_log(f"HANDLER_CALLED chat_id={chat_id} query={query[:200]}")
    try:
        _debug_log("STEP5 calling RAG pipeline...")
        async with async_session_factory() as db:
            answer, sources = await run_knowledge_chat(query=query, db=db, channel="feishu")

        _debug_log(f"STEP6 RAG done answer_len={len(answer)} sources={len(sources)}")

        card = _build_knowledge_card(answer, sources, query)
        _debug_log(f"STEP7 sending card to chat_id={chat_id}")
        await _send_card_to_chat(chat_id, card)
        _debug_log("STEP8 card_sent")

    except Exception:
        _debug_log(f"EXCEPTION: {__import__('traceback').format_exc()}")
        logger.exception("知识库机器人处理异常")
        try:
            await _send_text_to_chat(chat_id, "抱歉，查询过程中出现错误，请稍后重试。")
        except Exception:
            _debug_log("EXCEPTION in error handler too")
