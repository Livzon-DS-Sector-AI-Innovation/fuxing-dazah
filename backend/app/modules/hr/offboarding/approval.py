"""离职审批编排：飞书原生审批自动发起 + 定时轮询回写（照 renewal_approval 模式）。

流程（方案 §3.3）：
    发起离职审批 → create_instance（表单按定义控件名自动填充，uuid 幂等，
    自选审批人节点 = 部门负责人 open_id）→ 办结（APPROVED）自动进入清退交接
    → 清退实例同样发起 → 会签办结（APPROVED）→ 回读清退明细 → cert_issuing 待开具证明。

回写口径按环节区分：
- 离职审批 REJECTED → 取消（canceled）；CANCELED/DELETED（发起人撤销）→ 清实例回 draft 可重发
- 清退会签 REJECTED / CANCELED / DELETED → 清实例、留在 clearing——离职审批早已通过，
  会签被退回只该停下等处理，不能把整张离职单作废；之后由 HR 站内登记办结

降级：四个审批定义编码（按职级分轨）任一未配置/不可用时，对应环节降级
「站内登记办结」（HR 在办理抽屉手动推进），流程不堵死；未配置是设计内路径，
不按失败报警，只有「配置了但发起失败」才通知 HR。
定义加载复用 labor_contract.renewal_approval.load_definition（按编码缓存）。
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract.renewal_approval import load_definition
from app.modules.hr.models import HrDepartment as Department
from app.modules.hr.offboarding import clearance, notify
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding import settings as offboarding_settings
from app.modules.hr.offboarding.models import OffboardingCase
from app.modules.hr.offboarding.service.common import notify_context
from app.modules.hr.title_review.notify import _lookup_open_id
from app.platform.integrations.feishu.approval import (
    ApprovalAPIError,
    create_instance,
    form_widgets_to_fields,
    get_instance,
    list_instance_codes,
)

logger = logging.getLogger(__name__)

_RECOVERY_MARK_PREFIX = "ob:"
STAGE_RESIGNATION = "resignation"
STAGE_CLEARANCE = "clearance"

# 审批定义表单控件约定（人事按名称创建，缺失的控件自动跳过不填）
RESIGN_WIDGET_SPECS: dict[str, str] = {
    "姓名": "name",
    "工号": "employee_number",
    "部门": "department",
    "岗位": "position",
    "职级": "level",
    "离职日期": "offboarding_date",
    "离职类型": "offboarding_type",
    "离职原因": "reason",
    "备注": "remark",
}
CLEARANCE_WIDGET_SPECS: dict[str, str] = {
    "姓名": "name",
    "工号": "employee_number",
    "部门": "department",
    "岗位": "position",
    "离职日期": "offboarding_date",
    "备注": "remark",
}


@dataclass(slots=True)
class InitiateResult:
    """发起结果。unconfigured=True 表示定义编码未配置（设计内的降级路径，不算失败）。"""

    ok: bool
    reason: str = ""
    unconfigured: bool = False


async def resolve_approver_open_id(db: AsyncSession, case: OffboardingCase) -> str | None:
    """部门负责人 open_id：部门表负责人姓名 → identity 解析；兜底员工直属经理。"""
    manager_name = (await db.execute(
        select(Department.department_manager_name)
        .where(Department.name == case.department, Department.is_deleted.is_(False))
    )).scalar_one_or_none()
    if not manager_name:
        employee = await repo.get_employee(db, case.employee_id)
        manager_name = getattr(employee, "direct_manager_name", None) if employee else None
    if not manager_name:
        return None
    return await _lookup_open_id(manager_name)


def _build_values(case: OffboardingCase, *, stage: str) -> dict[str, str]:
    values = {
        "name": case.name,
        "employee_number": case.employee_number,
        "department": case.department,
        "position": case.position or "-",
        "level": case.level or "-",
        "offboarding_date": case.offboarding_date.isoformat(),
        "offboarding_type": case.offboarding_type,
        "reason": case.reason or "-",
    }
    # 备注尾部带恢复标记：uuid 冲突（创建成功但保存前崩溃的窗口）后按标记找回实例
    values["remark"] = f"系统自动发起（离职管理） {_RECOVERY_MARK_PREFIX}{case.id} {stage}"
    return values


def build_form(detail: dict[str, Any], values: dict[str, str],
               specs: dict[str, str]) -> list[dict[str, Any]]:
    """定义控件 × 值 → 创建实例的 form 数组；定义里没有的控件跳过。"""
    form: list[dict[str, Any]] = []
    for widget in detail.get("form", []):
        if not isinstance(widget, dict):
            continue
        key = specs.get(widget.get("name") or "")
        if not key or key not in values:
            continue
        form.append({
            "id": widget.get("id"),
            "type": widget.get("type") or "input",
            "value": values[key],
        })
    return form


async def initiate_resignation(
    db: AsyncSession, case: OffboardingCase, *, operator_open_id: str | None = None,
) -> InitiateResult:
    return await _initiate(
        db, case, stage=STAGE_RESIGNATION, operator_open_id=operator_open_id,
    )


async def initiate_clearance(
    db: AsyncSession, case: OffboardingCase, *, operator_open_id: str | None = None,
) -> InitiateResult:
    return await _initiate(
        db, case, stage=STAGE_CLEARANCE, operator_open_id=operator_open_id,
    )


async def _initiate(
    db: AsyncSession, case: OffboardingCase, *, stage: str, operator_open_id: str | None,
) -> InitiateResult:
    """为办结单发起某阶段的原生审批。成功时已写实例码。"""
    kv = await offboarding_settings.load_offboarding_settings(db)
    track = case.approval_track or offboarding_settings.resolve_track(kv, case.level)
    approval_code = offboarding_settings.approval_code_for(kv, track=track, stage=stage)
    if not approval_code:
        return InitiateResult(False, "未配置审批定义编码（系统配置 → 离职管理）", unconfigured=True)

    detail = await load_definition(approval_code)
    if not detail:
        return InitiateResult(False, "审批定义不可用（未创建/已停用）")

    approver_open_id = await resolve_approver_open_id(db, case)
    if not approver_open_id:
        return InitiateResult(False, "部门负责人无法解析（部门表/员工档案均无负责人）")

    specs = RESIGN_WIDGET_SPECS if stage == STAGE_RESIGNATION else CLEARANCE_WIDGET_SPECS
    form = build_form(detail, _build_values(case, stage=stage), specs)
    if not form:
        return InitiateResult(False, "审批定义表单无可映射控件（请按控件名约定创建定义）")

    node_id = next((
        n.get("node_id") for n in detail.get("node_list", [])
        if isinstance(n, dict) and n.get("need_approver")
    ), None)
    if not node_id:
        return InitiateResult(False, "审批定义流程未设置「发起人自选审批人」节点")

    # 发起人依次取：员工本人 → 点「发起」的 HR → 部门负责人。前两者都没有时才会
    # 落到「发起人 = 审批人」，飞书对同人会自动通过，所以只作最后兜底
    employee = await repo.get_employee(db, case.employee_id)
    initiator = (
        (getattr(employee, "feishu_open_id", None) if employee else None)
        or operator_open_id
        or approver_open_id
    )
    case.approval_attempt = (case.approval_attempt or 0) + 1
    await db.flush()

    try:
        instance_code = await create_instance(
            approval_code,
            initiator_open_id=initiator,
            form=json.dumps(form, ensure_ascii=False, separators=(",", ":")),
            node_approver_open_id_list=[{"key": node_id, "value": [approver_open_id]}],
            uuid=f"ob-{stage}-{case.id}-{case.approval_attempt}",
        )
    except ApprovalAPIError as exc:
        recovered = await _recover_instance_code(approval_code, case, stage)
        if recovered:
            logger.info("审批实例幂等冲突后找回: case=%s stage=%s → %s", case.id, stage, recovered)
            _store_instance_code(case, stage, recovered)
            return InitiateResult(True)
        return InitiateResult(False, f"创建审批实例失败: {exc}")

    _store_instance_code(case, stage, instance_code)
    await db.flush()
    return InitiateResult(True)


def _store_instance_code(case: OffboardingCase, stage: str, code: str | None) -> None:
    if stage == STAGE_RESIGNATION:
        case.resignation_instance_code = code
    else:
        case.clearance_instance_code = code


async def _recover_instance_code(
    approval_code: str, case: OffboardingCase, stage: str,
) -> str | None:
    """uuid 冲突（创建成功但保存前崩溃的窗口）→ 按 7 天内实例找回落库 mark。"""
    try:
        now_ms = int(time.time() * 1000)
        codes = await list_instance_codes(approval_code, now_ms - 7 * 24 * 3600 * 1000, now_ms)
    except ApprovalAPIError:
        return None
    mark = f"{_RECOVERY_MARK_PREFIX}{case.id} {stage}"
    for code in codes[-50:]:
        try:
            instance = await get_instance(code)
        except ApprovalAPIError:
            continue
        fields = form_widgets_to_fields(instance.get("form", []))
        if str(fields.get("备注") or "").find(mark) >= 0:
            return code
    return None


# ─── 结果回写（轮询，幂等）───

_STATUS_HANDLED = ("APPROVED", "REJECTED", "CANCELED", "DELETED")


def _now() -> datetime:
    return datetime.now(UTC)


def _append_remark(case: OffboardingCase, text: str) -> None:
    """备注追加（不覆盖建单时的备注），超长截断到列宽。"""
    case.remark = "；".join(filter(None, [case.remark, text]))[-512:]


async def sync_pending_results(db: AsyncSession) -> dict[str, int]:
    """轮询回写离职审批/清退会签实例结果，办结自动推进状态机。返回 {handled: 计数}。

    每张单包在 SAVEPOINT 里：单条异常只回滚该条（不留改了一半的状态，会话也不会
    进入失败态拖垮后面的单），记日志下一轮重试。本函数不 commit。
    """
    counts: dict[str, int] = {}
    for case in await repo.list_pending_approval_sync(db):
        try:
            async with db.begin_nested():
                if case.status == OffboardingCase.STATUS_APPROVING and case.resignation_instance_code:
                    handled = await _sync_resignation(db, case)
                elif case.status == OffboardingCase.STATUS_CLEARING and case.clearance_instance_code:
                    handled = await _sync_clearance(db, case)
                else:
                    continue
        except Exception as exc:  # 单条失败不影响其余
            logger.warning("离职审批回写失败: case=%s → %s", case.id, exc)
            continue
        if handled:
            counts[handled] = counts.get(handled, 0) + 1
    return counts


async def _fetch_instance(instance_code: str | None) -> dict[str, Any] | None:
    """拉取实例；拉取失败或尚未办结（PENDING）返回 None，下一轮再看。"""
    if not instance_code:
        return None
    try:
        instance = await get_instance(instance_code)
    except ApprovalAPIError as exc:
        logger.warning("拉取离职审批实例失败: %s → %s", instance_code, exc)
        return None
    return instance if instance.get("status") in _STATUS_HANDLED else None


async def _sync_resignation(db: AsyncSession, case: OffboardingCase) -> str | None:
    instance = await _fetch_instance(case.resignation_instance_code)
    if not instance:
        return None
    status = instance["status"]
    if status == "APPROVED":
        case.resignation_finished_at = _now()
        case.status = OffboardingCase.STATUS_CLEARING
        await db.flush()
        await clearance.seed_default_items(db, case)
        # 离职审批办结后自动发起清退交接（下一环节仍优先飞书）
        result = await _initiate(db, case, stage=STAGE_CLEARANCE, operator_open_id=None)
        if result.ok:
            note = "离职审批已通过，清退交接飞书审批已自动发起"
        elif result.unconfigured:
            note = "离职审批已通过；清退交接未接飞书审批，请在平台登记各部门清退情况"
        else:
            note = f"离职审批已通过；清退交接飞书审批发起失败（{result.reason}），请在平台登记清退情况"
        logger.info("离职审批通过: %s(%s) → 进入清退会签", case.name, case.case_no)
        await notify.notify_stage_advanced(db, case, await notify_context(db), note=note)
        return "resignation_approved"

    if status == "REJECTED":
        case.status = OffboardingCase.STATUS_CANCELED
        _append_remark(case, "离职审批未通过（飞书审批不同意），办理已取消")
        logger.info("离职审批不同意: %s(%s) → 取消", case.name, case.case_no)
        await notify.notify_stage_advanced(
            db, case, await notify_context(db), note="离职审批未通过（飞书审批不同意），办理已取消",
        )
        return "resignation_rejected"

    # CANCELED / DELETED：审批被撤销，清实例回 draft 可重新发起
    case.resignation_instance_code = None
    case.status = OffboardingCase.STATUS_DRAFT
    _append_remark(case, "离职审批在飞书被撤销，已退回待发起")
    logger.info("离职审批实例被撤销: %s(%s) → 回待发起", case.name, case.case_no)
    await notify.notify_stage_advanced(
        db, case, await notify_context(db), note="离职审批在飞书被撤销，已退回「待发起审批」",
    )
    return "resignation_canceled"


async def _sync_clearance(db: AsyncSession, case: OffboardingCase) -> str | None:
    instance = await _fetch_instance(case.clearance_instance_code)
    if not instance:
        return None
    status = instance["status"]
    if status == "APPROVED":
        case.clearance_finished_at = _now()
        case.status = OffboardingCase.STATUS_CERT_ISSUING
        await db.flush()
        imported = 0
        try:
            imported = await clearance.import_from_instance(
                db, case, form_widgets_to_fields(instance.get("form", [])),
            )
        except Exception as exc:  # 表单回读脆弱（依赖人事建控件），失败不堵流程
            logger.warning("清退明细回读失败: case=%s → %s", case.id, exc)
        note = f"清退会签已办结，回读清退明细 {imported} 条，请核对开具证明" if imported else (
            "清退会签已办结，请核对开具证明"
        )
        logger.info("清退会签办结: %s(%s) → 待开具证明", case.name, case.case_no)
        await notify.notify_stage_advanced(db, case, await notify_context(db), note=note)
        return "clearance_approved"

    # REJECTED / CANCELED / DELETED：清掉实例、留在清退阶段，由 HR 处理后站内登记办结
    reason = {
        "REJECTED": "清退交接飞书审批被退回，请各部门处理后在平台登记清退情况",
        "CANCELED": "清退交接飞书审批被撤销，请在平台登记清退办结",
        "DELETED": "清退交接飞书审批被删除，请在平台登记清退办结",
    }[status]
    case.clearance_instance_code = None
    _append_remark(case, reason)
    logger.info("清退会签实例 %s: %s(%s) → 留在清退阶段", status, case.name, case.case_no)
    await notify.notify_stage_advanced(db, case, await notify_context(db), note=reason)
    return f"clearance_{status.lower()}"
