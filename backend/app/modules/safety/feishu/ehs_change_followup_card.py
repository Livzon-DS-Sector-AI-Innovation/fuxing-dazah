"""EHS 变更周度督办周五卡回调 —— 逐项提交进展/勾选「进展不变」。

路由（business_agent_bot_handler.handle_card_action）：
- form 提交按钮 name ``ecf_submit_<dispatch_id>``（form 回调 action.value 不一定
  返回，name 必然在——progress_card 同款约定）
- 旧版全局「进展不变」按钮（scope=ehs_change_followup，2026-11-24 改版前
  发出的卡）：兼容受理，落 dispatch.response_type（周一仍按旧口径参与判定）

交互（2026-11-24 改版）：表单 = 逐项「input（ecf_prog_<record_id>）+
checkbox（ecf_unchk_<record_id>）」+ 一个提交按钮，一次提交多项。

2.9s ACK 契约（daily_report 同款全链后台化）：一次提交可能含多项回写
（N×2 次飞书 API），回调内只做纯校验，写表+写库+改卡全部放后台 task；
ACK 返回「处理中」toast。写库幂等可重复提交（以最后一次为准）；
填了进展的项优先于勾选（同项两者都给时以文字为准）。

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
    """定向回写「变更最新具体进展」（追加署名行，不覆盖；写前抑制回声）。

    演练模式（`SAFETY_EHS_CHANGE_FOLLOWUP_WRITEBACK_DRY_RUN`，默认关）：
    跳过真实写表、按成功返回，只走「回调→写库→改卡」链路——供实机点击
    演练用（验交互不污染生产表）。正式验收/上线须保持关。
    """
    if not record_id or not text:
        return False
    from app.modules.safety.service.ehs_change_followup import config as _ecf_config

    if _ecf_config.writeback_dry_run():
        logger.info(
            "[演练] 跳过「%s」真实回写 record_id=%s text=%r",
            _PROGRESS_FIELD, record_id, text[:60],
        )
        return True
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
    """提交反馈（逐项：填进展/勾进展不变，一次多项）。

    回调内只做纯校验（2.9s 契约）：表单解析 + 收卡人身份；写表+写库+改卡
    全链放后台 task，ACK 返回「处理中」。
    """
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

    form_value = event_data.get("action", {}).get("form_value") or {}
    signals = _parse_form(dispatch.id, form_value, db_items=None)
    if not (signals["texts"] or signals["checks"]):
        return cards.toast(
            "请至少填写一项新进展，或勾选一项「进展不变」", "error",
        )

    operator = _operator_id(event_data)
    _log_task(
        _apply_submission(dispatch_id, form_value, operator or None),
        tag="submit",
    )
    return cards.toast("提交处理中，本卡片即将更新反馈状态…")


def _truthy_check(value: Any) -> bool:
    """checker 回传值判真（实测可能为 true / "true" / ["1"] / 1 / "checked"）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "checked", "yes", "on")
    if isinstance(value, (list, tuple)):
        return any(_truthy_check(v) for v in value)
    if isinstance(value, dict):
        for key in ("checked", "value", "selected"):
            if key in value:
                return _truthy_check(value[key])
    return bool(value)


def _parse_form(
    dispatch_id: Any, form_value: dict[str, Any], *, db_items: list | None,
) -> dict[str, Any]:
    """form_value → ({record_id: 文本}, {record_id: 勾选})。

    db_items 传入时按卡内实际项过滤（防旧卡残留 name 提交范围外变更）。
    """
    texts: dict[str, str] = {}
    checks: dict[str, bool] = {}
    in_scope = (
        {i.record_id for i in db_items} if db_items is not None else None
    )
    for key, value in (form_value or {}).items():
        if not isinstance(key, str):
            continue
        if key.startswith(cards.PROG_INPUT_PREFIX):
            rid = key[len(cards.PROG_INPUT_PREFIX):]
            text = str(value or "").strip()
            if text and (in_scope is None or rid in in_scope):
                texts[rid] = text
        elif key.startswith(cards.UNCHK_INPUT_PREFIX):
            rid = key[len(cards.UNCHK_INPUT_PREFIX):]
            if _truthy_check(value) and (in_scope is None or rid in in_scope):
                checks[rid] = True
    return {"texts": texts, "checks": checks}


async def _apply_submission(
    dispatch_id: str, form_value: dict[str, Any], operator_id: str | None,
    *, session: Any = None,
) -> None:
    """后台任务体：逐项写表（填了进展的）→ 写库（回复/标记）→ PATCH 原卡。

    单项写表失败该项不记已反馈（DESIGN §9），其余项不受影响；重复提交以
    最后一次为准（同一项又填文字时覆盖并清除勾选标记）。session 测试注入。
    """
    from app.core.database import async_session_factory

    own = session is None
    if own:
        db = async_session_factory()
    else:
        db = session
    try:
        dispatch = await db.scalar(
            select(EhsChangeFollowupDispatch).where(
                EhsChangeFollowupDispatch.id == dispatch_id,
                EhsChangeFollowupDispatch.is_deleted.is_(False),
            )
        )
        if dispatch is None:
            logger.warning("ehs_change_followup 提交落库时卡已失效: %s", dispatch_id)
            return
        items = list((await db.scalars(
            select(EhsChangeFollowupItem).where(
                EhsChangeFollowupItem.dispatch_id == dispatch.id
            )
        )).all())
        signals = _parse_form(dispatch.id, form_value, db_items=items)
        texts, checks = signals["texts"], signals["checks"]
        now = datetime.now(_TZ_SHANGHAI)
        applied = 0
        for item in items:
            text = texts.get(item.record_id)
            if text:
                ok = await push_progress_to_change_table(
                    item.record_id, text, operator_id=operator_id,
                )
                if not ok:
                    logger.warning(
                        "ehs_change_followup 单项回写失败不记已反馈: %s",
                        item.change_no,
                    )
                    continue
                item.replied_progress = text
                item.replied_at = now
                item.replied_by = operator_id
                item.marked_unchanged = False   # 文字优先，清掉旧标记
                applied += 1
            elif checks.get(item.record_id):
                item.marked_unchanged = True
                item.marked_at = now
                applied += 1
        await db.commit()
        if applied:
            await refresh_dispatch_card(dispatch_id)
        logger.info(
            "ehs_change_followup 提交反馈完成: dispatch=%s 文字 %d 项 / "
            "标记 %d 项 operator=%s",
            dispatch_id, len(texts), len(checks), operator_id or "-",
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ehs_change_followup 提交反馈后台处理失败: dispatch=%s", dispatch_id,
        )
    finally:
        if own:
            await db.close()


async def _handle_unchanged(
    db: Any, dispatch_id: str, event_data: dict[str, Any],
) -> dict[str, Any]:
    """旧版全局「进展不变」按钮（2026-11-24 改版前发出的卡）。

    兼容受理：落 dispatch.response_type（周一按旧口径=名下未提交项算②类）；
    新卡已无此按钮，单项勾选走 _apply_submission 的 marked_unchanged。
    """
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
        "ehs_change_followup 已反馈进展不变(旧版全局按钮): dispatch=%s operator=%s",
        dispatch_id, _operator_id(event_data) or "-",
    )
    return cards.toast("已记录：其余变更进展不变，无需更新")
