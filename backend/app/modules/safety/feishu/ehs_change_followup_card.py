"""EHS 变更周度督办周五卡回调 —— 提交进展 / 点「进展不变」。

路由（business_agent_bot_handler.handle_card_action）：
- form 提交按钮 name ``ecf_submit_<dispatch_id>``（form 回调 action.value 不一定
  返回，name 必然在——progress_card 同款约定）
- 「进展不变」按钮 value JSON ``{"scope": "ehs_change_followup", ...}``

2.9s ACK 契约（daily_report_card / progress_card 同款）：回调内只做写表
（Bitable 追加）+ 单行写库，改卡（PATCH 原卡）放后台 task。写库幂等，
可重复点（重复提交进展以最后一次为准，表侧追加是提交历史语义）。

回写（DESIGN §4）：变更表「变更最新具体进展」末尾追加
``【卡片提交·YYYY-MM-DD HH:mm·姓名】原文``（progress_card.append_progress_value
/ build_submission_line 复用），写前 _set_sync_ignore 抑制 changed_v1 回声
（ehs_change_bitable_handler 消费同一 ignore 键）。

只有收卡人本人能操作（operator 姓名 == dispatch.officer_name）；灰度收件人
非空时跳过该校验（验收链路：卡发给了灰度收件人而非安全员本人）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.modules.safety.models.ehs_change_followup import (
    RESPONSE_UNCHANGED,
    EhsChangeFollowupDispatch,
    EhsChangeFollowupItem,
)
from app.modules.safety.service.ehs_change_followup import cards

logger = logging.getLogger(__name__)

_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

_PROGRESS_FIELD = "变更最新具体进展"


def _operator_id(event_data: dict[str, Any]) -> str:
    operator = event_data.get("operator", {}) or {}
    return operator.get("open_id") or operator.get("user_id") or ""


def _log_task(coro: Any, *, tag: str) -> None:  # pragma: no cover - 薄封装
    async def _runner() -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001 — 后台任务失败留日志不外抛
            logger.exception("ehs_change_followup 后台任务失败: tag=%s", tag)

    try:
        asyncio.get_running_loop()
        asyncio.create_task(_runner())
    except RuntimeError:  # 无事件循环（测试环境）——直接丢弃
        coro.close()


def _approval_client():
    """绑定 ehs_change/approval 表的客户端（未登记抛错，回调侧如实失败）。"""
    from app.modules.safety.bitable_config.store import store
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    conn = store.get_connection("ehs_change", "approval")
    if conn is None or not conn.app_token or not conn.table_id:
        raise RuntimeError("ehs_change/approval 连接未登记，无法回写变更表")
    return SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)


async def push_progress_to_change_table(
    record_id: str, text: str, *, operator_id: str | None = None,
) -> bool:
    """定向回写「变更最新具体进展」（追加署名行，不覆盖；写前抑制回声）。"""
    if not record_id or not text:
        return False
    from app.modules.safety.feishu.bitable_handler import _set_sync_ignore
    from app.modules.safety.feishu.progress_card import (
        append_progress_value,
        build_submission_line,
        resolve_operator_name,
    )
    from app.modules.safety.service.ehs_change_followup.records import flat_text

    try:
        client = _approval_client()
        fields = await client.get_record(record_id)
        existing = flat_text((fields or {}).get(_PROGRESS_FIELD))
        line = build_submission_line(text, resolve_operator_name(operator_id))
        await _set_sync_ignore(record_id, ttl=30)
        ok = await client.update_record(
            record_id, {_PROGRESS_FIELD: append_progress_value(existing, line)},
        )
        if ok:
            logger.info(
                "ehs_change_followup 回写「%s」成功(追加署名): record_id=%s",
                _PROGRESS_FIELD, record_id,
            )
        else:
            logger.warning(
                "ehs_change_followup 回写「%s」失败: record_id=%s",
                _PROGRESS_FIELD, record_id,
            )
        return ok
    except Exception:
        logger.exception(
            "ehs_change_followup 回写「%s」异常: record_id=%s", _PROGRESS_FIELD, record_id,
        )
        return False


async def refresh_dispatch_card(
    dispatch_id: str, *, session: Any = None,
) -> bool:
    """按库内最新状态重建周五卡并 PATCH 原卡（后台任务体，测试直调）。"""
    from app.core.database import async_session_factory

    from app.modules.safety.service.ehs_change_followup.service import (
        _change_table_url,  # noqa: SLF001 — 同域复用，避免链接口径漂移
        _card_item_views,
    )

    own = session is None
    db = session if session is not None else async_session_factory()
    try:
        dispatch = await db.scalar(
            select(EhsChangeFollowupDispatch).where(
                EhsChangeFollowupDispatch.id == dispatch_id,
                EhsChangeFollowupDispatch.is_deleted.is_(False),
            )
        )
        if dispatch is None or not dispatch.message_id:
            return False
        from app.modules.safety.models.ehs_change_followup import (
            EhsChangeFollowupRound,
        )

        round_row = await db.get(EhsChangeFollowupRound, dispatch.round_id)
        if round_row is None:
            return False
        items = list((await db.scalars(
            select(EhsChangeFollowupItem).where(
                EhsChangeFollowupItem.dispatch_id == dispatch.id
            )
        )).all())
        view = cards.FridayCardView(
            officer_name=dispatch.officer_name,
            departments=dispatch.departments.replace(",", "/"),
            week_no=round_row.week_no,
            date_label=round_row.fired_on.strftime("%m-%d 周五"),
            items=_card_item_views(items),
            has_replies=any(i.replied_at for i in items),
            responded_unchanged_at=(
                dispatch.responded_at.strftime("%H:%M")
                if dispatch.responded_at else ""
            ),
            change_table_url=_change_table_url(),
        )
        from app.modules.safety.feishu.notification import update_card

        return await update_card(
            dispatch.message_id, cards.build_friday_card(view, str(dispatch.id)),
        )
    finally:
        if own:
            await db.close()


def _operator_allowed(dispatch: EhsChangeFollowupDispatch, event_data: dict) -> bool:
    """只有收卡人本人可操作；灰度收件人非空时跳过校验（验收链路）。"""
    from app.modules.safety.service.ehs_change_followup import config
    from app.modules.safety.feishu.progress_card import resolve_operator_name

    if config.gray_recipient().strip():
        return True
    name = resolve_operator_name(_operator_id(event_data))
    return bool(name) and name == dispatch.officer_name


async def handle_ehs_change_followup_action(
    payload: dict[str, Any], event_data: dict[str, Any], *,
    session: Any = None,
) -> dict[str, Any] | None:
    """周五卡动作分发（business_agent_bot_handler 路由入口；session 测试注入）。

    Returns:
        飞书 ACK：``{"toast": ...}``；无法识别返回 None。
    """
    if not isinstance(payload, dict):
        payload = {}
    action_name = event_data.get("action", {}).get("name", "") or ""
    action = str(payload.get("action") or "")
    dispatch_id = str(payload.get("dispatch_id") or "")
    if not dispatch_id and action_name.startswith(cards.SUBMIT_NAME_PREFIX):
        dispatch_id = action_name[len(cards.SUBMIT_NAME_PREFIX):]
    if not dispatch_id and action_name.startswith(cards.UNCHANGED_NAME_PREFIX):
        dispatch_id = action_name[len(cards.UNCHANGED_NAME_PREFIX):]
    if not dispatch_id:
        logger.warning(
            "ehs_change_followup 回调缺 dispatch_id: action=%s name=%s",
            action, action_name,
        )
        return None

    from app.core.database import async_session_factory

    own = session is None
    db = session if session is not None else async_session_factory()
    try:
        if action == "submit" or action_name.startswith(cards.SUBMIT_NAME_PREFIX):
            return await _handle_submit(db, dispatch_id, event_data)
        if action == "unchanged" or action_name.startswith(cards.UNCHANGED_NAME_PREFIX):
            return await _handle_unchanged(db, dispatch_id, event_data)
        logger.warning("ehs_change_followup 回调未知动作: action=%s", action)
        return None
    finally:
        if own:
            await db.close()


async def _handle_submit(
    db: Any, dispatch_id: str, event_data: dict[str, Any],
) -> dict[str, Any]:
    """提交进展：写表（追加署名行）→ 单行写库 → 后台 PATCH 原卡。"""
    form_value = event_data.get("action", {}).get("form_value") or {}
    record_id = str(form_value.get("change") or "").strip()
    text = str(form_value.get("progress") or "").strip()
    if not record_id or not text:
        return cards.toast("请选择变更并填写进展后再提交", "error")

    dispatch = await db.scalar(
        select(EhsChangeFollowupDispatch).where(
            EhsChangeFollowupDispatch.id == dispatch_id,
            EhsChangeFollowupDispatch.is_deleted.is_(False),
        )
    )
    if dispatch is None:
        return cards.toast("督办卡不存在或已失效", "error")
    if not _operator_allowed(dispatch, event_data):
        logger.warning(
            "ehs_change_followup 非收卡人操作被拒: dispatch=%s operator=%s",
            dispatch_id, _operator_id(event_data),
        )
        return cards.toast("仅收卡人本人可操作", "error")
    item = await db.scalar(
        select(EhsChangeFollowupItem).where(
            EhsChangeFollowupItem.dispatch_id == dispatch.id,
            EhsChangeFollowupItem.record_id == record_id,
            EhsChangeFollowupItem.is_deleted.is_(False),
        )
    )
    if item is None:
        return cards.toast("该变更不在本卡督办范围内", "error")

    operator = _operator_id(event_data)
    ok = await push_progress_to_change_table(
        record_id, text, operator_id=operator or None,
    )
    if not ok:
        # 写表失败不记为已反馈（DESIGN §9）
        return cards.toast("提交失败，请稍后重试", "error")

    item.replied_progress = text
    item.replied_at = datetime.now(_TZ_SHANGHAI)
    item.replied_by = operator or None
    await db.commit()

    _log_task(refresh_dispatch_card(dispatch_id), tag="submit")
    logger.info(
        "ehs_change_followup 提交进展: dispatch=%s change=%s operator=%s",
        dispatch_id, item.change_no, operator or "-",
    )
    return cards.toast("进展已提交，感谢更新！")


async def _handle_unchanged(
    db: Any, dispatch_id: str, event_data: dict[str, Any],
) -> dict[str, Any]:
    """点「进展不变，无需更新」：单行写库（幂等）→ 后台 PATCH 原卡。"""
    dispatch = await db.scalar(
        select(EhsChangeFollowupDispatch).where(
            EhsChangeFollowupDispatch.id == dispatch_id,
            EhsChangeFollowupDispatch.is_deleted.is_(False),
        )
    )
    if dispatch is None:
        return cards.toast("督办卡不存在或已失效", "error")
    if not _operator_allowed(dispatch, event_data):
        logger.warning(
            "ehs_change_followup 非收卡人操作被拒: dispatch=%s operator=%s",
            dispatch_id, _operator_id(event_data),
        )
        return cards.toast("仅收卡人本人可操作", "error")

    if dispatch.response_type == RESPONSE_UNCHANGED:
        return cards.toast("已反馈：其余变更进展不变，无需更新")

    dispatch.response_type = RESPONSE_UNCHANGED
    dispatch.responded_at = datetime.now(_TZ_SHANGHAI)
    await db.commit()

    _log_task(refresh_dispatch_card(dispatch_id), tag="unchanged")
    logger.info(
        "ehs_change_followup 已反馈进展不变: dispatch=%s operator=%s",
        dispatch_id, _operator_id(event_data) or "-",
    )
    return cards.toast("已记录：其余变更进展不变，无需更新")
