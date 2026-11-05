"""五金库领料审批双通道（M3，设计 §五/§十一 M3）。

ApprovalChannel 抽象 + feishu / manual 两实现，工厂按配置选择：
- feishu 通道：对接新审批定义「五金库领料申请」（definition code 从
  env/config 读，未配置=通道不可用自动落 manual）；uuid 幂等创建实例；
  审批结果轮询兜底复用 list_instance_codes 增量拉取。
- manual 通道：部门主管在领用中心点确认=审批结果代录（approve/reject
  API 直改状态机）。

状态机对通道无感：pending（预扣）→ approved（预扣保持）→ issued（实扣）
/ rejected（释放）；两通道产出相同的 requisition 状态迁移。

配置（backend/app/core/config.py env，未配置自动 manual）：
- HARDWARE_APPROVAL_CHANNEL: feishu | manual（默认 manual）
- HARDWARE_APPROVAL_CODE: 飞书审批定义 code（业务部门建好后填）
- HARDWARE_APPROVAL_USER_KEY: 发起人 user_id 口径（open_id|user_id，默认 user_id）
"""

from __future__ import annotations

import logging
import uuid as _uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareRequisition,
    HardwareScrap,
)

logger = logging.getLogger(__name__)


class ApprovalChannelError(Exception):
    """审批通道错误（提交/轮询失败）。"""


class ApprovalChannel(ABC):
    """审批通道抽象：状态机对通道无感（提交 + 结果查询两能力）。"""

    name: str = "abstract"

    @abstractmethod
    async def submit(self, db: AsyncSession, req: HardwareRequisition, items: list[dict[str, Any]]) -> str:
        """创建审批载体，返回外部引用（instance_code 或通道标记）。"""

    @abstractmethod
    async def poll_result(self, db: AsyncSession, req: HardwareRequisition) -> str | None:
        """查询审批结果：approved / rejected / None（未决）。"""


# ── feishu 通道 ──


class FeishuApprovalChannel(ApprovalChannel):
    """飞书审批：definition code 配置化，未配置=通道不可用。"""

    name = "feishu"

    def __init__(self, approval_code: str) -> None:
        self.approval_code = approval_code

    @staticmethod
    def _credentials() -> tuple[str | None, str | None]:
        """safety 应用凭证（2026-10-28 已拍板：审批 API 全走 safety）。"""
        settings = get_settings()
        return (
            getattr(settings, "SAFETY_FEISHU_APP_ID", None) or None,
            getattr(settings, "SAFETY_FEISHU_APP_SECRET", None) or None,
        )

    async def submit(
        self, db: AsyncSession, req: HardwareRequisition, items: list[dict[str, Any]]
    ) -> str:
        import json as _json

        from app.platform.integrations.feishu.approval import (
            ApprovalAPIError,
            create_instance,
        )

        app_id, app_secret = self._credentials()
        if not app_id or not app_secret:
            raise ApprovalChannelError("safety 应用审批凭证未配置（SAFETY_FEISHU_APP_ID/SECRET）")

        settings = get_settings()
        user_id = req.applicant_open_id or ""
        if getattr(settings, "HARDWARE_APPROVAL_USER_KEY", "user_id") == "user_id":
            # open_id 与 user_id 同值场景（本系统 identity 用户 open_id 直传）；
            # 定义侧为 user_id 口径时由审批后台字段映射兼容
            user_id = user_id or ""

        form = [
            {"id": "widget1", "type": "input", "value": req.dept_name},  # 领用部门
            {"id": "widget2", "type": "input", "value": req.applicant},  # 领用人
            {"id": "widget3", "type": "textarea", "value": req.purpose or "-"},  # 用途
            # 物料明细（多行控件以 markdown 汇总；定义建好后按实际控件 id 调整）
            {
                "id": "widget4",
                "type": "textarea",
                "value": "\n".join(
                    f"{it['material_name']} {it.get('spec') or ''} × {it['need_qty']}"
                    f" {it.get('unit') or ''}"
                    for it in items
                ),
            },
            {"id": "widget5", "type": "input", "value": "紧急" if req.req_type == "urgent" else "常规"},
            {"id": "widget6", "type": "input", "value": req.req_no},  # 单号回溯键
        ]
        # uuid 幂等：req.id 派生（重试不重单）
        idempotency = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"hardware-requisition:{req.id}"))
        try:
            instance_code = await create_instance(
                self.approval_code,
                user_id,
                form,
                app_id=app_id,
                app_secret=app_secret,
                uuid_idempotency=idempotency,
            )
        except ApprovalAPIError as exc:
            raise ApprovalChannelError(f"飞书审批实例创建失败: {exc}") from exc
        req.approval_channel = "feishu"
        req.approval_instance_code = instance_code
        req.approval_status = "pending"
        await db.flush()
        return instance_code

    async def poll_result(self, db: AsyncSession, req: HardwareRequisition) -> str | None:
        from app.platform.integrations.feishu.approval import (
            ApprovalAPIError,
            get_instance,
        )

        if not req.approval_instance_code:
            return None
        app_id, app_secret = self._credentials()
        try:
            instance = await get_instance(
                req.approval_instance_code, app_id=app_id, app_secret=app_secret
            )
        except ApprovalAPIError as exc:
            logger.warning("五金领料审批轮询失败 req=%s: %s", req.req_no, exc)
            return None
        status = str(instance.get("status") or "")
        # 飞书审批实例状态：APPROVED / REJECTED / CANCELED / PENDING
        if status == "APPROVED":
            return "approved"
        if status == "REJECTED":
            return "rejected"
        return None


# ── manual 通道 ──


class ManualApprovalChannel(ApprovalChannel):
    """manual 通道：部门主管在系统领用中心点确认=审批结果代录。

    submit 只登记通道标记（无外部载体）；结果由 approve/reject API
    直改状态机（approval_status 同步落），poll_result 恒 None。
    """

    name = "manual"

    async def submit(
        self, db: AsyncSession, req: HardwareRequisition, items: list[dict[str, Any]]
    ) -> str:
        req.approval_channel = "manual"
        req.approval_status = "pending"
        await db.flush()
        return f"manual:{req.req_no}"

    async def poll_result(self, db: AsyncSession, req: HardwareRequisition) -> str | None:
        return None  # manual 结果由人操作直接写状态机，无需轮询


# ── 工厂 ──


def get_approval_channel() -> ApprovalChannel:
    """按配置选择通道：HARDWARE_APPROVAL_CHANNEL != feishu 或 definition
    code 未配置 → manual（业务部门建好定义+配置 code 后自动切 feishu）。"""
    settings = get_settings()
    channel = str(getattr(settings, "HARDWARE_APPROVAL_CHANNEL", "manual") or "manual").lower()
    code = str(getattr(settings, "HARDWARE_APPROVAL_CODE", "") or "").strip()
    if channel == "feishu" and code:
        return FeishuApprovalChannel(code)
    return ManualApprovalChannel()


def feishu_channel_configured() -> bool:
    """feishu 通道是否已就绪（definition code 已配置）。"""
    settings = get_settings()
    return bool(
        str(getattr(settings, "HARDWARE_APPROVAL_CHANNEL", "") or "").lower() == "feishu"
        and str(getattr(settings, "HARDWARE_APPROVAL_CODE", "") or "").strip()
    )


# ── 报废审批（三期 M7：复用双通道抽象，新 definition key 配置化；不改领料语义）──


class _ScrapManualApprovalChannel(ManualApprovalChannel):
    """报废 manual 通道：两步系统内确认的载体标记（dept_confirm→final_approve
    由人操作直写状态机，submit 只登记通道）。"""

    name = "manual"

    async def submit_scrap(
        self, db: AsyncSession, scrap: HardwareScrap, items: list[dict[str, Any]]
    ) -> str:
        scrap.approval_channel = "manual"
        scrap.approval_status = "pending"
        await db.flush()
        return f"manual:{scrap.scrap_no}"


class _ScrapFeishuApprovalChannel(FeishuApprovalChannel):
    """报废 feishu 通道：definition key 独立配置（HARDWARE_SCRAP_APPROVAL_CODE），
    表单照领料同构（部门/发起人/原因/明细汇总/单号回溯键）。制度定稿业务部门
    建好定义后只改配置切换，代码零改动。"""

    name = "feishu"

    def __init__(self, approval_code: str) -> None:
        super().__init__(approval_code)

    async def submit_scrap(
        self, db: AsyncSession, scrap: HardwareScrap, items: list[dict[str, Any]]
    ) -> str:
        from app.platform.integrations.feishu.approval import (
            ApprovalAPIError,
            create_instance,
        )

        app_id, app_secret = self._credentials()
        if not app_id or not app_secret:
            raise ApprovalChannelError("safety 应用审批凭证未配置（SAFETY_FEISHU_APP_ID/SECRET）")

        from app.modules.warehouse.hardware.scrap import SCRAP_REASON_LABELS

        form = [
            {"id": "widget1", "type": "input", "value": scrap.dept_name},  # 发起部门
            {"id": "widget2", "type": "input", "value": scrap.requested_by},  # 发起人
            {
                "id": "widget3",
                "type": "textarea",
                "value": (
                    f"{SCRAP_REASON_LABELS.get(scrap.scrap_reason, scrap.scrap_reason)}"
                    f"：{scrap.reason_note or '-'}"
                ),
            },  # 报废条件+说明
            # 物料明细（多行控件以 markdown 汇总；定义建好后按实际控件 id 调整）
            {
                "id": "widget4",
                "type": "textarea",
                "value": "\n".join(
                    f"{it['material_name']} {it.get('spec') or ''} × {it['quantity']}"
                    f" {it.get('unit') or ''}"
                    for it in items
                ),
            },
            {"id": "widget5", "type": "input", "value": scrap.scrap_no},  # 单号回溯键
        ]
        # uuid 幂等：scrap.id 派生（重试不重单）
        idempotency = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"hardware-scrap:{scrap.id}"))
        try:
            instance_code = await create_instance(
                self.approval_code,
                scrap.requested_by_open_id or "",
                form,
                app_id=app_id,
                app_secret=app_secret,
                uuid_idempotency=idempotency,
            )
        except ApprovalAPIError as exc:
            raise ApprovalChannelError(f"飞书报废审批实例创建失败: {exc}") from exc
        scrap.approval_channel = "feishu"
        scrap.approval_instance_code = instance_code
        scrap.approval_status = "pending"
        await db.flush()
        return instance_code


def get_scrap_approval_channel() -> _ScrapManualApprovalChannel | _ScrapFeishuApprovalChannel:
    """报废审批通道工厂：HARDWARE_SCRAP_APPROVAL_CHANNEL=feishu 且
    HARDWARE_SCRAP_APPROVAL_CODE 已配置 → feishu；否则 manual 两步
    （业务部门建好定义+配置 code 后自动切换）。"""
    settings = get_settings()
    channel = str(
        getattr(settings, "HARDWARE_SCRAP_APPROVAL_CHANNEL", "manual") or "manual"
    ).lower()
    code = str(getattr(settings, "HARDWARE_SCRAP_APPROVAL_CODE", "") or "").strip()
    if channel == "feishu" and code:
        return _ScrapFeishuApprovalChannel(code)
    return _ScrapManualApprovalChannel()


# ── 提交编排（API 层 submit 后调用；通道失败自动落 manual 兜底）──


async def submit_approval(db: AsyncSession, req: HardwareRequisition) -> str | None:
    """领料单提交审批：按配置走通道；feishu 失败降级 manual 不阻断业务。"""
    items = await _load_items(db, req)
    channel = get_approval_channel()
    try:
        ref = await channel.submit(db, req, items)
        logger.info("五金领料审批已提交: req=%s channel=%s ref=%s", req.req_no, channel.name, ref)
        return ref
    except ApprovalChannelError:
        if channel.name == "feishu":
            # feishu 通道故障 → manual 兜底（预扣已生效，审批方式不阻断）
            logger.warning("feishu 审批提交失败，降级 manual 通道: req=%s", req.req_no, exc_info=True)
            fallback = ManualApprovalChannel()
            return await fallback.submit(db, req, items)
        raise


async def _load_items(db: AsyncSession, req: HardwareRequisition) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.modules.warehouse.hardware.models import HardwareRequisitionItem

    rows = (
        await db.execute(
            select(HardwareRequisitionItem).where(
                HardwareRequisitionItem.requisition_id == req.id,
                HardwareRequisitionItem.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    items = []
    for row in rows:
        material = await db.get(HardwareMaterial, row.material_id)
        items.append(
            {
                "material_name": material.name if material else "-",
                "spec": material.spec if material else None,
                "unit": material.unit if material else None,
                "need_qty": float(row.need_qty),
            }
        )
    return items


# ── feishu 结果轮询兜底（scheduled.py 定时任务调用）──


async def poll_pending_approvals(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """增量拉取 feishu 通道 pending 单的审批结果并同步状态机。

    只处理 approval_channel=feishu 且 status=pending 的单（manual 通道
    结果由人直写，不在此列）；approved → service.approve（预扣保持）；
    rejected → service.reject（释放预扣）。
    """
    from app.modules.warehouse.hardware import service as hw_service
    from sqlalchemy import select

    now = now or datetime.now(UTC)
    pending = (
        await db.execute(
            select(HardwareRequisition).where(
                HardwareRequisition.approval_channel == "feishu",
                HardwareRequisition.status == "pending",
                HardwareRequisition.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    stats = {"checked": len(pending), "approved": 0, "rejected": 0}
    channel = get_approval_channel()
    if not isinstance(channel, FeishuApprovalChannel):
        return stats  # 未配置 feishu 通道，无轮询对象
    for req in pending:
        result = await channel.poll_result(db, req)
        if result == "approved":
            await hw_service.approve_requisition(
                db, req.id,
                approver=req.approved_by or "飞书审批",
                note="飞书审批通过（轮询同步）",
            )
            stats["approved"] += 1
        elif result == "rejected":
            await hw_service.reject_requisition(
                db, req.id,
                approver="飞书审批",
                reason="飞书审批驳回（轮询同步）",
            )
            stats["rejected"] += 1
    return stats
