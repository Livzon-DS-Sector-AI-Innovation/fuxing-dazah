"""飞书安全助手统一入口。

监听 ``im.message.receive_v1`` 事件，所有文本消息统一进入业务 Agent（Pydantic AI tool-calling）。
Agent 根据用户意图自动选择工具：知识库检索（knowledge_search）还是业务操作（query_hazards 等）。

- 身份已知用户 → 按角色授权
- 身份未知用户 → viewer 角色（仅只读工具，可查知识库和隐患/检查/事故数据）

确认卡片的回调处理：
    发送确认卡片后，监听 ``card.action.trigger`` 事件获取用户选择并调用
    executor.resume() 执行或取消写操作。

注册方式：在 ``__init__.py`` 中 import 本模块，触发 @on_event 装饰器自动注册。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import uuid
from typing import Any

import httpx

from app.core.database import async_session_factory
from app.modules.safety.business_agent.executor import resume, run_turn
from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.business_agent.session_store import (
    create_pending_action,
    get_or_create_session,
    get_pending_action,
    get_user_role,
    resolve_pending_action,
    save_message,
    set_card_message_id,
    update_session_history,
)
from app.modules.safety.feishu.chat_sender import send_file_to_chat
from app.modules.safety.feishu.client import (
    get_safety_feishu_client,
    get_safety_tenant_token,
)
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.feishu.identity_resolver import IdentityResolver
from app.modules.safety.feishu.notification import update_card as _update_feishu_card
from app.modules.safety.service.oh_archive import (
    OH_UPLOAD_MAX_SIZE,
    ZIP_MAX_TOTAL_SIZE,
    OhArchiveService,
    has_pending_oh_archive,
    looks_like_oh_archive_reply,
)

logger = logging.getLogger(__name__)

_CARD_TITLE = "🤖 安全助手"

# ── Card content limits ──
_MAX_ANSWER_LEN = 12000   # Feishu markdown element practical limit
_MAX_SOURCES = 8          # Max reference items in card

# ── Slash commands ──
_SLASH_COMMANDS: dict[str, str] = {
    "/help": "显示可用指令",
    "/new": "新建会话（清空上下文）",
    "/stop": "停止当前操作",
    "/抄送": "将对话抄送到指定用户（格式：/抄送 姓名）",
}

_HELP_TEXT = (
    "**📋 可用指令**\n\n"
    "| 指令 | 说明 |\n"
    "|------|------|\n"
    "| `/help` | 显示可用指令 |\n"
    "| `/new` | 新建会话，清空对话上下文 |\n"
    "| `/stop` | 停止当前操作 |\n"
    "| `/抄送 姓名` | 将对话抄送给指定人员 |\n\n"
    "**🔍 我能帮您**\n\n"
    "检索安全法律法规、标准规范和管理制度，例如：\n"
    "- 「防爆电气设备安装有哪些标准要求」\n"
    "- 「危险化学品储存安全管理规定」\n"
    "- 「受限空间作业安全规范」\n\n"
    "此外还支持：\n"
    "- 隐患查询与统计（按部门/状态/时间筛选，督办通报）\n"
    "- 法规更新查询\n"
    "- 应急演练计划/记录查询与 AI 演练方案生成\n"
    "- URS 智能审核（创建/评估/审核/申诉/报告导出）\n"
    "- 职业健康管理（人员台账/体检/岗位危害/随访/转岗离岗）\n"
    "- 特殊作业日报生成、MSDS 台账查询\n\n"
    "**💡 使用提示**\n\n"
    "- 直接输入问题即可，我会从知识库检索并给出带法规引用的回答\n"
    '- 提问时尽量具体明确（如「防爆电气安装标准」比「电气安全」更精准）\n'
    "- 每次回答末尾会列出参考法规，点击「查看原文」可跳转原文\n"
    "- 如需开始全新话题，请使用 `/new` 清空上下文\n"
    "- 如需将检索结果分享给同事，请使用 `/抄送 姓名`\n\n"
    "**❓ 为什么需要 `/new`**\n\n"
    "我会记住当前会话的上下文来理解您的连续提问。当您切换到一个全新话题时，旧上下文可能干扰检索结果。使用 `/new` 清空上下文，可以确保每次查询独立、精准。\n\n"
    "**建议在以下情况使用 `/new`**：\n"
    "- 从一个法规话题切换到完全不同的另一个话题\n"
    "- 感觉回答偏离了您想问的方向\n"
    "- 刚进入会话，想从一个干净的状态开始"
)

# ── Feishu API helpers ──


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=lambda o: str(o) if isinstance(o, uuid.UUID) else o)


async def _send_card_to_chat(chat_id: str, card: dict[str, Any]) -> str | None:
    """发送飞书卡片到指定会话。"""
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(_json_dumps(card))
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.acreate(req)
        if not resp.success():
            logger.error("业务 Agent 发送卡片失败: chat_id=%s, code=%s, msg=%s", chat_id, resp.code, resp.msg)
            return None
        return resp.data.message_id if resp.data else None
    except Exception:
        logger.exception("发送飞书卡片异常")
        return None


async def _send_text_to_chat(chat_id: str, text: str) -> None:
    """发送纯文本到飞书会话（降级/错误提示用）。"""
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(_json_dumps({"text": text}))
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        await client.im.v1.message.acreate(req)
    except Exception:
        logger.exception("发送飞书文本异常")


async def _send_file_to_chat(chat_id: str, file_bytes: bytes, file_name: str) -> bool:
    """上传文件到飞书并发送到会话（委托 feishu.chat_sender 叶子模块，行为与旧实现一致）。

    Args:
        chat_id: 飞书 chat_id
        file_bytes: 文件二进制内容
        file_name: 文件名（含扩展名）

    Returns:
        True 表示发送成功
    """
    return await send_file_to_chat(chat_id, file_bytes, file_name)


async def _add_reaction(message_id: str, emoji_type: str) -> None:
    """给飞书消息添加表情回应（轻量社交信号，不阻塞主流程）。

    Feishu 标准 emoji_type 值：
    - OK（👌 知道了）
    - THUMBSUP（👍 赞）
    - HEART（❤️ 爱心）
    - LAUGH（😄 大笑）
    - SURPRISE（😮 惊讶）
    - SAD（😢 难过）
    - ANGRY（😡 愤怒）

    Args:
        message_id: 飞书消息 ID（open_message_id）
        emoji_type: 表情类型字符串
    """
    try:
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)
        from lark_oapi.api.im.v1 import (
            CreateMessageReactionRequest,
            CreateMessageReactionRequestBody,
            Emoji,
        )
        req = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message_reaction.acreate(req)
        if not resp.success():
            logger.debug(
                "添加表情回应失败: message_id=%s emoji=%s code=%s msg=%s",
                message_id, emoji_type, resp.code, resp.msg,
            )
    except Exception:
        logger.debug("添加表情回应异常: message_id=%s", message_id, exc_info=True)


def _build_confirm_card(action_id: str, summary: str) -> dict[str, Any]:
    """构建「执行方案确认」卡片（带确认/取消按钮）。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{_CARD_TITLE} — 操作确认"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": f"📋 **执行方案**\n\n{summary}"},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 确认执行"},
                        "type": "primary",
                        "value": json.dumps({"action": "confirm", "action_id": action_id}),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 取消"},
                        "type": "danger",
                        "value": json.dumps({"action": "cancel", "action_id": action_id}),
                    },
                ],
            },
        ],
    }


def _build_executing_card(summary: str) -> dict[str, Any]:
    """构建「正在执行」卡片（无按钮，展示进度状态）。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{_CARD_TITLE} — 正在执行"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": f"⏳ **正在执行，请稍候...**\n\n{summary}"},
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "执行完成后将自动更新此卡片"}],
            },
        ],
    }


def _build_completed_card(summary: str, result_text: str) -> dict[str, Any]:
    """构建「执行完成」卡片（展示执行结果）。"""
    # 截断过长的结果文本
    result_short = result_text.strip()
    if len(result_short) > 3000:
        result_short = result_short[:3000] + "\n\n…（内容过长已截断）"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{_CARD_TITLE} — 执行完成"},
            "template": "green",
        },
        "elements": [
            {"tag": "markdown", "content": f"✅ **执行完成**\n\n{summary}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": result_short},
        ],
    }


def _build_cancelled_card(summary: str) -> dict[str, Any]:
    """构建「已取消」卡片（无按钮，展示取消状态）。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{_CARD_TITLE} — 已取消"},
            "template": "red",
        },
        "elements": [
            {"tag": "markdown", "content": f"❌ **操作已取消**\n\n{summary}"},
        ],
    }


def _build_reply_card(answer: str, sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """构建普通回复卡片，底部附加「📚 参考法规」链接列表。

    1. 剥离模型自生成的参考区块
    2. 提取正文中 [N] 引用 → 重编号为 [1][2][3]… 顺序
    3. 参考栏只列正文实际引用的文档，编号与正文一致
    """
    import re

    answer_text = _strip_trailing_references(answer.strip())

    # ── 参考法规：去重 + 按正文引用重编号 ──
    if sources:
        # 按 doc_title 去重
        seen: set[str] = set()
        unique_sources: list[dict[str, Any]] = []
        for s in sources:
            title = s.get("doc_title", "未知文档")
            if title not in seen:
                seen.add(title)
                unique_sources.append(s)

        # 提取正文中引用的 [N] 编号（1-based，对应 source 位置）
        cited_old: set[int] = set()
        for m in re.finditer(r"\[(\d+)\]", answer_text):
            n = int(m.group(1))
            if 1 <= n <= len(unique_sources):
                cited_old.add(n)

        if cited_old:
            # old → new 顺序映射：被引用的按原文顺序重排为 [1][2][3]…
            sorted_old = sorted(cited_old)
            mapping: dict[int, int] = {old: new for new, old in enumerate(sorted_old, 1)}

            # 重编号正文中的 [N] 引用
            def _replace_ref(m: re.Match) -> str:
                n = int(m.group(1))
                return f"[{mapping[n]}]" if n in mapping else m.group(0)

            answer_text = re.sub(r"\[(\d+)\]", _replace_ref, answer_text)

            # 只保留被引用的 source，按新编号顺序
            cited_sources = [unique_sources[old - 1] for old in sorted_old]
        else:
            # 正文无引用标记 → 不显示参考栏
            cited_sources = []
    else:
        cited_sources = []

    if len(answer_text) > _MAX_ANSWER_LEN:
        answer_text = answer_text[:_MAX_ANSWER_LEN] + "\n\n…（回答过长已截断，请在平台网页端查看完整回答）"

    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": answer_text}]

    # ── 参考法规栏（仅列出正文实际引用的文档）──
    if cited_sources:
        ref_lines = ["**📚 参考法规**"]
        for i, s in enumerate(cited_sources[:_MAX_SOURCES], 1):
            title = s.get("doc_title", "未知文档")
            url = s.get("feishu_url", "")
            line = f"**[{i}] {title}**"
            if url:
                line += f"  <a href='{url}'>查看原文</a>"
            ref_lines.append(line)

        if len(cited_sources) > _MAX_SOURCES:
            ref_lines.append(f"*…等共 {len(cited_sources)} 部法规*")

        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": "\n".join(ref_lines)})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": _CARD_TITLE},
            "template": "blue",
        },
        "elements": elements,
    }


def _strip_trailing_references(text: str) -> str:
    """移除文本末尾模型可能追加的参考法规/关联制度文件等列表区块。

    检测模式：
    1. 含 "参考法规" / "关联制度文件" / "法规依据" / "参考来源" / "📚" 的标题块
    2. 末尾连续的 "[N] ..." 或 "《...》[N]" 引用行（模型自生成的纯列表）
    """
    if not text:
        return text

    import re

    # ── 模式 1：含关键词标题的区块 ──
    # 找所有关键词中最靠前（最先出现）的位置，从此处截断
    best_pos = len(text)
    for keyword in ("参考法规", "关联制度文件", "法规依据", "参考来源"):
        pos = text.rfind(keyword)  # rfind: 最后一个（模型可能在末尾追加）
        if 0 <= pos < best_pos:
            best_pos = pos
    if best_pos < len(text):
        before = text[:best_pos]
        for sep in ("\n---", "\n**", "\n📚", "\n- "):
            sep_pos = before.rfind(sep)
            if sep_pos > 0 and best_pos - sep_pos < 500:
                return text[:sep_pos].rstrip()
        if best_pos > len(text) * 0.6:
            return text[:best_pos].rstrip()

    # ── 模式 2：末尾连续的编号引用行 ──
    # 匹配: "[N] 《法规》 — 查看原文"、"《法规》[N]"、"[N] 法规名 — 查看原文"
    _ref_line_re = re.compile(
        r"^(\[(\d+)\]\s+.+查看原文"          # [N] 《法规》 — [查看原文](url)
        r"|《[^》]+》\[(\d+)\].*"             # 《法规名》[N]
        r"|\[(\d+)\]\s+《[^》]+》"            # [N] 《法规名》
        r")"
    )
    lines = text.split("\n")
    ref_start = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if _ref_line_re.match(stripped):
            ref_start = i
        else:
            break

    if ref_start is not None:
        ref_count = sum(
            1 for j in range(ref_start, len(lines))
            if _ref_line_re.match(lines[j].strip())
        )
        if ref_count >= 2:
            cut = ref_start
            while cut > 0 and (
                not lines[cut - 1].strip()
                or lines[cut - 1].strip().startswith("---")
                or lines[cut - 1].strip().startswith("**")
                or lines[cut - 1].strip().startswith("- ")
            ):
                cut -= 1
            return "\n".join(lines[:cut]).rstrip()

    return text


# ── Slash command handler ──


async def _handle_slash_command(
    cmd: str,
    args: str,
    chat_id: str,
    db: Any,
    feishu_user_id: str | None,
) -> bool:
    """处理斜杠指令，返回 True 表示已处理（无需再走 Agent）。

    Args:
        cmd: 指令（如 /help）
        args: 指令后的参数（如 /抄送 张三 中的 "张三"）
        chat_id: 飞书 chat_id
        db: 数据库会话
        feishu_user_id: 发送者 feishu_user_id

    Returns:
        True 表示指令已处理，调用方应直接 return；
        False 表示不是已知指令，调用方应继续走 Agent。
    """
    from app.modules.safety.business_agent.session_store import (
        get_or_create_session as _gos,
    )

    if cmd == "/help":
        card = _build_reply_card(_HELP_TEXT)
        await _send_card_to_chat(chat_id, card)
        return True

    if cmd == "/new":
        # 软删除旧会话，下次 get_or_create_session 会创建新的
        try:
            from sqlalchemy import update

            from app.modules.safety.business_agent.models import AgentSession

            stmt = (
                update(AgentSession)
                .where(
                    AgentSession.channel == "feishu",
                    AgentSession.chat_id == chat_id,
                    AgentSession.is_deleted == False,  # noqa: E712
                )
                .values(is_deleted=True)
            )
            await db.execute(stmt)
            await db.flush()
        except Exception:
            logger.exception("软删除旧会话失败")
        card = _build_reply_card("✅ 已新建会话，上下文已清空。请继续输入您的问题。")
        await _send_card_to_chat(chat_id, card)
        return True

    if cmd == "/stop":
        card = _build_reply_card("⏹ 飞书端无需此指令（消息为非流式响应，每次对话完成后自动结束）。")
        await _send_card_to_chat(chat_id, card)
        return True

    if cmd == "/抄送":
        if not args:
            card = _build_reply_card("📨 **抄送到飞书**\n\n请指定收件人姓名，格式：`/抄送 张三`")
            await _send_card_to_chat(chat_id, card)
            return True

        target_name = args.strip()
        # 解析目标用户
        resolver = IdentityResolver(db)
        persons = await resolver.resolve_by_name(target_name)
        if not persons:
            card = _build_reply_card(f"❌ 未找到用户「{target_name}」，请确认姓名后重试。")
            await _send_card_to_chat(chat_id, card)
            return True

        target_person = persons[0]
        target_open_id = target_person.open_id
        if not target_open_id:
            card = _build_reply_card(f"❌ 用户「{target_name}」缺少飞书 open_id，无法发送私聊消息。")
            await _send_card_to_chat(chat_id, card)
            return True

        # 获取最近一条 Agent 回复
        try:
            session = await _gos(db, channel="feishu", chat_id=chat_id)
            history = session.message_history
            last_answer = ""
            if isinstance(history, list) and history:
                # 从消息历史提取最后一条 agent 回复文本
                for msg in reversed(history):
                    parts = msg.get("parts", []) if isinstance(msg, dict) else []
                    for part in parts:
                        if part.get("part_kind") == "text":
                            last_answer = part.get("content", "")
                            break
                    if last_answer:
                        break
            if not last_answer:
                card = _build_reply_card("❌ 当前会话没有可抄送的内容。")
                await _send_card_to_chat(chat_id, card)
                return True
        except Exception:
            logger.exception("获取会话历史失败")
            card = _build_reply_card("❌ 获取会话内容失败，请稍后重试。")
            await _send_card_to_chat(chat_id, card)
            return True

        # 发送抄送卡片给目标用户
        from app.modules.safety.feishu.notification import send_user_card

        cc_content = (
            f"📨 **安全管理AI助手 · 对话抄送**\n\n"
            f"抄送人：{target_name}\n\n---\n\n"
            f"{last_answer[:3000]}"
        )
        sent = await send_user_card(
            open_id=target_open_id,
            title="安全管理AI助手 · 对话抄送",
            content=cc_content,
        )
        if sent:
            card = _build_reply_card(f"✅ 已抄送给 **{target_name}**。")
        else:
            card = _build_reply_card("❌ 抄送失败，请稍后重试。")
        await _send_card_to_chat(chat_id, card)
        return True

    return False


# ── 身份解析 ──


async def _resolve_sender(db: Any, event_data: dict[str, Any]) -> tuple[str | None, SafetyDeps]:
    """从事件数据中解析发送者身份并构建 SafetyDeps。

    身份未知用户 → viewer 角色（仅只读工具：knowledge_search / query_hazards 等）。
    """
    sender = event_data.get("sender", {})
    sender_id = sender.get("sender_id", {})
    feishu_user_id = sender_id.get("user_id") or sender_id.get("open_id")

    # 当前飞书会话 chat_id（工具回传文件用；缺失时置 None 走降级提示）
    chat_id = event_data.get("message", {}).get("chat_id", "") or None

    person = None
    role = "viewer"  # 默认只读

    if feishu_user_id:
        resolver = IdentityResolver(db)
        person = await resolver.resolve_by_user_id(feishu_user_id)
        if person:
            role = await get_user_role(db, feishu_user_id) or "viewer"

    deps = SafetyDeps(
        db=db, person=person, role=role, session_id="", channel="feishu", chat_id=chat_id,
    )
    return feishu_user_id, deps


# ── 事件处理 ──


# ── 文件消息支持 ──

# OH 归档文件扩展名（L3 单文件 PDF/图片；L4 压缩包；设计 §13.6.2）
_OH_ARCHIVE_EXTS: frozenset[str] = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".zip"})

# OH 归档下载临时文件目录（service 处理完成后清理）
_OH_BOT_TMP_DIR = "uploads/safety/oh_bot"


async def _download_message_file(message_id: str, file_key: str) -> bytes:
    """从飞书消息中下载文件附件。

    飞书 API: GET /open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=file

    返回文件二进制内容；失败时抛出异常。
    """
    token = await get_safety_tenant_token()
    url = (
        "https://open.feishu.cn/open-apis/im/v1/messages/"
        f"{message_id}/resources/{file_key}"
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
        resp = await http.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"type": "file"},
        )
        # 飞书文件下载成功时返回二进制，失败时返回 JSON
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type or resp.status_code >= 400:
            try:
                data = resp.json()
                raise RuntimeError(
                    f"code={data.get('code')} msg={data.get('msg', 'unknown')}"
                )
            except (json.JSONDecodeError, RuntimeError) as e:
                if isinstance(e, RuntimeError):
                    raise
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}") from e
        resp.raise_for_status()
        return resp.content


async def _handle_oh_archive_file(message: dict[str, Any], chat_id: str) -> None:
    """L3/L4 OH 归档文件处理（仅私聊调用）：下载 → 落盘 → OhArchiveService 编排 → 回复。

    - L3：PDF/图片单文件 → match_exam 匹配（体检号/姓名）→ 上传 Bitable → 回复
      归档结果 + AI 解析状态；匹配失败回复询问，用户回复后二次匹配
      （`_try_oh_archive_reply`，本轮会话内生效，A2 不持久化）。
    - L4：zip → extract_zip 安全解压（§13.6.5）→ 逐文件匹配 + 串行上传 → 回复汇总。
    """
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
    except json.JSONDecodeError:
        await _send_text_to_chat(chat_id, "抱歉，无法解析文件消息格式。")
        return
    file_key = content.get("file_key", "")
    file_name = content.get("file_name", "unknown.file")
    message_id = message.get("message_id", "")
    if not file_key or not message_id:
        await _send_text_to_chat(chat_id, "抱歉，无法获取文件信息，请重试。")
        return

    try:
        file_bytes = await _download_message_file(message_id, file_key)
    except Exception as e:
        logger.warning("OH 归档文件下载失败: chat_id=%s file=%s err=%s", chat_id, file_name, e)
        await _send_text_to_chat(
            chat_id,
            f"❌ 文件下载失败，请确认文件仍可访问后重试。\n\n技术详情：{e}",
        )
        return

    # 大小预检（L3 单文件 ≤50MB；L4 压缩包按解压后总量限制兜底）
    ext = os.path.splitext(file_name)[1].lower()
    limit = OH_UPLOAD_MAX_SIZE if ext != ".zip" else ZIP_MAX_TOTAL_SIZE
    if len(file_bytes) > limit:
        await _send_text_to_chat(
            chat_id,
            f"❌ 文件过大（超过 {limit // (1024 * 1024)}MB），请压缩后重试。",
        )
        return

    # 落盘临时文件（uuid 命名，保留原始文件名供匹配/上传展示）
    os.makedirs(_OH_BOT_TMP_DIR, exist_ok=True)
    path = os.path.join(_OH_BOT_TMP_DIR, f"{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as f:
        f.write(file_bytes)

    try:
        async with async_session_factory() as db:
            svc = OhArchiveService(db)
            result = await svc.archive_and_reply(
                chat_id=chat_id, file_path=path, file_name=file_name,
            )
    except Exception:
        logger.exception("OH 归档处理失败: chat_id=%s file=%s", chat_id, file_name)
        if os.path.exists(path):
            os.remove(path)
        await _send_text_to_chat(chat_id, "❌ 归档处理失败，请稍后重试或联系管理员。")
        return

    reply = result.get("reply") or ""
    if reply:
        await _send_text_to_chat(chat_id, reply)


async def _try_oh_archive_reply(chat_id: str, text: str) -> bool:
    """OH 归档二次匹配（设计 §13.6.3，A2：本轮会话内生效，不持久化）。

    有挂起归档（匹配失败等待回复 / 多条候选选序号）且文本像姓名/体检号/序号时
    拦截处理；其余情况返回 False 继续正常 Agent 流程。

    Returns:
        True — 已直接回复用户（不再走 Agent）；False — 继续正常流程。
    """
    if not looks_like_oh_archive_reply(text):
        return False
    if not has_pending_oh_archive(chat_id):
        return False
    async with async_session_factory() as db:
        svc = OhArchiveService(db)
        result = await svc.archive_and_reply(chat_id=chat_id, reply_text=text)
    if result.get("status") in ("fallthrough", "no_pending"):
        return False
    reply = result.get("reply") or ""
    if reply:
        await _send_text_to_chat(chat_id, reply)
    return True


async def _handle_file_message(message: dict[str, Any], chat_id: str) -> Any:
    """处理飞书文件消息：仅支持职业健康归档文件（L3 单文件 / L4 压缩包），其余类型提示不支持。

    只处理 OH 归档；不返回合成查询文本，非归档文件直接回复用户。
    """
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
    except json.JSONDecodeError:
        await _send_text_to_chat(chat_id, "抱歉，无法解析文件消息格式。")
        return None

    file_key = content.get("file_key", "")
    file_name = content.get("file_name", "unknown.file")
    message_id = message.get("message_id", "")

    if not file_key or not message_id:
        await _send_text_to_chat(chat_id, "抱歉，无法获取文件信息，请重试。")
        return None

    # 检查文件类型
    ext = file_name[file_name.rfind("."):].lower() if "." in file_name else ""
    if ext not in _OH_ARCHIVE_EXTS:
        await _send_text_to_chat(
            chat_id,
            f"📎 收到文件「{file_name}」，但我目前只支持职业健康归档相关的 "
            f"PDF / 图片（.pdf/.jpg/.jpeg/.png）或压缩包（.zip）文件。\n\n"
            f"如需上传其他文件，请在 Web 平台操作。",
        )
        return None

    # OH 归档（L3 单文件 / L4 压缩包）：仅私聊响应；群聊落到下方「不支持」原提示
    if message.get("chat_type") == "p2p":
        logger.info("安全助手: chat_id=%s OH 归档文件 %s (L3/L4)", chat_id, file_name)
        await _handle_oh_archive_file(message, chat_id)
        return None

    await _send_text_to_chat(
        chat_id,
        f"📎 收到文件「{file_name}」。该类文件请在私聊中发送以便处理。",
    )
    return None


def _extract_text_query(message: dict[str, Any]) -> str | None:
    """从飞书文本消息中提取查询文本。

    返回：
        str — 有效的查询文本
        None — 消息无效
    """
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
    except json.JSONDecodeError:
        return None
    query = (content.get("text", "") or "").strip()
    if not query:
        return None

    # 去除 @mention
    import re
    query = re.sub(r'@\S+', '', query).strip()
    return query or None


def _has_at_mention_only(message: dict[str, Any]) -> bool:
    """检查文本消息是否仅包含 @mention 无实质内容。"""
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
    except json.JSONDecodeError:
        return False
    raw = (content.get("text", "") or "").strip()
    if not raw:
        return False
    import re
    return not re.sub(r'@\S+', '', raw).strip()


# @所有人 在 content 文本中的表示（新老格式 + 各 id 属性 + 大小写变体）。
# 覆盖：<at user_id="all">、<at id="all">、<at open_id="all">、@_all、@all、@全体成员 等。
_AT_ALL_TEXT_PATTERNS = (
    # <at user_id="all" ...>（属性顺序任意、大小写不敏感；兼容 id/open_id/union_id/id="all"）
    re.compile(r'<at[^>]*(?:user_id|open_id|union_id|id)="all"', re.IGNORECASE),
    re.compile(r"<at[^>]*(?:user_id|open_id|union_id|id)='all'", re.IGNORECASE),
    # 纯文本 token：@_all（旧格式）、@all（部分客户端）
    # 用负向前瞻防止把 `@_allocation` 之类误判为 @all，同时允许多语言字符紧跟其后
    re.compile(r"@_all(?![A-Za-z0-9_])", re.IGNORECASE),
    re.compile(r"@all(?![A-Za-z0-9_])", re.IGNORECASE),
    # 中文文本兜底
    re.compile(r"@全体成员"),
    re.compile(r"@全体人员"),
    re.compile(r"@全员"),
    re.compile(r"@全体"),
    re.compile(r"@所有人"),
)


def _has_at_all_mention(message: dict[str, Any]) -> bool:
    """检查消息是否 @所有人（@all）。

    @所有人 的消息通常是群发通知，机器人不应回复。
    飞书事件中 @所有人 的多种表示（新老格式 / 不同 id 属性 / 大小写变体）：
    1. mentions 数组中 key 为 @_all / all / id 各字段为 all / name 为「所有人」等
    2. content 文本中的 <at user_id="all">（新格式）或 @_all / @all / @所有人（文本格式）
    """
    # ── mentions 数组（事件自带的结构化提及列表）──
    for m in message.get("mentions") or []:
        if not isinstance(m, dict):
            continue
        key = (m.get("key") or "").lower()
        if key in ("@_all", "all") or key.startswith("@_all"):
            return True
        mid = m.get("id") or {}
        if isinstance(mid, dict) and any(str(v).lower() == "all" for v in mid.values()):
            return True
        if (m.get("name") or "") in ("所有人", "全体成员", "全员", "全体人员", "全体"):
            return True

    # ── content 文本兜底（mentions 缺失/解析失败/结构不同时）──
    content_str = message.get("content", "{}")
    text = content_str
    try:
        content = json.loads(content_str)
        if isinstance(content, dict):
            text = content.get("text", "") or ""
    except (json.JSONDecodeError, TypeError):
        pass
    # 同时扫描未转义的 text 与原始 content_str（post/multi 结构里 token 可能不在顶层 text）
    return any(p.search(text) for p in _AT_ALL_TEXT_PATTERNS) or any(
        p.search(content_str) for p in _AT_ALL_TEXT_PATTERNS
    )


# ── 群聊：仅直接 @ 机器人才回复 ──

# 安全助手机器人自身的飞书 open_id（群成员里名称「安全管理机器人」）。
# 机器人重建后会变化，故允许用环境变量覆盖；默认值取自当前租户。
_SAFETY_BOT_OPEN_ID = os.getenv(
    "SAFETY_FEISHU_BOT_OPEN_ID", "ou_33d2fe6a5714c4e808248c05cf66205a"
)
# content 文本里 @ 机器人的几种显示名（含旧叫法），作为 mentions 缺失时的兜底
_SAFETY_BOT_NAMES: tuple[str, ...] = ("安全助手", "安全管理机器人", "安全机器人", "安全员助手")


def _is_bot_directly_mentioned(message: dict[str, Any]) -> bool:
    """群聊中判断消息是否「直接 @ 了本机器人」。

    只有直接 @ 机器人才回复；@所有人、无@、@其他用户均视为未直接@机器人（不回复）。

    判定来源：
    1. ``mentions`` 数组里包含机器人自身 open_id / user_id
    2. ``content.text`` 里 @ 机器人名（兜底）
    """
    # ── mentions 数组（结构化提及）──
    for m in message.get("mentions") or []:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        ids = [str(v) for v in mid.values()] if isinstance(mid, dict) else ([str(mid)] if mid else [])
        if _SAFETY_BOT_OPEN_ID in ids:
            return True

    # ── content 文本兜底：@机器人名 ──
    text = _raw_text_from_message(message)
    for name in _SAFETY_BOT_NAMES:
        if f"@{name}" in text:
            return True
    return False


def _is_quoted_message(message: dict[str, Any]) -> bool:
    """检查消息是否为「引用 / 回复」消息。

    飞书引用（回复）消息通过 ``message.parent_id`` / ``message.root_id`` 标识
    （二者非空即处于回复消息树中；普通发言均为空）。

    引用消息的上下文可能内嵌被引用内容（如机器人历史消息、或历史 @ 过机器人的消息），
    其中含 ``@安全助手`` / ``@_all`` 等关键词，会让 @ 判断误判为「直接@机器人」/「@所有人」，
    导致机器人错误回复引用场景。群聊中对引用消息统一跳过（不回复）。
    """
    return bool(message.get("parent_id") or message.get("root_id"))


# ── Office 云文档/文件链接识别与 Agent 提示注入（T05）──

# 链接 path 段 → office 资源类型（供 Agent 选择对应只读工具）
_OFFICE_LINK_KIND_BY_PATH: dict[str, str] = {
    "docx": "docx",
    "docs": "docx",
    "sheet": "sheet",
    "sheets": "sheet",
    "base": "bitable",
    "wiki": "wiki",
    "slides": "slides",
    "file": "file",
}

_OFFICE_LINK_RE = re.compile(
    r"https?://[^\s<>)]+\.feishu\.cn/"
    r"(docx|docs|sheets?|base|wiki|slides|file)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# 显式「文档/表格 token xxx」形式，避免把普通文本里的 token 字样误判为办公路由
_OFFICE_TOKEN_REFERENCE_RE = re.compile(
    r"(云文档|文档|电子表格|表格|多维表格|知识库|幻灯片|文件|docx|sheet|base|"
    r"wiki|slides|file)\s*(?:token|标识|id)?\s*[：:，,\s]+"
    r"(?P<token>[A-Za-z0-9_-]{6,})",
    re.IGNORECASE,
)

_OFFICE_TOKEN_KIND_BY_LABEL: dict[str, str] = {
    "云文档": "docx",
    "文档": "docx",
    "docx": "docx",
    "电子表格": "sheet",
    "表格": "sheet",
    "sheet": "sheet",
    "多维表格": "bitable",
    "base": "bitable",
    "知识库": "wiki",
    "wiki": "wiki",
    "幻灯片": "slides",
    "slides": "slides",
    "文件": "file",
    "file": "file",
}


def detect_office_link(text: str) -> dict[str, Any] | None:
    """从文本中识别飞书云文档/表格/多维表格/知识库/幻灯片/文件链接。

    Returns:
        {"kind": "url", "resource_type", "url", "token"} 或 None。
        本函数只做纯文本识别，无飞书调用。
    """
    if not text:
        return None
    match = _OFFICE_LINK_RE.search(text)
    if not match:
        return None
    resource_type = _OFFICE_LINK_KIND_BY_PATH.get(match.group(1).lower(), "file")
    return {
        "kind": "url",
        "resource_type": resource_type,
        "url": match.group(0),
        "token": match.group(2),
    }


def detect_office_token_reference(text: str) -> dict[str, Any] | None:
    """识别显式「文档/表格 token xxx」形式，避免误触普通业务文本。"""
    if not text:
        return None
    match = _OFFICE_TOKEN_REFERENCE_RE.search(text)
    if not match:
        return None
    label = match.group(1).lower()
    return {
        "kind": "token",
        "resource_type": _OFFICE_TOKEN_KIND_BY_LABEL.get(label, "file"),
        "token": match.group("token"),
    }


def detect_office_reference(text: str) -> dict[str, Any] | None:
    """识别 office 云文档链接或显式文件 token。"""
    return detect_office_link(text) or detect_office_token_reference(text)


def _raw_text_from_message(message: dict[str, Any]) -> str:
    """从飞书消息 dict 中提取原始文本（不 strip @mention）。"""
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return content_str if isinstance(content_str, str) else ""
    if isinstance(content, dict):
        return (content.get("text", "") or "") if isinstance(content, dict) else ""
    return ""


def detect_office_reference_in_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """从飞书消息中识别 office 引用；非文本消息直接返回 None。

    纯文件消息（message_type=file）与 @所有人 通知没有 office 链接/token 时，
    均返回 None，不会抢占既有分支。
    """
    if message.get("message_type") != "text":
        return None
    return detect_office_reference(_raw_text_from_message(message))


def _office_hint(ref: dict[str, Any]) -> str:
    """生成给 Agent 的 office 路由提示。"""
    if ref.get("kind") == "url":
        return (
            f"（系统检测到飞书云文档链接：{ref['url']}，资源类型 "
            f"{ref['resource_type']}。请优先使用对应只读办公工具读取链接内容："
            "docx 用 office_read_docx、sheet 用 office_read_sheet、"
            "bitable 用 office_read_base、普通文件用 office_read_drive_file，"
            "读取后用中文总结并回复用户。）"
        )
    return (
        f"（系统检测到用户指明了飞书文件 token：{ref['token']}，资源类型 "
        f"{ref['resource_type']}。请优先使用对应只读办公工具读取该 token，"
        "读取后用中文总结并回复用户。）"
    )


def augment_office_query(query: str) -> str:
    """把 office 链接/token 识别结果作为提示注入用户消息，复用 Agent 主流程。"""
    ref = detect_office_reference(query)
    if not ref:
        return query
    return f"{query}\n\n{_office_hint(ref)}"


@on_event("im.message.receive_v1")
async def handle_message(event_data: dict[str, Any]) -> None:
    """统一消息入口：文本消息 + 文件消息均进入业务 Agent。

    - 文本消息：直接传给 Agent，由模型决定调用知识库还是业务工具。
    - 文件消息（Excel/CSV/JSON）：Bot 下载文件 → 调平台工具解析 →
      将结构化预览注入 Agent 对话，由 Agent 继续与用户交互确认。
    """
    try:
        message = event_data.get("message", {})
        chat_id = message.get("chat_id", "")
        message_type = message.get("message_type", "")
        if not chat_id:
            return

        # ── 危险品日报群的文件消息：由 chemical_inventory_daily_handler 处理，不进 Agent ──
        if chat_id == "oc_ae9c3a305430cb196e42130f69b052bc" and message_type == "file":
            return

        # ── 群聊：仅直接 @ 机器人才回复 ──
        # 机器人在群聊里开启了「接收所有群消息」，会收到 @所有人、无@、@他人的消息；
        # 按固定设置，群聊中只有直接 @ 机器人才回复，其余一律跳过（不回复、不点赞、不进 Agent）。
        if message.get("chat_type") == "group":
            # 引用/回复消息（parent_id/root_id 非空）：被引用内容可能带 @机器人的关键词，
            # 会污染 @ 判断导致误回复 —— 引用场景统一跳过。
            if _is_quoted_message(message):
                logger.info(
                    "安全助手: 群聊引用消息，跳过 chat_id=%s type=%s message_id=%s",
                    chat_id, message_type, message.get("message_id", ""),
                )
                return
            if not _is_bot_directly_mentioned(message):
                logger.info(
                    "安全助手: 群聊且未直接@机器人，跳过 chat_id=%s type=%s message_id=%s",
                    chat_id, message_type, message.get("message_id", ""),
                )
                return

        # ── @所有人 消息不回复 ──
        # 群聊中 @所有人 通常是群发通知，机器人直接跳过（不回复、不点赞、不进 Agent）。
        if _has_at_all_mention(message):
            logger.info(
                "安全助手: 跳过 @所有人 消息 chat_type=%s type=%s message_id=%s",
                message.get("chat_type", ""), message_type,
                message.get("message_id", ""),
            )
            return

        # ── 文件消息：仅 OH 归档（L3/L4）处理，其余类型直接回复；不走 Agent ──
        if message_type == "file":
            await _handle_file_message(message, chat_id)
            return
        elif message_type == "text":
            query = _extract_text_query(message)
            if query is None:
                # 检查是否为纯 @mention（无实质内容）→ 回复引导
                if _has_at_mention_only(message):
                    await _send_text_to_chat(
                        chat_id,
                        "您好！我是安全助手，专注于安全法规与制度检索。\n\n"
                        "直接输入问题即可查询（如「防爆电气安装有哪些标准」）。\n\n"
                        "💡 输入 /help 查看可用指令和使用技巧。",
                    )
                return
            # ── OH 归档二次匹配（L3/L4，仅私聊 + 有挂起归档 + 文本像姓名/体检号/序号）──
            if message.get("chat_type") == "p2p":
                if await _try_oh_archive_reply(chat_id, query):
                    return
        else:
            return

        logger.info("安全助手: chat_id=%s query=%s", chat_id, query[:100])

        # ── 表情回应：让用户知道 Agent 已收到消息 ──
        message_id = message.get("message_id", "")
        if message_id:
            await _add_reaction(message_id, "OK")

        # ── Slash command interception ──
        if query.startswith("/"):
            space_idx = query.find(" ")
            cmd = query[:space_idx] if space_idx > 0 else query
            args = query[space_idx + 1:] if space_idx > 0 else ""
            known_cmd = _SLASH_COMMANDS.get(cmd)
            if known_cmd:
                async with async_session_factory() as db:
                    feishu_user_id, _deps = await _resolve_sender(db, event_data)
                    handled = await _handle_slash_command(
                        cmd, args.strip(), chat_id, db, feishu_user_id,
                    )
                    if handled:
                        await db.commit()
                if handled:
                    return
                # 如果命令未被处理（不应该发生），fall through to Agent

        # ── Office 链接/token 增强：识别后注入提示，复用 Agent 主流程 ──
        query = augment_office_query(query)

        async with async_session_factory() as db:
            feishu_user_id, deps = await _resolve_sender(db, event_data)

            # 获取/创建会话
            session = await get_or_create_session(
                db, channel="feishu", chat_id=chat_id,
                user_id=feishu_user_id, role=deps.role,
            )
            deps.session_id = str(session.id)

            # 恢复历史
            history = session.message_history if isinstance(session.message_history, list) else None

            # 执行
            result = await run_turn(query, deps, message_history=history)

            # 持久化
            pending_action_id = None
            if result.get("pending_action"):
                pending = result["pending_action"]
                pa_record = await create_pending_action(
                    db, session_id=session.id, pending=pending,
                    message_history_snapshot=result["messages"],
                )
                pending_action_id = str(pa_record.id)

            await update_session_history(
                db, session, messages=result["messages"],
                title=query[:80] if session.message_count == 0 else None,
            )
            await save_message(
                db, session_id=session.id, user_message=query,
                agent_answer=result["answer"],
                pending_action_id=uuid.UUID(pending_action_id) if pending_action_id else None,
            )
            await db.commit()

        # 发送回复
        if pending_action_id and result.get("pending_action"):
            card = _build_confirm_card(pending_action_id, result["pending_action"].summary)
            msg_id = await _send_card_to_chat(chat_id, card)
            # 存储卡片的 message_id，用于后续按钮点击后更新卡片状态
            if msg_id:
                async with async_session_factory() as db2:
                    await set_card_message_id(db2, pending_action_id, msg_id)
                    await db2.commit()
        else:
            card = _build_reply_card(result["answer"], sources=result.get("sources"))
            await _send_card_to_chat(chat_id, card)

    except Exception as _e:
        logger.exception("业务 Agent 消息处理异常")
        try:
            chat_id = event_data.get("message", {}).get("chat_id", "")
            if chat_id:
                await _send_text_to_chat(chat_id, f"抱歉，处理过程中出现错误：{type(_e).__name__}: {_e}\n\n请截图此错误信息发给开发者排查，然后输入/new重置会话后再尝试提问。")
        except Exception:
            pass


@on_event("card.action.trigger")
async def handle_card_action(event_data: dict[str, Any]) -> dict[str, Any] | None:
    """处理卡片按钮回调（确认/取消写操作）。

    参照隐患复核通知的同款模式：
    - 快速路径（同步返回）→ ACK 帧中携带卡片更新 → 飞书立即渲染
    - 慢操作（LLM + 工具执行）→ 后台任务 → 完成后 PATCH 卡片为最终状态

    Returns:
        dict → event_client 将其序列化放入 ACK payload，飞书据此更新卡片。
        None → 降级为 {"code": 200}，卡片不变。
    """
    try:
        action_value = event_data.get("action", {}).get("value", "{}")
        try:
            payload = json.loads(action_value)
            # Feishu 对 value 字段做双重 JSON 编码（卡片 JSON 序列化 + 事件 JSON 序列化）
            # 一次 json.loads 可能只解出内层字符串，需要再解一次才能得到 dict
            if isinstance(payload, str):
                payload = json.loads(payload)
        except json.JSONDecodeError:
            return None

        action = payload.get("action")
        action_id = payload.get("action_id")

        # ── 督办催办卡片提交路由（form 提交按钮，name 携带 hazard_id）──
        # form 表单回调中 action.value 不一定随回调返回，但 action.name 必然存在。
        # 按钮 name 形如 progress_submit_<hazard_id>，据此路由并提取 hazard_id。
        action_name = event_data.get("action", {}).get("name", "")
        # 直读多维表格模式：name 形如 progress_submit_rec_<record_id> → 直写 Bitable
        if action_name.startswith("progress_submit_rec_"):
            record_id = action_name[len("progress_submit_rec_"):]
            if record_id:
                from app.modules.safety.feishu.progress_card import (
                    handle_progress_submit_direct,
                )

                return await handle_progress_submit_direct(record_id, event_data)
        if action_name.startswith("progress_submit_"):
            hazard_id_str = action_name[len("progress_submit_"):]
            if hazard_id_str:
                payload = {
                    "scope": "progress_update",
                    "hazard_id": hazard_id_str,
                    "action": "submit",
                }
                from app.modules.safety.feishu.progress_card import (
                    handle_progress_submit,
                )

                return await handle_progress_submit(payload, event_data)

        # ── URS 审核卡片回调路由（scope=urs，非 Agent 写操作确认流）──
        if payload.get("scope") == "urs":
            from app.modules.safety.feishu.urs_card import handle_urs_card_action

            return await handle_urs_card_action(payload, event_data)

        # ── 督办催办卡片提交路由（scope=progress_update）──
        if payload.get("scope") == "progress_update":
            from app.modules.safety.feishu.progress_card import handle_progress_submit

            return await handle_progress_submit(payload, event_data)

        if not action or not action_id:
            return None

        approved = action == "confirm"
        logger.info("业务 Agent 卡片回调: action_id=%s action=%s", action_id, action)

        # ── 快速路径：读 DB + 返回卡片更新（不等待 LLM）──
        async with async_session_factory() as db:
            pa = await get_pending_action(db, action_id)
            if pa is None or pa.status != "pending":
                logger.warning(
                    "卡片回调: action_id=%s 不存在或已处理 status=%s",
                    action_id, pa.status if pa else "?",
                )
                return None

            summary = pa.summary or ""
            card_msg_id = pa.card_message_id  # 可能为 None（旧卡片）

            chat_id = (
                event_data.get("open_chat_id", "")
                or event_data.get("message", {}).get("chat_id", "")
            )
            operator_id = (
                event_data.get("operator", {}).get("user_id")
                or event_data.get("operator", {}).get("open_id")
            )

        # ── 后台任务：慢操作（resume → LLM → 工具 → DB 更新 → PATCH 卡片）──
        asyncio.create_task(
            _execute_pending_action_background(
                action_id=action_id,
                approved=approved,
                chat_id=chat_id,
                operator_id=operator_id,
                card_msg_id=card_msg_id,
                summary=summary,
            )
        )

        # ── ACK 立即返回卡片更新 ──
        if approved:
            return {
                "toast": {"type": "success", "content": "正在执行，请稍候..."},
                "card": {"type": "raw", "data": _build_executing_card(summary)},
            }
        else:
            return {
                "toast": {"type": "success", "content": "操作已取消"},
                "card": {"type": "raw", "data": _build_cancelled_card(summary)},
            }

    except Exception:
        logger.exception("业务 Agent 卡片回调处理异常")
        return None


# ── Office 写工具产物交付（T05）──

_OFFICE_ARTIFACT_TOOL_NAMES: frozenset[str] = frozenset({
    "office_create_docx",
    "office_create_sheet",
    "office_write_sheet",
    "office_create_base",
    "office_create_slides",
    "office_generate_docx_pdf",
    "office_upload_file",
    "office_set_permission",
})


def extract_office_artifacts(
    messages: list[dict[str, Any]],
    *,
    tool_names: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """从 Agent 消息历史中提取 office 写工具返回的 link/file 产物。

    仅扫描写工具（默认 _OFFICE_ARTIFACT_TOOL_NAMES），避免把只读下载文件
    误当成待交付产物。返回产物列表，每项为：
    - {"kind": "file", "bytes", "file_name", "tool_name"}
    - {"kind": "link", "url", "message", "tool_name"}
    """
    allowed = tool_names if tool_names is not None else _OFFICE_ARTIFACT_TOOL_NAMES
    artifacts: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        for part in msg.get("parts", []):
            if not isinstance(part, dict):
                continue
            if part.get("part_kind") != "tool_return":
                continue
            if part.get("tool_name") not in allowed:
                continue

            content = part.get("content")
            if not isinstance(content, dict):
                continue

            kind = content.get("kind")
            if kind == "file":
                file_b64 = content.get("content_base64")
                file_name = content.get("file_name") or "office-file"
                if not file_b64:
                    continue
                try:
                    file_bytes = base64.b64decode(file_b64)
                except Exception:
                    logger.exception("解码 office 文件 base64 失败")
                    continue
                artifacts.append({
                    "kind": "file",
                    "bytes": file_bytes,
                    "file_name": file_name,
                    "tool_name": part.get("tool_name"),
                })
            elif kind == "link":
                url = content.get("url")
                if not url:
                    continue
                artifacts.append({
                    "kind": "link",
                    "url": url,
                    "message": content.get("message") or "",
                    "tool_name": part.get("tool_name"),
                })
    return artifacts


def _build_office_link_card(link: dict[str, Any]) -> dict[str, Any]:
    """构建可点击的飞书链接卡片（复用 reply card 的 header 样式）。"""
    url = link.get("url") or ""
    message = link.get("message") or "办公产物已生成"
    content = (
        f"✅ **{message}**\n\n"
        f"<a href='{url}'>打开飞书文档 / 文件</a>"
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{_CARD_TITLE} — 办公产物"},
            "template": "green",
        },
        "elements": [
            {"tag": "markdown", "content": content},
        ],
    }


async def _send_office_link_card(chat_id: str, link: dict[str, Any]) -> bool:
    """发送 office link 产物卡片，返回是否发送成功。"""
    msg_id = await _send_card_to_chat(chat_id, _build_office_link_card(link))
    return msg_id is not None


async def _deliver_office_artifacts(
    messages: list[dict[str, Any]],
    chat_id: str,
) -> tuple[bool, bool]:
    """把 office 写工具产物交付到当前 chat。

    Returns:
        (link_sent, file_sent)
    """
    link_sent = False
    file_sent = False
    for artifact in extract_office_artifacts(messages):
        if artifact["kind"] == "link":
            sent = await _send_office_link_card(chat_id, artifact)
            link_sent = link_sent or sent
        elif artifact["kind"] == "file":
            logger.info(
                "准备发送 office 文件: name=%s size=%d chat_id=%s",
                artifact["file_name"], len(artifact["bytes"]), chat_id,
            )
            sent = await _send_file_to_chat(
                chat_id, artifact["bytes"], artifact["file_name"],
            )
            file_sent = file_sent or sent
            if sent:
                logger.info("office 文件发送成功: %s", artifact["file_name"])
            else:
                logger.warning("office 文件发送失败: %s", artifact["file_name"])
    return link_sent, file_sent


async def _execute_pending_action_background(
    *,
    action_id: str,
    approved: bool,
    chat_id: str,
    operator_id: str | None,
    card_msg_id: str | None,
    summary: str,
) -> None:
    """后台执行 pending action：resume → DB 更新 → PATCH 卡片为最终状态。"""
    effective_chat_id = chat_id or None
    try:
        async with async_session_factory() as db:
            pa = await get_pending_action(db, action_id)
            if pa is None or pa.status != "pending":
                return

            # 卡片回调事件可能不携带 chat_id（open_chat_id/message.chat_id 均空）→
            # 用与 pending action 关联的会话记录恢复真实 chat_id，避免 generate 等
            # 发文件工具回传时误判为 Web 渠道降级（chat_id=None）。
            if not effective_chat_id:
                from app.modules.safety.business_agent.models import AgentSession

                _sess = await db.get(AgentSession, pa.session_id)
                if _sess is not None and _sess.chat_id:
                    effective_chat_id = _sess.chat_id

            session = await get_or_create_session(
                db, channel="feishu", chat_id=effective_chat_id,
            )

            # 重建 deps
            deps = SafetyDeps(
                db=db, person=None, role=None,
                session_id=str(session.id), channel="feishu",
                chat_id=effective_chat_id,
            )
            if operator_id:
                resolver = IdentityResolver(db)
                person = await resolver.resolve_by_user_id(operator_id)
                if person:
                    role = await get_user_role(db, operator_id)
                    deps = SafetyDeps(
                        db=db, person=person, role=role,
                        session_id=str(session.id), channel="feishu",
                        chat_id=effective_chat_id,
                    )

            # 恢复执行
            snapshot = (
                pa.message_history_snapshot
                if isinstance(pa.message_history_snapshot, list)
                else []
            )
            result = await resume(
                str(session.id), deps,
                action_id=action_id, approved=approved,
                message_history_raw=snapshot,
            )

            # 持久化
            await resolve_pending_action(
                db, pa, approved=approved, approved_by=operator_id,
                result_data=result.get("messages") if result["executed"] else None,
            )
            await update_session_history(db, session, messages=result["messages"])
            await save_message(
                db, session_id=session.id,
                user_message=f"[卡片操作: {'确认' if approved else '取消'} {action_id}]",
                agent_answer=result["answer"],
            )
            await db.commit()

        # ── PATCH 卡片为最终状态 ──
        if card_msg_id:
            if result.get("executed"):
                await _update_feishu_card(
                    card_msg_id,
                    _build_completed_card(summary, result["answer"]),
                )

        # ── 从消息中提取文件/链接产物并交付 ──
        if chat_id and result.get("executed"):
            office_link_sent, office_file_sent = await _deliver_office_artifacts(
                result["messages"], effective_chat_id,
            )

            # ── 文本消息作为降级通知（仅在无文件/链接交付时）──
            answer_text = result["answer"].strip()
            if not office_link_sent and not office_file_sent and answer_text:
                await _send_text_to_chat(
                    effective_chat_id, f"✅ 操作已执行。\n\n{answer_text[:500]}",
                )

    except Exception:
        logger.exception("后台执行 pending action 失败: action_id=%s", action_id)
        # 尝试 PATCH 卡片为失败状态
        if card_msg_id:
            try:
                await _update_feishu_card(
                    card_msg_id,
                    _build_completed_card(summary, "❌ 执行失败，请重试或联系管理员。"),
                )
            except Exception:
                pass
        if effective_chat_id:
            await _send_text_to_chat(effective_chat_id, "❌ 操作执行失败，请重试或联系管理员。")
