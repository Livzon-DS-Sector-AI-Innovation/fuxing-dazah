"""通用业务确认门（V3.0 分期A Ticket 05）— ConfirmRequest 状态机 + Base 回写。

架构定案（1C/2B，spec Implementation Decisions）：
- 二值确认（确认/取消）、单级、无会签；对外口径统一「线上确认」；
- 确认动作 = 按映射回写 Base 字段（Bitable 为权威），取消动作 = 仅记审计不改数；
- 确认人 = 确认卡目标范围内任何人（加速器定位）；回写操作人 = 点击者 open_id。

状态机（confirm_requests.status）：
    pending ──confirm──▶ confirmed ──回写──▶ （保持 confirmed，失败置 failed）
    pending ──cancel───▶ cancelled
    pending ──TTL 过期─▶ expired

与草稿确认链（agent/confirm.py）的关系：机制同构（防重复/TTL/先置终态再执行），
但独立成表独立成服务——登记场景继续走 AgentDraft，业务确认走本模块。

回写执行时机：确认点击在飞书卡片回调 ACK 窗口（2.9s）内只置 confirmed
（execute=False），Base 逐条回写由 gateway 后台任务执行（本模块
``execute_writeback``），失败显式置 failed 并发失败回执——模式对齐
submit 场景（先置终态防重复点击，异常不回滚 pending）。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.cards import build_card
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseConfirmAudit,
    WarehouseConfirmRequest,
)

logger = logging.getLogger(__name__)

# 确认门场景标识（卡片按钮 value.scene，gateway 分发键）
CONFIRM_GATE_SCENE = "biz_confirm"

# 业务确认 TTL（秒）：默认 24 小时（区别于对话草稿的 10 分钟）
DEFAULT_TTL_SECONDS = 86400

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"


@dataclass
class ConfirmGateOutcome:
    """一次确认操作的结构化结果（gateway 渲染卡片更新用）。"""

    ok: bool
    status: str  # confirmed/cancelled/denied/expired/invalid/error
    message: str  # 用户可见提示
    request: WarehouseConfirmRequest | None = None  # execute=False 时携带（后台回写用）


def _generate_request_no() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"CR-{stamp}-{uuid.uuid4().hex[:6].upper()}"


async def _audit(
    db: AsyncSession,
    request: WarehouseConfirmRequest | None,
    *,
    action: str,
    operator_open_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        WarehouseConfirmAudit(
            request_no=request.request_no if request is not None else "-",
            action=action,
            operator_open_id=operator_open_id,
            detail=detail,
        )
    )
    await db.flush()


async def get_request(
    db: AsyncSession, request_id: str | uuid.UUID
) -> WarehouseConfirmRequest | None:
    stmt = select(WarehouseConfirmRequest).where(
        WarehouseConfirmRequest.id == request_id,
        WarehouseConfirmRequest.is_deleted.is_(False),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_request(
    db: AsyncSession,
    *,
    business_type: str,
    title: str,
    summary: str,
    ref_table: str,
    ref_record_ids: list[str],
    target: str,
    payload: dict[str, Any] | None = None,
    writeback: dict[str, Any] | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> WarehouseConfirmRequest:
    """创建确认单（pending）+ 审计；调用方随后 send_request_card 投递。"""
    request = WarehouseConfirmRequest(
        request_no=_generate_request_no(),
        business_type=business_type,
        title=title,
        summary=summary,
        ref_table=ref_table,
        ref_record_ids=list(ref_record_ids),
        payload=payload,
        target=target,
        writeback=writeback,
        status=STATUS_PENDING,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )
    db.add(request)
    await db.flush()
    await _audit(
        db,
        request,
        action="create",
        detail={"ref_table": ref_table, "ref_count": len(ref_record_ids)},
    )
    return request


def build_request_card(request: WarehouseConfirmRequest) -> dict[str, Any]:
    """确认卡（JSON 2.0：摘要 + 确认/取消按钮，value 携带 scene/request_id/action）。

    按钮数据 value 与 behaviors[type=callback].value 双写同值（2.0 字段表
    首选 behaviors，旧式 value 回调取哪个都一致——与草稿确认卡同构）。
    """
    value_base = {"scene": CONFIRM_GATE_SCENE, "request_id": str(request.id)}
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
            "title": {"tag": "plain_text", "content": request.title},
            "template": "orange",
        },
        "body": {"elements": [{"tag": "markdown", "content": request.summary}, *buttons]},
    }


def build_request_status_card(
    request: WarehouseConfirmRequest, *, state: str
) -> dict[str, Any]:
    """原卡 PATCH 用状态卡（无按钮；processing/done/cancelled/failed）。"""
    titles = {
        "processing": ("⏳ 回写中", "blue"),
        "done": ("✅ 已确认", "green"),
        "cancelled": ("✖ 已取消", "grey"),
        "failed": ("⚠️ 回写失败", "red"),
        "expired": ("⏰ 已过期", "grey"),
    }
    title, template = titles.get(state, (request.title, "orange"))
    status_text = {
        "processing": "已确认，正在回写台账…",
        "done": f"已确认（{request.request_no}），台账已更新。",
        "cancelled": f"已取消（{request.request_no}），未做任何数据变更。",
        "failed": f"回写失败（{request.request_no}），请重发确认单或人工处理。",
        "expired": f"该确认已过期（{request.request_no}），请重新发起。",
    }.get(state, "")
    return build_card(
        title=title,
        template=template,
        elements=[{"tag": "markdown", "content": request.summary}, {"tag": "markdown", "content": status_text}],
    )


async def patch_request_card(
    request: WarehouseConfirmRequest, *, state: str, dry_run: bool | None = None
) -> None:
    """PATCH 原确认卡为状态卡（失败吞异常，不阻断主流程）。"""
    if not request.card_message_id:
        return
    try:
        await notification.update_card(
            request.card_message_id,
            build_request_status_card(request, state=state),
            dry_run=dry_run,
        )
    except Exception:  # noqa: BLE001 — 卡片更新失败不阻断状态机
        logger.warning("确认卡状态更新失败: request_no=%s state=%s", request.request_no, state)


async def send_request_card(
    request: WarehouseConfirmRequest, *, dry_run: bool | None = None
) -> bool:
    """发送确认卡到目标（ou_ 私聊/否则群聊，统一分发入口）；成功写回 card_message_id。

    message_id 列的落库由调用方 session 的后续 flush/commit 带出。
    """
    card = build_request_card(request)
    message_id = await notification.send_card_to_target(request.target, card, dry_run=dry_run)
    if message_id is None:
        logger.error("确认卡发送失败: request_no=%s target=%s", request.request_no, request.target[:20])
        return False
    request.card_message_id = message_id
    return True


async def handle_action(
    db: AsyncSession,
    *,
    value: dict[str, Any],
    operator_open_id: str,
    execute: bool = True,
) -> ConfirmGateOutcome:
    """处理确认卡按钮点击（value 来自 card.action.trigger 的 action.value）。

    校验链：单存在且 pending（防重复）→ TTL 未过期否则置 expired → 二值分支。
    confirm + execute=False：只置 confirmed（gateway 后台执行回写）；
    confirm + execute=True：同步执行回写（服务层测试路径）。
    本函数不 commit（由调用方 session 上下文统一提交/回滚）。
    """
    action = str(value.get("action") or "")
    request_id_raw = str(value.get("request_id") or "")

    try:
        request_id = uuid.UUID(request_id_raw)
    except ValueError:
        return ConfirmGateOutcome(ok=False, status="invalid", message="确认请求无效")

    request = await get_request(db, request_id)
    if request is None or request.status != STATUS_PENDING:
        logger.warning(
            "确认门单不存在或已处理: request_id=%s status=%s",
            request_id_raw, request.status if request else "missing",
        )
        return ConfirmGateOutcome(ok=False, status="invalid", message="该确认不存在或已被处理")

    if request.expires_at is not None and request.expires_at < datetime.now(UTC):
        request.status = STATUS_EXPIRED
        await db.flush()
        await _audit(db, request, action="expire", operator_open_id=operator_open_id)
        return ConfirmGateOutcome(ok=False, status="expired", message="该确认已过期，请重新发起")

    if action == "cancel":
        request.status = STATUS_CANCELLED
        await db.flush()
        await _audit(db, request, action="cancel", operator_open_id=operator_open_id)
        return ConfirmGateOutcome(ok=True, status="cancelled", message="已取消，未做任何数据变更")

    if action != "confirm":
        return ConfirmGateOutcome(ok=False, status="invalid", message="未知操作")

    # 先置终态再执行回写：回写慢/被取消时重复点击会被 pending 校验拒绝（防重复回写）
    request.status = STATUS_CONFIRMED
    request.confirmed_by = operator_open_id or None
    request.confirmed_at = datetime.now(UTC)
    await db.flush()
    await _audit(db, request, action="confirm", operator_open_id=operator_open_id)

    if not execute:
        return ConfirmGateOutcome(
            ok=True, status="confirmed", message="已确认，正在回写台账…", request=request
        )

    result = await execute_writeback(db, request)
    if result["failed"]:
        return ConfirmGateOutcome(
            ok=False, status="error", message=f"回写失败 {len(result['failed'])} 条，请人工处理", request=request
        )
    return ConfirmGateOutcome(
        ok=True, status="confirmed", message="已确认，台账已更新", request=request
    )


# 回写字段值哨兵：创建时未知、确认执行时才解析（如处理日期=确认当天，
# 而非推送当天——隔日确认的语义正确性）
WRITEBACK_TODAY = "@today"


def _resolve_writeback_value(value: Any) -> Any:
    """解析回写字段值：``@today`` → 确认执行当天的毫秒时间戳（Base date 字段
    写入契约，对齐 submit._parse_date_ms）；其余原样。"""
    if value == WRITEBACK_TODAY:
        now = datetime.now(UTC)
        return int(
            datetime(now.year, now.month, now.day, tzinfo=UTC).timestamp() * 1000
        )
    return value


async def execute_writeback(
    db: AsyncSession, request: WarehouseConfirmRequest
) -> dict[str, Any]:
    """按映射逐条回写 Base（ref_table × ref_record_ids × writeback 字段）。

    writeback 值支持 ``@today`` 哨兵（确认执行当天毫秒时间戳）。逐条独立
    执行：失败条目记入 failed 列表并继续（不回滚已成功条目）；全部成功保持
    confirmed、写 writeback_ok 审计；有失败置 failed + writeback_failed 审计
    （含失败明细）。调用方负责 commit。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    writeback = {
        key: _resolve_writeback_value(value)
        for key, value in (request.writeback or {}).items()
    }
    record_ids = list(request.ref_record_ids or [])
    failed: list[dict[str, str]] = []
    ok_count = 0
    adapter = WarehouseBitableAdapter()
    for record_id in record_ids:
        try:
            await adapter.update_record(request.ref_table, record_id, dict(writeback))
            ok_count += 1
        except Exception as exc:  # noqa: BLE001 — 单条失败继续，明细入审计
            logger.exception(
                "确认门回写失败: request_no=%s record_id=%s", request.request_no, record_id
            )
            failed.append(
                {"record_id": record_id, "error": f"{type(exc).__name__}: {exc}"[:200]}
            )
    if failed:
        request.status = STATUS_FAILED
        await db.flush()
    await _audit(
        db,
        request,
        action="writeback_failed" if failed else "writeback_ok",
        operator_open_id=request.confirmed_by,
        detail={"ok": ok_count, "failed": failed, "fields": list(writeback.keys())},
    )
    return {"ok": ok_count, "failed": failed}


async def resend_request(
    db: AsyncSession,
    request: WarehouseConfirmRequest,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    dry_run: bool | None = None,
) -> bool:
    """重发确认卡（仅 pending）：新卡 + 刷新 message_id + 顺延 TTL + 计数。"""
    if request.status != STATUS_PENDING:
        raise ValueError("仅待确认状态可重发")
    request.expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    request.resend_count += 1
    await db.flush()
    sent = await send_request_card(request, dry_run=dry_run)
    await _audit(
        db,
        request,
        action="resend",
        detail={"sent": sent, "message_id": request.card_message_id},
    )
    return sent


async def expire_stale_requests(db: AsyncSession, *, now: datetime | None = None) -> int:
    """批量将超时 pending 置 expired（挂推送泵 tick；返回更新条数）。"""
    moment = now or datetime.now(UTC)
    stale = (
        await db.execute(
            select(WarehouseConfirmRequest).where(
                WarehouseConfirmRequest.status == STATUS_PENDING,
                WarehouseConfirmRequest.expires_at < moment,
                WarehouseConfirmRequest.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    for request in stale:
        request.status = STATUS_EXPIRED
        await _audit(db, request, action="expire", detail={"batch": True})
    return len(stale)
