"""仓储 Agent 确认门（HITL）— 请求确认 → 存草稿 → 点确认校验 → 执行回调。

S1 范围：机制本身（drafts 表状态机 + 发起人/TTL 校验 + 回调注册表 + 审计），
不实现具体业务动作。票07 办公工具（send_card 卡片确认门）复用本服务注册回调。

卡片回调路由：card.action.trigger 按 value.scene 分发（spec Further Notes：
S2 识别草稿确认复用同一注册表），S1 仅处理 scene="confirm_action"。

drafts 状态机（warehouse_agent_drafts.status）：
    pending_confirm ──confirm──▶ confirmed
    pending_confirm ──cancel───▶ cancelled
    pending_confirm ──TTL 过期─▶ expired
回调执行失败保持 pending_confirm（用户可重试），audit 记 error。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.models import WarehouseAgentDraft

logger = logging.getLogger(__name__)

# S1 确认门场景标识（drafts.scene 与卡片按钮 value.scene 同值）
CONFIRM_SCENE = "confirm_action"
# 确认有效期（秒）：spec Implementation Decisions 6 — pending 状态 10 分钟 TTL
DEFAULT_TTL_SECONDS = 600

# 回调签名：在同一 db 事务内执行业务动作，返回用户可见提示（None 用默认文案）
ConfirmCallback = Callable[[AsyncSession, WarehouseAgentDraft], Awaitable[str | None]]

# scene → 回调注册表（模块级；register_confirm_callback 注册，重复注册视为配置错误）
_confirm_callbacks: dict[str, ConfirmCallback] = {}


def register_confirm_callback(scene: str, callback: ConfirmCallback) -> None:
    """注册某 scene 的确认执行回调（票07/S2 复用入口）。"""
    if scene in _confirm_callbacks:
        raise ValueError(f"Confirm callback for scene '{scene}' is already registered")
    _confirm_callbacks[scene] = callback


def unregister_confirm_callback(scene: str) -> None:
    """移除回调（测试清理用；生产不调用）。"""
    _confirm_callbacks.pop(scene, None)


def is_registered_scene(scene: str) -> bool:
    """scene 是否已注册执行回调（gateway 卡片回调路由分发依据）。"""
    return scene in _confirm_callbacks


@dataclass
@dataclass
class ConfirmOutcome:
    """一次确认操作的结构化结果（gateway 渲染卡片更新用）。"""

    ok: bool
    status: str  # confirmed/cancelled/denied/expired/invalid/error
    message: str  # 用户可见提示
    draft: Any | None = None  # execute=False 时携带草稿（gateway 后台执行 submit 用）


def _generate_draft_no() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"CF-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def request_confirm(
    db: AsyncSession,
    *,
    requester_open_id: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    scene: str = CONFIRM_SCENE,
    expires_in_seconds: int | None = None,
) -> WarehouseAgentDraft:
    """发起一次确认：写 pending_confirm 草稿（含摘要、业务载荷、TTL）。

    TTL 缺省读运行参数配置 confirm_ttl_seconds（DB → env → 默认 600），
    管理员改值即时生效；显式传入 expires_in_seconds 时以调用方为准。
    调用方随后用 build_confirm_card(draft) 渲染卡片发给用户；
    payload 为点确认后透传给回调的业务数据（票07：收件人/内容等）。
    """
    if expires_in_seconds is None:
        from app.modules.warehouse.ops_config.runtime_store import runtime_store

        expires_in_seconds = int(runtime_store.get_value("confirm_ttl_seconds"))
    return await agent_repository.create_agent_draft(
        db,
        draft_no=_generate_draft_no(),
        scene=scene,
        status="pending_confirm",
        created_by_open_id=requester_open_id,
        aligned={"summary": summary, "payload": payload or {}},
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
    )


def build_confirm_card(draft: WarehouseAgentDraft) -> dict[str, Any]:
    """确认卡片（预览摘要 + 确认/取消按钮，value 携带 scene/draft_id 供回调路由）。

    卡片为 JSON 2.0 结构（与 cards.build_card 同构；不直接导入 cards——
    cards→runner→query→office→confirm 存在模块环，保持本模块零依赖 cards）。
    按钮直接放 body.elements（2.0 无 action 容器）；回调数据 value 与
    behaviors[type=callback].value 双写同值（2.0 字段表首选 behaviors，
    旧式 value 官方 Demo 仍在用，回调取哪个都一致）。
    """
    aligned = draft.aligned or {}
    summary = str(aligned.get("summary") or "（无摘要）")
    value_base = {"scene": draft.scene, "draft_id": str(draft.id)}
    buttons: list[dict[str, Any]] = []
    for label, action, btype in (
        ("✅ 确认", "confirm", "primary"),
        ("✖ 取消", "cancel", "default"),
    ):
        buttons.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": btype,
                "value": {**value_base, "action": action},
                "behaviors": [
                    {"type": "callback", "value": {**value_base, "action": action}}
                ],
            }
        )
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": "🔔 待确认操作"},
            "template": "orange",
        },
        "body": {"elements": [{"tag": "markdown", "content": summary}, *buttons]},
    }


async def handle_action(
    db: AsyncSession,
    *,
    value: dict[str, Any],
    operator_open_id: str,
    execute: bool = True,
) -> ConfirmOutcome:
    """处理卡片按钮点击（value 来自 card.action.trigger 的 action.value）。

    校验链：草稿存在且 pending → 仅发起人可操作 → TTL 未过期 → 执行回调。
    每次处理写 warehouse_agent_audit（tool_name="confirm"）。
    本函数不 commit（由调用方的 session 上下文统一提交/回滚）。
    """
    started = time.monotonic()
    action = str(value.get("action", ""))
    scene = str(value.get("scene", ""))
    draft_id_raw = str(value.get("draft_id", ""))

    async def _audit(
        draft_id: uuid.UUID | None, status: str, error_code: str | None = None
    ) -> None:
        await agent_repository.insert_agent_audit(
            db,
            tool_name="confirm",
            args_summary={
                "action": action,
                "scene": scene,
                "operator": operator_open_id[:30],
            },
            result_status=status,
            error_code=error_code,
            duration_ms=_elapsed_ms(started),
            draft_id=draft_id,
        )

    try:
        draft_id = uuid.UUID(draft_id_raw)
    except ValueError:
        await _audit(None, "denied", "bad_draft_id")
        return ConfirmOutcome(ok=False, status="invalid", message="确认请求无效")

    draft = await agent_repository.get_agent_draft(db, draft_id)
    if draft is None or draft.status != "pending_confirm":
        await _audit(draft_id, "denied", "not_pending")
        return ConfirmOutcome(ok=False, status="invalid", message="该确认不存在或已被处理")

    if draft.created_by_open_id != operator_open_id:
        logger.warning(
            "仓库确认门非发起人点击: draft_no=%s operator=%s",
            draft.draft_no, operator_open_id[:20],
        )
        await _audit(draft_id, "denied", "not_requester")
        return ConfirmOutcome(ok=False, status="denied", message="仅发起人可以操作该确认")

    expires_at = draft.expires_at
    if expires_at is not None and expires_at < datetime.now(UTC):
        await agent_repository.set_agent_draft_status(db, draft, "expired")
        await _audit(draft_id, "denied", "expired")
        return ConfirmOutcome(ok=False, status="expired", message="该确认已过期，请重新发起")

    if action == "cancel":
        await agent_repository.set_agent_draft_status(db, draft, "cancelled")
        await _audit(draft_id, "ok")
        return ConfirmOutcome(ok=True, status="cancelled", message="已取消")

    if action != "confirm":
        await _audit(draft_id, "denied", "unknown_action")
        return ConfirmOutcome(ok=False, status="invalid", message="未知操作")

    if not execute:
        # submit 类场景（receipt/gmp_outbound/finished_outbound）：确认门只
        # 置状态，回调由 gateway 后台执行（执行耗时可能超过 ACK 窗口），
        # 回执按发起渠道（draft.chat_id）发送
        await agent_repository.set_agent_draft_status(db, draft, "confirmed")
        await _audit(draft_id, "ok")
        return ConfirmOutcome(ok=True, status="confirmed", message="已确认，正在登记…", draft=draft)

    callback = _confirm_callbacks.get(draft.scene)
    if callback is None:
        logger.error("仓库确认门未注册回调: scene=%s", draft.scene)
        await _audit(draft_id, "error", "no_callback")
        return ConfirmOutcome(ok=False, status="error", message="该场景未注册确认回调")

    # 先置终态再执行回调：回调慢/被取消时重复点击会被 pending 校验拒绝（防重复发送）
    await agent_repository.set_agent_draft_status(db, draft, "confirmed")
    await db.flush()

    try:
        note = await callback(db, draft)
    except Exception:
        logger.exception("仓库确认门回调执行失败: draft_no=%s", draft.draft_no)
        # 显式置 failed 而非回滚到 pending——pending 会让用户再次触发执行
        await agent_repository.set_agent_draft_status(db, draft, "failed")
        await _audit(draft_id, "error", "callback_error")
        return ConfirmOutcome(ok=False, status="error", message="执行失败（草稿已作废），请重新拍照发起识别")

    await _audit(draft_id, "ok")
    return ConfirmOutcome(ok=True, status="confirmed", message=note or "已确认执行")
