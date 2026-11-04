"""督办催办卡片：一卡一隐患，卡片内提交整改进展。

流程：
  发送侧 → HazardSupervisionService.send_progress_dunning(chat_id)
           （查「未更新进展」隐患 → 解析责任人 open_id → build_progress_card → send_group_card）
  回调侧 → business_agent_bot_handler.handle_card_action 按 scope=="progress_update" 路由到本模块
           handle_progress_submit(payload, event_data)
           → 平台更新（update_progress_from_card）+ Bitable 定向回写 + ACK「已提交」卡片

Bitable 回写为**定向**单字段写回（"目前进展"），不动 ONE_WAY_FIELDS：
写回前 _set_sync_ignore(record_id, ttl=30) 抑制 changed_v1 回声，机制与
push_hazard_to_bitable 一致。平台更新为主源，回写失败仅告警不阻塞。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.database import async_session_factory
from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.bitable_handler import (
    _extract_rich_text,
    _set_sync_ignore,
)
from app.modules.safety.feishu.notification import update_card
from app.modules.safety.service.hazard import HazardService
from app.modules.safety.service.responsible_mapping import effective_responsible_person

logger = logging.getLogger(__name__)

# 卡片回调 scope 标识（与 handle_card_action 路由约定一致）
SCOPE_PROGRESS_UPDATE = "progress_update"


def _record_link(hazard: Any) -> str:
    """主表多维表格记录链接（催办卡仅覆盖主表隐患，外审记录已被进度机制排除）。

    凭证延迟读 store（hazard/hazard 连接），改表 ID 后链接立即指向新表。
    """
    rid = getattr(hazard, "feishu_record_id", "") or ""
    if not rid:
        return ""
    conn = store.get_connection("hazard", "hazard")
    if conn is None or conn.status == "disabled":
        return ""
    if not (conn.app_token and conn.table_id):
        return ""
    return f"[📋查看记录](https://j0eukrlohu.feishu.cn/base/{conn.app_token}?table={conn.table_id}&record={rid})"


def build_progress_card(hazard: Any, open_id: str | None) -> tuple[str, list[dict]]:
    """构建一卡一隐患的催办卡片，返回 (markdown 正文, 附加元素列表)。

    send_group_card 会构建信封（header + 正文 markdown），我们只需给正文与
    form 容器元素。input 必须内嵌在 form 容器内、配合 form_action_type=submit
    的按钮，值才会在 card.action.trigger 回调的 event.action.form_value 返回。

    路由约定：form 回调中 action.value 不一定随回调返回，但 action.name 必然存在。
    因此按钮 name 携带 hazard_id（progress_submit_<hazard_id>），handle_card_action
    据此路由并提取 hazard_id。
    """
    name = effective_responsible_person(
        getattr(hazard, "department", None),
        getattr(hazard, "rectification_responsible_person_name", "") or "",
    ) or "-"
    # @ 提及需「安全应用作用域」open_id（平台同步的 open_id 跨应用无效）
    from app.modules.safety.feishu import mention

    at_mention = mention.at_tag(name, open_id) or name
    hazard_id = str(getattr(hazard, "id", ""))
    # 直读多维表格模式：id 即 Bitable record_id（rec 前缀）
    # → 按钮 name 走 progress_submit_rec_ 前缀，回调直接写 Bitable（不经平台库）
    is_direct = hazard_id.startswith("rec")
    route_key = f"rec_{hazard_id}" if is_direct else hazard_id
    hazard_no = getattr(hazard, "hazard_no", "") or ""
    desc = (getattr(hazard, "description", "") or "").strip()[:200]
    if not desc:
        desc = "（无描述）"

    dept = getattr(hazard, "department", "") or "-"
    discovered = getattr(hazard, "discovered_at", None)
    discovered_str = discovered.strftime("%Y-%m-%d") if discovered else "-"

    # 补充隐患基本信息（责任人/整改建议）
    person = getattr(hazard, "rectification_responsible_person_name", "") or "-"
    reason = (getattr(hazard, "major_hazard_basis", "") or "").strip()

    lines = [
        f"{at_mention} ｜ 隐患 **{hazard_no}**",
        f"{desc}",
        f"责任人：{person}",
        f"责任部门：{dept}",
        f"检查日期：{discovered_str}",
        f"整改建议：{reason}" if reason else "",
    ]
    link = _record_link(hazard)
    if link:
        lines.append(f"查看记录：{link}")
    # 去掉空行
    content = "\n".join([line for line in lines if line])

    form: dict = {
        "tag": "form",
        "name": f"progress_form_{hazard_id}",
        "elements": [
            {
                "tag": "input",
                "name": "progress",
                "required": True,
                "label": {"tag": "plain_text", "content": "最新进展"},
                "placeholder": {"tag": "plain_text", "content": "请填写本次整改进展"},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "提交进展"},
                "type": "primary",
                "form_action_type": "submit",
                # name 携带 hazard_id：form 回调 action.name 必然返回，据此路由
                "name": f"progress_submit_{route_key}",
                # value 需 JSON 编码（Feishu 事件侧再做一次编码，回调双重 decode）
                "value": json.dumps(
                    {
                        "scope": SCOPE_PROGRESS_UPDATE,
                        "hazard_id": hazard_id,
                        "record_id": hazard_id if is_direct else "",
                        "action": "submit",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    return content, [form]


def build_submitted_card(hazard_no: str, text: str) -> dict:
    """提交成功后的确认卡片（替换原卡，防止重复提交混淆）。"""
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": "✅ 进展已提交"},
            "template": "green",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"隐患 **{hazard_no or '-'}** 的最新进展已提交：\n\n{text}\n\n⏱ 提交时间：{now_str}",
                },
            ],
        },
    }


def _plain_text(value: Any) -> str:
    """Bitable 字段值 → 纯文本（str 直取；富文本 list 拼接；dict 取 text）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            el.get("text", "") if isinstance(el, dict) else str(el) for el in value
        )
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value)


async def _audit_submission(
    *, record_id: str, hazard_no: str, text: str, operator: str,
    event_data: dict, applied: bool,
) -> None:
    """提交动作旁挂留痕（方向 B；开关关=零写，失败不抛——不影响业务链路）。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service.hazard_direct.audit_trail import (
        record_card_submission,
    )

    context = event_data.get("context") or {}
    action = event_data.get("action") or {}
    message_key = f"{context.get('open_message_id') or ''}:{action.get('name') or ''}"
    try:
        async with async_session_factory() as session:
            await record_card_submission(
                session, record_id=record_id, text=text, operator=operator,
                message_key=message_key, applied=applied, hazard_no=hazard_no,
                note="bitable_write" if applied else "bitable_write_failed",
            )
            await session.commit()
    except Exception:
        logger.exception("提交留痕异常（不影响业务）: record_id=%s", record_id)


async def _push_and_audit(
    record_id: str, hazard_no: str, text: str,
    operator: str, event_data: dict,
) -> None:
    """镜像路径后台任务：回写台账 + 留痕（原 push 后台任务的超集）。"""
    ok = await push_progress_note_to_bitable(
        record_id, text, operator_open_id=operator,
    )
    await _audit_submission(
        record_id=record_id, hazard_no=hazard_no, text=text, operator=operator,
        event_data=event_data, applied=ok,
    )


def build_submission_line(
    text: str, sender_name: str, *, at: datetime | None = None,
) -> str:
    """台账追加行：【卡片提交·YYYY-MM-DD HH:mm·姓名】原文（北京时间）。"""
    from zoneinfo import ZoneInfo

    stamp = (at or datetime.now(ZoneInfo("Asia/Shanghai"))).strftime(
        "%Y-%m-%d %H:%M"
    )
    return f"【卡片提交·{stamp}·{sender_name}】{(text or '').strip()}"


def append_progress_value(existing: str, *lines: str) -> str:
    """现值追加（只 append 不改写历史；空行分隔）。"""
    base = (existing or "").rstrip()
    new = "\n\n".join(x for x in lines if x)
    if base and new:
        return f"{base}\n\n{new}"
    return new or base


def resolve_operator_name(identifier: str | None) -> str:
    """提交人标识 → 姓名（user_id 直查 → open_id 反查 → 尾 12 位兜底）。

    card.action 的 operator 可能带 user_id（租户级）或 open_id（安全应用作用域），
    两条链都走静态映射 best-effort。
    """
    from app.modules.safety.feishu import bitable_id_mapper

    ident = (identifier or "").strip()
    if not ident:
        return "未知"
    if ident.startswith("ou_"):
        name = bitable_id_mapper.get_name_by_bitable_open_id(ident)
    else:
        name = bitable_id_mapper.get_name_by_user_id(ident)
    return name or ident[-12:]


async def push_progress_note_to_bitable(
    record_id: str, text: str, *, operator_open_id: str | None = None,
) -> bool:
    """定向回写「目前进展」到 Bitable（best-effort，失败仅告警不阻塞）。

    留痕语义（2026-11-04 拍板）：**追加**带署名行【卡片提交·时间·姓名】原文，
    不再覆盖——「目前进展」成为有 attribution 的提交历史；③轮询按全文字
    hash 判变化，追加语义天然兼容。写回前打 _set_sync_ignore 抑制回声。
    """
    if not record_id or not text:
        return False
    try:
        line = build_submission_line(text, resolve_operator_name(operator_open_id))
        bitable = SafetyBitableClient()
        fields = await bitable.get_record(record_id)
        existing = _plain_text((fields or {}).get("目前进展")).strip()
        await _set_sync_ignore(record_id, ttl=30)
        ok = await bitable.update_record(
            record_id, {"目前进展": append_progress_value(existing, line)},
        )
        if ok:
            logger.info(
                "Bitable 回写「目前进展」成功(追加署名): record_id=%s", record_id,
            )
        else:
            logger.warning("Bitable 回写「目前进展」失败: record_id=%s", record_id)
        return ok
    except Exception:
        logger.exception("Bitable 回写「目前进展」异常: record_id=%s", record_id)
        return False


async def handle_progress_submit_direct(record_id: str, event_data: dict) -> dict | None:
    """处理「直读多维表格」模式催办卡片的提交回调。

    与 ``handle_progress_submit`` 的区别：不查平台库、不写平台库，
    直接把「目前进展」写回多维表格（唯一数据源）。

    Returns:
        飞书 ACK：{"toast": ..., "card": {"type": "raw", "data": ...}} 或 None。
    """
    if not record_id or not record_id.startswith("rec"):
        logger.warning("直读催办卡片回调: 非法 record_id=%r", record_id)
        return None

    action = event_data.get("action", {}) or {}
    form_value = action.get("form_value") or {}
    text = str(form_value.get("progress", "") or "").strip()
    operator_open_id = (
        event_data.get("operator", {}).get("user_id")
        or event_data.get("operator", {}).get("open_id")
    )
    if not text:
        logger.warning("直读催办卡片回调: 输入为空 record_id=%s", record_id)
        return {"toast": {"type": "error", "content": "请填写最新进展后再提交"}}

    # 读记录拿编号（仅用于确认卡片展示）
    hazard_no = ""
    try:
        bitable = SafetyBitableClient()
        fields = await bitable.get_record(record_id)
        hazard_no = _extract_rich_text(fields.get("隐患编号")).strip()
    except Exception:
        logger.debug("读取隐患编号失败（不影响提交）: record_id=%s", record_id, exc_info=True)

    ok = await push_progress_note_to_bitable(
        record_id, text, operator_open_id=operator_open_id or "",
    )
    await _audit_submission(
        record_id=record_id, hazard_no=hazard_no, text=text,
        operator=operator_open_id or "", event_data=event_data, applied=ok,
    )
    if not ok:
        return {"toast": {"type": "error", "content": "提交失败，请稍后重试"}}

    submitted_card = build_submitted_card(hazard_no, text)
    msg_id = (event_data.get("context") or {}).get("open_message_id")
    if msg_id:
        asyncio.create_task(update_card(msg_id, submitted_card))

    logger.info(
        "直读催办卡片提交成功: record_id=%s operator=%s len=%d",
        record_id, operator_open_id or "-", len(text),
    )
    return {
        "toast": {"type": "success", "content": "进展已提交，感谢更新！"},
        "card": {"type": "raw", "data": json.dumps(submitted_card, ensure_ascii=False)},
    }


async def handle_progress_submit(payload: dict, event_data: dict) -> dict | None:
    """处理催办卡片提交回调（scope == 'progress_update'）。

    卡片替换为「已提交」确认卡采用**双通道**（都 best-effort）：
      A. WS ACK 响应携带卡片更新（快速路径）
      B. 显式 PATCH update_card(context.open_message_id)（可靠机制，照抄 Agent 确认流）
    关键：慢操作（Bitable 回写、PATCH）全部放入后台任务，确保 ACK 在 event_client
    的 2.9s wait_for 超时前返回——否则协程被取消，DB 已提交但卡片更新数据丢失
    （表现为「数据库已更新、卡片不变、无重试」）。

    Returns:
        飞书 ACK：{"toast": ..., "card": {"type": "raw", "data": ...}} 或 None（无法识别）。
    """
    hazard_id = payload.get("hazard_id", "")
    if not hazard_id:
        return None
    try:
        hazard_uuid = uuid.UUID(hazard_id)
    except (ValueError, TypeError, AttributeError):
        logger.warning("催办卡片回调: 非法 hazard_id=%r", hazard_id)
        return None

    action = event_data.get("action", {}) or {}
    form_value = action.get("form_value") or {}
    text = str(form_value.get("progress", "") or "").strip()
    operator_open_id = (
        event_data.get("operator", {}).get("user_id")
        or event_data.get("operator", {}).get("open_id")
    )
    if not text:
        logger.warning("催办卡片回调: 输入为空 hazard_id=%s operator=%s", hazard_id, operator_open_id)
        return {"toast": {"type": "error", "content": "请填写最新进展后再提交"}}

    hazard_no = ""
    record_id = ""
    async with async_session_factory() as db:
        service = HazardService(db)
        hazard = await service.update_progress_from_card(
            hazard_uuid, text, operator_open_id=operator_open_id,
        )
        if hazard is None:
            return {"toast": {"type": "error", "content": "隐患不存在或已删除"}}
        hazard_no = hazard.hazard_no or ""
        record_id = hazard.feishu_record_id or ""
        await db.commit()

    submitted_card = build_submitted_card(hazard_no, text)

    # Bitable 定向回写（best-effort，后台执行避免拖慢卡片 ACK；失败仅告警不阻塞）
    # 直读多维表格模式下平台库独立运行，不再回填 Bitable（新卡片走 handle_progress_submit_direct）
    from app.modules.safety.service.hazard_direct.config import event_sync_enabled

    if record_id and event_sync_enabled():
        asyncio.create_task(_push_and_audit(
            record_id, hazard_no, text, operator_open_id or "", event_data,
        ))
    elif record_id:
        logger.debug("隐患事件同步已关闭，跳过「目前进展」回写: record_id=%s", record_id)

    # 通道 B：显式 PATCH 替换卡片为「已提交」确认卡（可靠机制，与 Agent 确认流一致）
    msg_id = (event_data.get("context") or {}).get("open_message_id")
    if msg_id:
        asyncio.create_task(update_card(msg_id, submitted_card))

    logger.info(
        "催办卡片提交成功: hazard_id=%s operator=%s len=%d msg_id=%s",
        hazard_id, operator_open_id or "-", len(text), msg_id or "-",
    )
    return {
        "toast": {"type": "success", "content": "进展已提交，感谢更新！"},
        "card": {"type": "raw", "data": json.dumps(submitted_card, ensure_ascii=False)},
    }
