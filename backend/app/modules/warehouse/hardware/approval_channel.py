"""五金库领料审批双通道（M3，设计 §五/§十一 M3）。

ApprovalChannel 抽象 + feishu / manual 两实现，工厂按配置选择：
- feishu 通道：前端申领（弹窗二次确认 + 选择审批人）提交即**代发起**
  「福兴电子领/退料单审批」（definition code 从 env/config 读，未配置=通道
  不可用自动落 manual）；系统代发走「五金库领料-平台」分支（分流键选项
  value + 六个顶层普通控件，API 可写；人工填单的多维表格明细分支 API 不
  支持）；审批人为发起人自选节点（主管及以上），必须随实例提交
  node_approver_user_id_list；uuid 幂等；审批结果轮询兜底复用
  list_instance_codes 增量拉取；审批 API 走仓储应用凭证（2026-11-10 拍板）。
  发起失败=上抛，单据回滚草稿（2026-11-19 拍板：不再静默降级 manual）。
- manual 通道：部门主管在领用中心点确认=审批结果代录（approve/reject
  API 直改状态机）。

状态机对通道无感：pending（预扣）→ approved（预扣保持）→ issued（实扣）
/ rejected（释放）；两通道产出相同的 requisition 状态迁移。

配置（backend/app/core/config.py env，未配置自动 manual）：
- HARDWARE_APPROVAL_CHANNEL: feishu | manual（默认 manual；切换步骤=改
  backend/.env.development 该键为 feishu + 确认 HARDWARE_APPROVAL_CODE
  已配「福兴电子领/退料单审批」code + 重启后端）
- HARDWARE_APPROVAL_CODE: 飞书审批定义 code（业务部门建好后填）
- HARDWARE_APPROVAL_NODE_ID: 「主管及以上审批」节点 id（定义改版后覆盖）
- HARDWARE_APPROVAL_USER_KEY: 已弃用（发起人统一按 identity.users.feishu_user_id）
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

# 「福兴电子领/退料单审批」控件 ID（与 approval_ingest 同源；系统代发只发领料
# ——退料入口是员工飞书自发起，摄取层建退库草稿）。
# 2026-11-19 平台分支定性（真机三证：定义接口 + create 成功 + 实例读回）：
# - 系统代发走「五金库领料-平台」分支（普通 input/number 六个顶层控件），
#   不用 五金库领料 明细 fieldList——后者是关联多维表格控件，飞书创建实例
#   API 不支持（行会被静默丢弃/校验报幽灵控件，2026-11-19 已实测）。
# - 单选分流键值是**选项 value**，读回时才归一成文本。
KIND_WIDGET_ID = "widget17942773552310001"  # 单选：五金库领料/领退料/平台
KIND_VALUE_REQUISITION = "mwa2erxb-pjfkprp9r9e-0"  # 选项 value（写接口口径）
KIND_VALUE_RETURN = "mwbvpcpg-zevsx2cn1yc-1"
KIND_VALUE_PLATFORM = "mwncy1jd-m87rnkvo2p-1"  # 五金库领料-平台（系统代发分支）
DETAIL_WIDGET_ID = "widget17942790533710001"  # 五金库领料明细 fieldList（人工填单）

# 「是否紧急」单选（2026-11-20 改版：紧急领料打标+紧急原因，与 approval_ingest
# 同源；显示条件=领料∨平台分支，「紧急原因」仅 是否紧急=是 时显示/必填）
URGENT_WIDGET_ID = "widget17951544578680001"
URGENT_VALUE_YES = "mwokm4ng-jf0ljqu7rwb-0"
URGENT_VALUE_NO = "mwokm4ng-5bvpjhmhs1u-0"
URGENT_REASON_WIDGET_ID = "widget17951566636350001"

# 平台分支六个顶层控件（id, 名称, 类型, 取值键）——普通控件，API 可写
PLATFORM_WIDGETS: tuple[tuple[str, str, str, str], ...] = (
    ("widget17950811346260001", "类别", "input", "category"),
    ("widget17950811558710001", "名称", "input", "material_name"),
    ("widget17950811686580001", "规格", "input", "spec"),
    ("widget17950811760340001", "单位", "input", "unit"),
    ("widget17950811860230001", "可领量", "number", "available"),
    ("widget17950812036890001", "领料量", "number", "need_qty"),
)

# 「主管及以上审批」节点（发起人自选）：创建实例时必须指定审批人，
# 否则节点无人可批。节点 id 可被 HARDWARE_APPROVAL_NODE_ID 覆盖（定义改版）。
APPROVER_NODE_ID = "043453bb3477199c9dd17bd7d0ccba3b"


def build_platform_form(
    items: list[dict[str, Any]], *, urgent: bool = False, urgent_reason: str = ""
) -> list[dict[str, Any]]:
    """单据明细 → 平台分支表单（分流键 + 是否紧急 [+ 紧急原因] + 六个普通控件）。

    平台分支是单物资结构（顶层控件而非 fieldList）：一单多物资时需拆单，
    由调用方校验拦截。「是否紧急」为必填控件，不写有被实例创建必填校验
    拒收的风险——一律显式写（紧急=是 时连带写「紧急原因」，否则该控件
    隐藏不必写）。radio/input 值=文本，number 值=浮点（真机读回同构）。
    """
    if len(items) != 1:
        raise ApprovalChannelError(
            f"平台分支仅支持单物资申领（当前 {len(items)} 行），请拆单后提交"
        )
    if urgent and not urgent_reason.strip():
        raise ApprovalChannelError("紧急申领必须填写紧急原因")
    it = items[0]
    form: list[dict[str, Any]] = [
        {"id": KIND_WIDGET_ID, "type": "radioV2", "value": KIND_VALUE_PLATFORM},
        {
            "id": URGENT_WIDGET_ID,
            "type": "radioV2",
            "value": URGENT_VALUE_YES if urgent else URGENT_VALUE_NO,
        },
    ]
    if urgent:
        form.append(
            {"id": URGENT_REASON_WIDGET_ID, "type": "input", "value": urgent_reason.strip()}
        )
    for widget_id, _name, wtype, key in PLATFORM_WIDGETS:
        raw = it.get(key)
        value: Any = float(raw or 0) if wtype == "number" else str(raw or "")
        form.append({"id": widget_id, "type": wtype, "value": value})
    return form


async def _resolve_starter_user_id(db: AsyncSession, req: HardwareRequisition) -> str:
    """领用人 → 飞书 user_id（创建审批实例的发起人锚点）。

    identity.users.id（applicant_user_id）→ feishu_user_id 优先；缺 user id 时
    按 applicant_open_id 反查同表，仍缺才原值兜底（可能是 ou_ 值，创建会报错，
    由调用方转成可读失败信息）。
    """
    from sqlalchemy import text

    if req.applicant_user_id is not None:
        row = (
            await db.execute(
                text(
                    "select feishu_user_id from identity.users "
                    "where id = :uid and is_deleted = false limit 1"
                ),
                {"uid": req.applicant_user_id},
            )
        ).first()
        if row and row[0]:
            return str(row[0])
    if req.applicant_open_id:
        row = (
            await db.execute(
                text(
                    "select feishu_user_id from identity.users "
                    "where feishu_open_id = :oid and is_deleted = false limit 1"
                ),
                {"oid": req.applicant_open_id},
            )
        ).first()
        if row and row[0]:
            return str(row[0])
        return str(req.applicant_open_id)
    return ""


class FeishuApprovalChannel(ApprovalChannel):
    """飞书审批：definition code 配置化，未配置=通道不可用。"""

    name = "feishu"

    def __init__(self, approval_code: str) -> None:
        self.approval_code = approval_code

    @staticmethod
    def _credentials() -> tuple[str | None, str | None]:
        """仓储应用凭证（2026-11-10 拍板：审批 API 走仓储应用，推翻 10-28
        safety 口径——safety app 无 approval:definition 读权限 99991672）。"""
        settings = get_settings()
        return (
            getattr(settings, "WAREHOUSE_FEISHU_APP_ID", None) or None,
            getattr(settings, "WAREHOUSE_FEISHU_APP_SECRET", None) or None,
        )

    async def submit(
        self, db: AsyncSession, req: HardwareRequisition, items: list[dict[str, Any]]
    ) -> str:
        from app.platform.integrations.feishu.approval import (
            ApprovalAPIError,
            create_instance,
        )

        app_id, app_secret = self._credentials()
        if not app_id or not app_secret:
            raise ApprovalChannelError(
                "仓储应用审批凭证未配置（WAREHOUSE_FEISHU_APP_ID/SECRET）"
            )

        user_id = await _resolve_starter_user_id(db, req)
        if not user_id:
            raise ApprovalChannelError(
                "发起人飞书 user_id 未解析（identity.users.feishu_user_id 缺失），无法代发起审批"
            )

        # 平台分支：分流键 + 是否紧急/紧急原因 + 六个普通控件（API 可写；人工
        # 填单仍走明细表分支）；紧急原因 schema 必填校验在前，这里双保险
        form = build_platform_form(
            items,
            urgent=req.req_type == "urgent",
            urgent_reason=req.urgent_reason or "",
        )
        # 发起人自选审批节点：必须带申领时选定的审批人（主管及以上），否则节点无人可批
        approver_uid = str(req.approver_user_id or "").strip()
        if not approver_uid:
            raise ApprovalChannelError("未选择审批人（主管及以上），请重新提交并选择审批人")
        node_id = str(
            getattr(get_settings(), "HARDWARE_APPROVAL_NODE_ID", "") or APPROVER_NODE_ID
        )
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
                node_approver_user_id_list={node_id: [approver_uid]},
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
            raise ApprovalChannelError(
                "仓储应用审批凭证未配置（WAREHOUSE_FEISHU_APP_ID/SECRET）"
            )

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


# ── 提交编排（API 层 submit 后调用；feishu 失败上抛，由 API 回滚草稿）──


async def submit_approval(db: AsyncSession, req: HardwareRequisition) -> str | None:
    """领料单提交审批：按配置走通道；feishu 失败上抛（不降级、不阻断重试）。"""
    items = await _load_items(db, req)
    channel = get_approval_channel()
    try:
        ref = await channel.submit(db, req, items)
    except ApprovalChannelError:
        # 2026-11-19 拍板：feishu 通道失败**不再静默降级 manual**——审批没真正
        # 发起时不要让单据停在「等审批」假象里；异常上抛由 API 层回滚草稿。
        logger.exception("五金领料审批提交失败: req=%s channel=%s", req.req_no, channel.name)
        raise
    logger.info("五金领料审批已提交: req=%s channel=%s ref=%s", req.req_no, channel.name, ref)
    return ref


async def _load_items(db: AsyncSession, req: HardwareRequisition) -> list[dict[str, Any]]:
    """单据明细 → 审批表单行（含提交时可领快照）。

    可领量 = 当前 available + 本行 need_qty（提交已预扣，加回本行即预扣前面向
    申请人的可领量，与申领当时所见一致）。
    """
    from sqlalchemy import select

    from app.modules.warehouse.hardware.models import HardwareRequisitionItem
    from app.modules.warehouse.hardware.service import available_of_material

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
        available = await available_of_material(db, row.material_id) + row.need_qty
        items.append(
            {
                "material_name": material.name if material else "-",
                "spec": material.spec if material else None,
                "unit": material.unit if material else None,
                "category": material.category if material else None,
                "code": material.code if material else None,
                "need_qty": float(row.need_qty),
                "available": float(available),
            }
        )
    return items


# ── 系统内取消 → 撤回飞书实例（best-effort）──


async def cancel_approval(db: AsyncSession, req: HardwareRequisition) -> bool:
    """系统内取消领料单时撤回飞书待审实例（best-effort）。

    只对 feishu 通道且审批未决（approval_status 空/pending）的单生效；撤回
    失败（定义未开「允许撤销」/已审批）不阻断本地取消，只留备注。成功后
    approval_status 落 cancelled，轮询/事件不再把它当待审单。
    """
    from app.platform.integrations.feishu.approval import cancel_instance

    if getattr(req, "approval_channel", None) != "feishu":
        return False
    if str(getattr(req, "approval_status", "") or "") not in ("", "pending"):
        return False
    code = str(getattr(req, "approval_instance_code", "") or "")
    approval_code = str(getattr(get_settings(), "HARDWARE_APPROVAL_CODE", "") or "").strip()
    app_id, app_secret = FeishuApprovalChannel._credentials()
    if not (code and approval_code and app_id and app_secret):
        return False
    user_id = await _resolve_starter_user_id(db, req)
    if not user_id:
        return False
    ok = await cancel_instance(
        approval_code, code, user_id, app_id=app_id, app_secret=app_secret
    )
    req.approval_status = "cancelled"
    if not ok:
        req.approval_note = (
            (req.approval_note or "") + "；飞书实例撤回失败（可能已审批或定义未开撤销）"
        ).strip("；")
    await db.flush()
    return ok


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
