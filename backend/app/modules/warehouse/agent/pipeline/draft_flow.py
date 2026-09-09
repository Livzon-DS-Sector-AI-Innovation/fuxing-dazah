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

确认执行回调：scene=receipt/gmp_outbound/finished_outbound 注册到 S1
ConfirmService（模块导入即注册，tools/office.py 同款模式）。回调为
submit_receipt/submit_gmp/submit_outbound 真身（薄包装延迟 import 解
cards↔draft_flow 模块环）：confirmed → submitted（写 Base + 读回核对），
见 pipeline/submit.py。

场景配置（S3 ticket 01/02，spec Implementation Decisions 1/2/5/6）：
``SCENE_CONFIG: dict[str, SceneConfig]`` 按场景收口中文名/必收字段/可写
字段/提交回调（receipt 零行为变化；gmp_outbound/finished_outbound 对话
收集）。对话收集场景（GMP/成品——无识别/对齐步骤）经
:func:`create_dialog_draft` 一步 created→aligned（fields 即 aligned；
recognized 留底原始收集值供审计回溯）。

卡片发送复用 notification dry_run 模式（测试经 _send_create 捕获或模块级
dry_run，不触网）。cards 延迟 import（cards → runner → tools.query →
tools.draft_update → 本模块存在模块环，运行时已加载完毕）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import confirm, repository
from app.modules.warehouse.agent.pipeline.aligner import AlignedReceipt
from app.modules.warehouse.agent.pipeline.recognizer import (
    REQUIRED_FIELDS,
    RecognizedReceipt,
)
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseAgentDraft

logger = logging.getLogger(__name__)

# 场景标识（drafts.scene 与确认卡片按钮 value.scene 同值；确认回调注册键）
RECEIPT_SCENE = "receipt"
GMP_OUTBOUND_SCENE = "gmp_outbound"
FINISHED_OUTBOUND_SCENE = "finished_outbound"  # 票02：成品出库登记（预留）

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


@dataclass(frozen=True)
class SceneConfig:
    """场景配置（spec Implementation Decisions 1/5/6；SCENE_CONFIG 值）。

    name_cn：场景中文名（卡片/回执文案与审计摘要）；
    required_fields：对话收集必收字段（canonical 键；receipt 复用识别必提
    集合，gmp_outbound/finished_outbound 为对话必收集）；
    writable_fields：Base 可写字段（业务字段名，submit 组装/审计对照口径；
    lookup/公式/created_user 等只读类型不在列——执行真身在 submit 的字段
    映射表，此处为配置快照）；
    submit：确认执行回调（ConfirmCallback）；None 表示提交尚未实现。三场景
    的回调均为薄包装（延迟 import submit 解 cards↔draft_flow 模块环，见
    文件尾部注册处）。
    """

    name_cn: str
    required_fields: tuple[str, ...]
    writable_fields: tuple[str, ...]
    submit: confirm.ConfirmCallback | None = None


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
    （票04 submit 下载回字节传附件列）。chat_id 落库——确认后回执按原渠道
    回复（群聊发起回群聊，私聊发起回私聊）。
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
        chat_id=chat_id,
            expires_at=expires_at,
        )
        db.add(draft)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()  # 序号并发冲突，重新生成（pipeline 自管事务，仅此一写）
            continue
        logger.info(
            "入库识别草稿已创建: draft_no=%s open_id=%s", draft_no, open_id[:20]
        )
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


async def create_dialog_draft(
    db: AsyncSession,
    *,
    scene: str,
    fields: dict[str, Any],
    open_id: str,
    chat_id: str | None = None,
    image_file_token: str | None = None,
) -> WarehouseAgentDraft:
    """对话收集场景草稿（S3 ticket 01）：created → aligned 一步到位。

    GMP/成品出库是对话收集非识别：无识别/对齐步骤，收集字段（canonical 键）
    直接作为 working set——``aligned = fields``（票04 submit 同款取值口径，
    update_draft 修改后覆盖），``recognized`` 存同内容原始收集值（审计回溯，
    不参与提交取值）。语义与迁移审计对齐 create_receipt_draft：create 与
    mark_aligned 各一条 audit，TTL/序号重试同款。
    """
    if scene not in SCENE_CONFIG:
        raise DraftFlowError(
            f"未知对话登记场景: {scene!r}（可选: {sorted(SCENE_CONFIG)}）"
        )
    started = time.monotonic()
    fields_json = dict(fields)
    expires_at = datetime.now(UTC) + timedelta(seconds=DRAFT_TTL_SECONDS)
    for _ in range(DRAFT_NO_RETRIES):
        draft_no = await _generate_draft_no(db)
        draft = WarehouseAgentDraft(
            draft_no=draft_no,
            scene=scene,
            status="created",
            source_image=image_file_token or None,
            recognized=fields_json,  # 原始收集值留底（审计回溯）
            aligned={},
            created_by_open_id=open_id,
            chat_id=chat_id,
            expires_at=expires_at,
        )
        db.add(draft)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()  # 序号并发冲突，重新生成（仅此一写）
            continue
        await _audit_transition(
            db,
            draft,
            action="create",
            from_status="",
            to_status="created",
            started=started,
            extra={"chat_id": (chat_id or "")[:30], "dialog": True},
        )
        # created → aligned：fields 即 aligned（对话收集无对齐步骤）
        draft.aligned = fields_json
        draft.status = "aligned"
        await db.flush()
        await _audit_transition(
            db,
            draft,
            action="mark_aligned",
            from_status="created",
            to_status="aligned",
            started=started,
            extra={"dialog": True},
        )
        logger.info(
            "对话登记草稿已创建: scene=%s draft_no=%s open_id=%s",
            scene,
            draft_no,
            open_id[:20],
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
        raise DraftFlowError(
            f"草稿 {draft.draft_no} 已过期，不能发送确认卡片（请重新识别）"
        )
    _ensure_transition(draft, "pending_confirm")
    started = time.monotonic()
    from_status = draft.status
    draft.status = "pending_confirm"
    await db.flush()

    from app.modules.warehouse.agent.cards import render_receipt_confirm_card

    card = render_receipt_confirm_card(draft)
    sent = False
    confirm_message_id: str | None = None
    try:
        if chat_id:
            confirm_message_id = await notification.send_card(chat_id, card)
        elif open_id:
            # 私聊场景（p2p chat_id 未传时回落 open_id 直发）
            confirm_message_id = await notification.send_card_to_user(open_id, card)
        sent = confirm_message_id is not None
    except Exception:  # noqa: BLE001 — 发送异常按失败落审计，不中断 Pipeline
        logger.exception(
            "入库确认卡片发送异常: draft_no=%s chat_id=%s",
            draft.draft_no,
            (chat_id or "")[:20],
        )
        sent = False
    if not sent:
        logger.warning(
            "入库确认卡片发送失败: draft_no=%s chat_id=%s",
            draft.draft_no,
            (chat_id or "")[:20],
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
    if confirm_message_id and confirm_message_id != "dry_run":
        try:
            import asyncio as _asyncio

            from app.core.redis import redis_client

            await _asyncio.wait_for(
                redis_client.set(
                    f"wh:draft:card:{draft.id}",
                    confirm_message_id,
                    ex=600,
                ),
                timeout=3.0,
            )
        except Exception:  # noqa: BLE001 — 存储失败仅影响卡片更新，不阻断
            logger.warning(
                "确认卡片 message_id 存储失败/超时: draft_no=%s", draft.draft_no
            )
    logger.info(
        "入库确认卡片已发送: draft_no=%s chat_id=%s",
        draft.draft_no,
        (chat_id or "")[:20],
    )
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
    stmt = select(WarehouseAgentDraft).where(
        WarehouseAgentDraft.status.in_(ACTIVE_STATUSES),
        WarehouseAgentDraft.is_deleted == False,  # noqa: E712
        WarehouseAgentDraft.expires_at.is_not(None),
        WarehouseAgentDraft.expires_at < now_dt,
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


# ── 确认执行回调（ConfirmService 注册；submit_receipt / submit_gmp 真身）──


async def _receipt_submit_callback(
    db: AsyncSession, draft: WarehouseAgentDraft
) -> str | None:
    """scene=receipt 确认回调（票04）：薄包装延迟 import submit（cards →
    runner → tools.query → tools.draft_update → 本模块 → submit → cards
    模块环，与上方 cards 延迟 import 同理；反向 import submit 亦经此解环）。
    确认门已先置 confirmed（S1 语义，防重复点击），submit_receipt 校验
    confirmed 后执行写入 → 读回核对 → submitted（详见 pipeline/submit.py）。"""
    from app.modules.warehouse.agent.pipeline.submit import submit_receipt

    return await submit_receipt(db, draft)


async def _gmp_submit_callback(
    db: AsyncSession, draft: WarehouseAgentDraft
) -> str | None:
    """scene=gmp_outbound 确认回调（S3 ticket 01）：薄包装延迟 import
    submit_gmp（解环同上）；confirmed → 写 GMP 物料出库总账 + 读回核对 →
    submitted（详见 pipeline/submit.py）。"""
    from app.modules.warehouse.agent.pipeline.submit import submit_gmp

    return await submit_gmp(db, draft)


async def _finished_submit_callback(
    db: AsyncSession, draft: WarehouseAgentDraft
) -> str | None:
    """scene=finished_outbound 确认回调（S3 ticket 02）：薄包装延迟 import
    submit_outbound（解环同上）；confirmed → 写成品出库台账 + 读回核对 →
    submitted + 回执含快递推送引导（详见 pipeline/submit.py）。"""
    from app.modules.warehouse.agent.pipeline.submit import submit_outbound

    return await submit_outbound(db, draft)


# 场景配置表（spec Implementation Decisions 1/2/5/6）：scene → 配置。
# receipt 沿用识别必提集合；gmp_outbound 对话必收四件套 + 可写八字段
# （物料名称为 lookup 拒写，不在此列——仅确认卡片展示）；finished_outbound
# 对话必收五件套 + 可写九字段（品规/各品种库存/质量状态/库存数量为公式/
# lookup、出库人为 created_user 拒写；快递号写 API 专用文本字段
# 「快递号(API)」（原字段为附件类型 type 17））。
SCENE_CONFIG: dict[str, SceneConfig] = {
    RECEIPT_SCENE: SceneConfig(
        name_cn="入库识别",
        required_fields=tuple(REQUIRED_FIELDS),
        writable_fields=(
            "物料名称",
            "厂家批号",
            "入库数量",
            "单位",
            "供应商",
            "生产商",
            "车牌",
            "合同编号或订单号",
            "包装规格",
            "生产日期",
            "到货情况",
            "外包装/厂家报告单/送货单照片",
        ),
        submit=_receipt_submit_callback,
    ),
    GMP_OUTBOUND_SCENE: SceneConfig(
        name_cn="GMP 出库登记",
        required_fields=(
            "material_batch_no",
            "quantity",
            "unit",
            "production_batch_no",
        ),
        writable_fields=(
            "物料批号(API)",
            "日期",
            "单据类型",
            "领用品种",
            "领用部门",
            "单位",
            "领用数量",
            "生产批号",
        ),
        submit=_gmp_submit_callback,
    ),
    FINISHED_OUTBOUND_SCENE: SceneConfig(
        name_cn="成品出库登记",
        required_fields=(
            "product_name",
            "product_batch_no",
            "quantity",
            "unit",
            "customer",
        ),
        writable_fields=(
            "出库日期",
            "产品名称",
            "产品批号",
            "出库量",
            "单位",
            "销售客户",
            "用途",
            "温度计",
            "备注",
            "快递号(API)",
        ),
        submit=_finished_submit_callback,
    ),
}

# 模块导入即注册（tools/office.py 同款模式；pipeline/__init__ 导入本模块时生效；
# gateway 导入 pipeline 保证卡片回调按 scene 分发可用）
for _scene, _config in SCENE_CONFIG.items():
    if _config.submit is not None:
        confirm.register_confirm_callback(_scene, _config.submit)
del _scene, _config
