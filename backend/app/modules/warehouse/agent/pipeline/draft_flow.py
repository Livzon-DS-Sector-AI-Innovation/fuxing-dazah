"""入库识别草稿状态机（S2 ticket 03，spec Implementation Decisions 4/5）。

Pipeline 的草稿生命周期封装：识别落库 → 对齐落库 → 确认卡片 → 确认/取消/
过期。每次状态迁移写 warehouse_agent_audit（tool_name="draft_flow"，
draft_id 关联）；幂等 = 迁移前校验当前状态，非法迁移抛 :class:`DraftFlowError`
（终态 confirmed/submitted/cancelled/expired/failed 不可再迁移）。

drafts 状态机（warehouse_agent_drafts.status，receipt 场景段）：
    created ──mark_aligned──────▶ aligned
    aligned ──send_confirm_card─▶ pending_confirm
    pending_confirm ──resend────▶ pending_confirm（对话修改字段后重发卡片）
    pending_confirm ──confirm───▶ confirmed（confirm.handle_action，S1 门）
    pending_confirm ──cancel────▶ cancelled（confirm.handle_action / cancel_draft）
    created/aligned/pending_confirm ──TTL──▶ expired（expire_stale 批量清扫）
    confirmed ──submit──▶ submitted（票04 submit_receipt：写 Base + 读回核对）

确认执行回调：scene=receipt 注册到 S1 ConfirmService（模块导入即注册，
tools/office.py 同款模式）。票04 起，回调为 submit_receipt 真身（薄包装
延迟 import 解 cards↔draft_flow 模块环）：confirmed → submitted（写 Base
+ 附件 + 读回核对），见 pipeline/submit.py。

卡片发送复用 notification dry_run 模式（测试经 _send_create 捕获或模块级
dry_run，不触网）。cards 延迟 import（cards → runner → tools.query →
tools.draft_update → 本模块存在模块环，运行时已加载完毕）。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import confirm, repository
from app.modules.warehouse.agent.pipeline.aligner import AlignedReceipt
from app.modules.warehouse.agent.pipeline.recognizer import RecognizedReceipt
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseAgentDraft

logger = logging.getLogger(__name__)

# 场景标识（drafts.scene 与确认卡片按钮 value.scene 同值；确认回调注册键）
RECEIPT_SCENE = "receipt"

# pending_confirm TTL（秒）：spec Implementation Decisions 4 —— 10 分钟
DRAFT_TTL_SECONDS = confirm.DEFAULT_TTL_SECONDS

# 活跃状态（expire/cancel 的作用域）；其余为终态，不可再迁移
ACTIVE_STATUSES: tuple[str, ...] = ("created", "aligned", "pending_confirm")

# 合法迁移表（幂等依据；pending_confirm→pending_confirm 为修改后重发卡片）
_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "created": ("aligned", "expired", "cancelled"),
    "aligned": ("pending_confirm", "expired", "cancelled"),
    "pending_confirm": ("pending_confirm", "confirmed", "cancelled", "expired"),
    "confirmed": ("submitted",),  # → submit_receipt（票04：写 Base + 读回核对）
    "submitted": (),
    "cancelled": (),
    "expired": (),
    "failed": (),
}

# draft_no 序号重试次数（唯一索引并发冲突兜底；WR+YYYYMMDD+3 位序号，仿 plans WP）
DRAFT_NO_RETRIES = 3


class DraftFlowError(ValueError):
    """草稿状态机非法迁移（幂等拒绝 / 状态前置校验失败）。"""


# ── 审计（每次迁移一条，draft_id 关联）──


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def _audit_transition(
    db: AsyncSession,
    draft: WarehouseAgentDraft,
    *,
    action: str,
    from_status: str,
    to_status: str,
    result_status: str = "ok",
    error_code: str | None = None,
    started: float,
    extra: dict[str, Any] | None = None,
) -> None:
    await repository.insert_agent_audit(
        db,
        tool_name="draft_flow",
        args_summary={
            "action": action,
            "draft_no": draft.draft_no,
            "from": from_status,
            "to": to_status,
            **(extra or {}),
        },
        result_status=result_status,
        error_code=error_code,
        duration_ms=_elapsed_ms(started),
        draft_id=draft.id,
    )


def _ensure_transition(draft: WarehouseAgentDraft, target: str) -> None:
    """状态前置校验（幂等）：非法迁移抛 :class:`DraftFlowError`。"""
    current = draft.status
    if target not in _TRANSITIONS.get(current, ()):
        raise DraftFlowError(
            f"草稿 {draft.draft_no} 状态为 {current}，不允许迁移到 {target}"
        )


# ── draft_no：WR + YYYYMMDD + '-' + 当日 3 位序号 ──


async def _generate_draft_no(db: AsyncSession) -> str:
    """draft_no = WR + YYYYMMDD + '-' + 当日 3 位序号（字典序=序号序，仿 WP）。"""
    prefix = f"WR{datetime.now(UTC).strftime('%Y%m%d')}"
    last = await repository.get_latest_draft_no_on_prefix(db, prefix=prefix)
    seq = 1
    if last:
        try:
            seq = int(last.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    return f"{prefix}-{seq:03d}"


# ── 状态机迁移 ──


async def create_receipt_draft(
    db: AsyncSession,
    *,
    recognized: RecognizedReceipt,
    image_file_token: str | None = None,
    open_id: str,
    chat_id: str | None = None,
) -> WarehouseAgentDraft:
    """识别落库：新建 scene=receipt 草稿（status=created + TTL 10min）。

    recognized JSONB 存 ``RecognizedReceipt.model_dump()``（13 字段 value/
    confidence + raw，票04/05 审计回溯用）；source_image 存原图 file token
    （票04 submit 下载回字节传附件列）。chat_id 仅用于审计摘要——卡片发送
    由调用方显式传目标（send_confirm_card），草稿本身不存会话。
    """
    started = time.monotonic()
    recognized_json = recognized.model_dump(mode="json")
    expires_at = datetime.now(UTC) + timedelta(seconds=DRAFT_TTL_SECONDS)
    for _ in range(DRAFT_NO_RETRIES):
        draft_no = await _generate_draft_no(db)
        draft = WarehouseAgentDraft(
            draft_no=draft_no,
            scene=RECEIPT_SCENE,
            status="created",
            source_image=image_file_token or None,
            recognized=recognized_json,
            aligned={},
            created_by_open_id=open_id,
            expires_at=expires_at,
        )
        db.add(draft)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()  # 序号并发冲突，重新生成（pipeline 自管事务，仅此一写）
            continue
        logger.info("入库识别草稿已创建: draft_no=%s open_id=%s", draft_no, open_id[:20])
        await _audit_transition(
            db,
            draft,
            action="create",
            from_status="",
            to_status="created",
            started=started,
            extra={"chat_id": (chat_id or "")[:30], "image": bool(image_file_token)},
        )
        return draft
    raise DraftFlowError("草稿编号生成冲突，请重试")


async def mark_aligned(
    db: AsyncSession, draft: WarehouseAgentDraft, aligned: AlignedReceipt
) -> None:
    """created → aligned：主数据对齐结果落库。

    aligned JSONB = 对齐字段（标准名/代码/大类…）+ match_confidence +
    match_detail（卡片渲染与票04 submit 的输入；recognized 不改写，审计可回溯）。
    """
    _ensure_transition(draft, "aligned")
    started = time.monotonic()
    from_status = draft.status
    draft.aligned = {
        **aligned.aligned,
        "match_confidence": aligned.match_confidence,
        "match_detail": aligned.match_detail,
    }
    draft.status = "aligned"
    await db.flush()
    await _audit_transition(
        db,
        draft,
        action="mark_aligned",
        from_status=from_status,
        to_status="aligned",
        started=started,
        extra={"match": aligned.match_confidence},
    )


async def send_confirm_card(
    db: AsyncSession,
    draft: WarehouseAgentDraft,
    *,
    chat_id: str | None = None,
    open_id: str | None = None,
) -> None:
    """aligned → pending_confirm（或 pending_confirm 重发）+ 确认卡片发送。

    确认卡片只在 pending_confirm 状态有效（confirm.handle_action 校验
    status==pending_confirm），本函数是唯一迁移入口：首发出现在对齐后，
    对话修改（tools/draft_update）后重发。发送目标：群/会话 chat_id 优先，
    缺省私聊发发起人 open_id（office.request_card_send 同款兜底）。
    发送失败不回滚迁移（草稿保持 pending_confirm，audit 记 send_failed）。
    """

    if draft.expires_at is not None and draft.expires_at < datetime.now(UTC):
        raise DraftFlowError(f"草稿 {draft.draft_no} 已过期，不能发送确认卡片（请重新识别）")
    _ensure_transition(draft, "pending_confirm")
    started = time.monotonic()
    from_status = draft.status
    draft.status = "pending_confirm"
    await db.flush()

    from app.modules.warehouse.agent.cards import render_receipt_confirm_card

    card = render_receipt_confirm_card(draft)
    sent = False
    try:
        if chat_id:
            sent = await notification.send_card(chat_id, card) is not None
        elif open_id:
            sent = await notification.send_card_to_user(open_id, card)
    except Exception:  # noqa: BLE001 — 发送异常按失败落审计，不中断 Pipeline
        logger.exception(
            "入库确认卡片发送异常: draft_no=%s chat_id=%s",
            draft.draft_no, (chat_id or "")[:20],
        )
        sent = False
    if not sent:
        logger.warning(
            "入库确认卡片发送失败: draft_no=%s chat_id=%s",
            draft.draft_no, (chat_id or "")[:20],
        )
        await _audit_transition(
            db,
            draft,
            action="send_confirm_card",
            from_status=from_status,
            to_status="pending_confirm",
            result_status="error",
            error_code="send_failed",
            started=started,
        )
        return
    logger.info("入库确认卡片已发送: draft_no=%s chat_id=%s", draft.draft_no, (chat_id or "")[:20])
    await _audit_transition(
        db,
        draft,
        action="send_confirm_card",
        from_status=from_status,
        to_status="pending_confirm",
        started=started,
        extra={"resend": from_status == "pending_confirm"},
    )


async def cancel_draft(
    db: AsyncSession,
    draft: WarehouseAgentDraft,
    *,
    operator_open_id: str | None = None,
) -> None:
    """活跃 → cancelled（对话/程序取消入口；卡片取消按钮走 confirm.handle_action）。"""
    _ensure_transition(draft, "cancelled")
    started = time.monotonic()
    from_status = draft.status
    draft.status = "cancelled"
    await db.flush()
    await _audit_transition(
        db,
        draft,
        action="cancel",
        from_status=from_status,
        to_status="cancelled",
        started=started,
        extra={"operator": (operator_open_id or "")[:30]},
    )


async def expire_stale(db: AsyncSession, *, now: datetime | None = None) -> int:
    """TTL 批量过期：活跃状态且 expires_at 已过的草稿置 expired，逐条 audit。

    轻量清扫入口（调度接 V1.1；当前由 pipeline/确认路径按需调用兜底——
    confirm.handle_action 点击时也会做过期校验）。返回本次过期数量。
    """
    now_dt = now or datetime.now(UTC)
    stmt = (
        select(WarehouseAgentDraft)
        .where(
            WarehouseAgentDraft.status.in_(ACTIVE_STATUSES),
            WarehouseAgentDraft.is_deleted == False,  # noqa: E712
            WarehouseAgentDraft.expires_at.is_not(None),
            WarehouseAgentDraft.expires_at < now_dt,
        )
    )
    drafts = list((await db.execute(stmt)).scalars().all())
    for draft in drafts:
        from_status = draft.status
        draft.status = "expired"
        await db.flush()
        await _audit_transition(
            db,
            draft,
            action="expire",
            from_status=from_status,
            to_status="expired",
            started=time.monotonic(),
        )
    if drafts:
        logger.info("入库草稿过期清扫: %s 条", len(drafts))
    return len(drafts)


# ── 确认执行回调（ConfirmService 注册；票04 起为 submit_receipt 真身）──


async def _receipt_submit_callback(
    db: AsyncSession, draft: WarehouseAgentDraft
) -> str | None:
    """scene=receipt 确认回调（票04）：薄包装延迟 import submit（cards →
    runner → tools.query → tools.draft_update → 本模块 → submit → cards
    模块环，与下方 cards 延迟 import 同理；反向 import submit 亦经此解环）。
    确认门已先置 confirmed（S1 语义，防重复点击），submit_receipt 校验
    confirmed 后执行写入 → 读回核对 → submitted（详见 pipeline/submit.py）。"""
    from app.modules.warehouse.agent.pipeline.submit import submit_receipt

    return await submit_receipt(db, draft)


# 模块导入即注册（tools/office.py 同款模式；pipeline/__init__ 导入本模块时生效；
# gateway 导入 pipeline 保证卡片回调 scene=receipt 分发可用）
confirm.register_confirm_callback(RECEIPT_SCENE, _receipt_submit_callback)
