"""部门续签审批 · 飞书原生审批：自动发起实例 + 定时轮询回写结果。

流程（方案 §3.4）：
    扫描进入公告期 → create_instance（表单按定义控件名自动填充，
    自选审批人节点 = 部门负责人 open_id，uuid 幂等）→ 部门负责人在飞书
    审批 → 轮询 get_instance 回写：APPROVED → 同意（续签办理中+通知员工）/
    REJECTED → 不同意（终止转离职）/ CANCELED → 清空实例回站内待审批。

依赖前置：人事在飞书审批后台创建「劳动合同续签审批」定义（表单控件按
下方 WIDGET_SPECS 命名，流程节点设「发起人自选审批人」），定义编码配置到
hr_contract.renewal_approval_code；未配置时由调用方降级站内勾选审批。

结果回写走轮询（沿用职称评审拉取模式，不新增事件订阅基础设施），
以 status==pending_renewal 且已存 instance_code 的行里取增量，天然幂等。
"""

import json
import logging
import time
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract import service as contract_service
from app.modules.hr.labor_contract import settings as contract_settings
from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.models import HrDepartment as Department
from app.modules.hr.title_review.notify import _lookup_open_id
from app.platform.integrations.feishu.approval import (
    ApprovalAPIError,
    create_instance,
    form_widgets_to_fields,
    get_approval_detail,
    get_instance,
    list_instance_codes,
)

logger = logging.getLogger(__name__)

# 审批定义表单控件约定（人事按名称创建，缺失的控件自动跳过不填）
WIDGET_SPECS: dict[str, str] = {
    "姓名": "name",
    "工号": "employee_number",
    "部门": "department",
    "岗位": "position",
    "原合同到期日": "end_date",
    "本次签订类型": "next_term",
    "合同期限": "term_label",
    "合同起始日期": "next_start",
    "备注": "remark",
}

_RECOVERY_MARK_PREFIX = "lc:"

# 定义详情进程内缓存（控件 id 不常变，避免每次扫描都打定义接口）
_definition_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_DEFINITION_TTL_SECONDS = 600


async def load_definition(approval_code: str) -> dict[str, Any] | None:
    """取审批定义（10 分钟缓存）。不可用返回 None。"""
    now = time.monotonic()
    cached = _definition_cache.get(approval_code)
    if cached and now - cached[0] < _DEFINITION_TTL_SECONDS:
        return cached[1]
    try:
        detail = await get_approval_detail(approval_code)
    except ApprovalAPIError as exc:
        logger.warning("获取审批定义失败: %s → %s", approval_code, exc)
        return None
    if detail.get("status") != "ACTIVE":
        logger.warning("审批定义未启用: %s status=%s", approval_code, detail.get("status"))
        return None
    _definition_cache[approval_code] = (now, detail)
    return detail


async def resolve_approver_open_id(
    db: AsyncSession, contract: LaborContract
) -> str | None:
    """部门负责人 open_id：部门表负责人姓名 → identity 解析；兜底员工直属经理。"""
    manager_name = (await db.execute(
        select(Department.department_manager_name)
        .where(Department.name == contract.department, Department.is_deleted.is_(False))
    )).scalar_one_or_none()
    if not manager_name:
        employee = await repo.get_employee(db, contract.employee_number)
        manager_name = getattr(employee, "direct_manager_name", None)
    if not manager_name:
        return None
    return await _lookup_open_id(manager_name)


def _build_values(contract: LaborContract, *, next_start: date) -> dict[str, str]:
    """按控件名组装表单值（备注尾部带恢复标记，用于 60012 冲突后找回实例）。"""
    next_seq = contract.seq_no + 1
    return {
        "name": contract.name,
        "employee_number": contract.employee_number,
        "department": contract.department,
        "position": contract.position or "-",
        "end_date": contract.end_date.isoformat() if contract.end_date else "无固定期限",
        "next_term": contract_service.next_term_preview(next_seq),
        "term_label": (
            LaborContract.TERM_LABELS[
                contract_service.term_for_seq(next_seq)[0]
            ]
        ),
        "next_start": next_start.isoformat(),
        "remark": (
            f"系统自动发起（劳动合同管理） {_RECOVERY_MARK_PREFIX}{contract.id}"
        ),
    }


def build_form(detail: dict[str, Any], values: dict[str, str]) -> list[dict[str, Any]]:
    """定义控件 × 值 → 创建实例的 form 数组；定义里没有的控件跳过。"""
    form: list[dict[str, Any]] = []
    for widget in detail.get("form", []):
        if not isinstance(widget, dict):
            continue
        name = widget.get("name") or ""
        key = WIDGET_SPECS.get(name)
        if not key or key not in values:
            continue
        form.append({
            "id": widget.get("id"),
            "type": widget.get("type") or "input",
            "value": values[key],
        })
    return form


async def initiate(
    db: AsyncSession, contract: LaborContract, *, next_start: date
) -> tuple[bool, str]:
    """为一份到期合同发起原生审批。成功时已写 instance_code 并返回 (True, "")。

    失败返回 (False, 原因)，由调用方降级站内勾选审批。
    """
    kv = await contract_settings.load_contract_settings(db)
    approval_code = contract_settings.approval_code(kv)
    if not approval_code:
        return False, "未配置审批定义编码"

    detail = await load_definition(approval_code)
    if not detail:
        return False, "审批定义不可用（未创建/已停用）"

    approver_open_id = await resolve_approver_open_id(db, contract)
    if not approver_open_id:
        return False, "部门负责人无法解析（部门表/员工档案均无负责人）"

    form = build_form(detail, _build_values(contract, next_start=next_start))
    if not form:
        return False, "审批定义表单无可映射控件（请按控件名约定创建定义）"

    node_id = next((
        n.get("node_id") for n in detail.get("node_list", [])
        if isinstance(n, dict) and n.get("need_approver")
    ), None)
    if not node_id:
        return False, "审批定义流程未设置「发起人自选审批人」节点"

    employee = await repo.get_employee(db, contract.employee_number)
    initiator = (getattr(employee, "feishu_open_id", None) if employee else None) or approver_open_id
    uuid = f"lc-renew-{contract.id}-{contract.approval_attempt or 0}"

    try:
        instance_code = await create_instance(
            approval_code,
            initiator_open_id=initiator,
            form=json.dumps(form, ensure_ascii=False, separators=(",", ":")),
            node_approver_open_id_list=[{"key": node_id, "value": [approver_open_id]}],
            uuid=uuid,
        )
    except ApprovalAPIError as exc:
        recovered = await _recover_instance_code(approval_code, contract)
        if recovered:
            logger.info("审批实例幂等冲突后找回: contract=%s → %s", contract.id, recovered)
            return True, recovered
        return False, f"创建审批实例失败: {exc}"

    return True, instance_code


async def _recover_instance_code(approval_code: str, contract: LaborContract) -> str | None:
    """uuid 冲突（创建成功但保存前崩溃的窗口）→ 按 7 天内实例找回落 mark。"""
    try:
        now_ms = int(time.time() * 1000)
        codes = await list_instance_codes(
            approval_code, now_ms - 7 * 24 * 3600 * 1000, now_ms
        )
    except ApprovalAPIError:
        return None
    mark = f"{_RECOVERY_MARK_PREFIX}{contract.id}"
    for code in codes[-50:]:
        try:
            instance = await get_instance(code)
        except ApprovalAPIError:
            continue
        fields = form_widgets_to_fields(instance.get("form", []))
        if str(fields.get("备注") or "").find(mark) >= 0:
            return code
    return None


# ─── 结果回写（轮询）───

_STATUS_HANDLED = ("APPROVED", "REJECTED", "CANCELED", "DELETED")


async def sync_pending_results(db: AsyncSession) -> dict[str, int]:
    """轮询回写公告期合同的原生审批结果。返回 {approved, rejected, canceled} 计数。"""
    pending = await repo.list_pending_approval_sync(db)
    counts = {"approved": 0, "rejected": 0, "canceled": 0}
    for contract in pending:
        instance_code = contract.approval_instance_code
        if not instance_code:
            continue
        try:
            instance = await get_instance(instance_code)
        except ApprovalAPIError as exc:
            logger.warning("拉取审批实例失败: %s → %s", contract.approval_instance_code, exc)
            continue
        status = instance.get("status")
        if status not in _STATUS_HANDLED:
            continue
        decided_by = "飞书审批"
        if status == "APPROVED":
            await contract_service.apply_dept_decision(
                db, contract,
                decision=LaborContract.DECISION_AGREE,
                decided_by=decided_by,
                send_notice=True,
            )
            counts["approved"] += 1
            logger.info("续签审批通过: %s 第%d份", contract.employee_number, contract.seq_no)
        elif status == "REJECTED":
            await contract_service.apply_dept_decision(
                db, contract,
                decision=LaborContract.DECISION_DISAGREE,
                decided_by=decided_by,
                send_notice=True,
            )
            counts["rejected"] += 1
            logger.info("续签审批拒绝: %s 第%d份，转终止", contract.employee_number, contract.seq_no)
        else:  # CANCELED / DELETED：清空实例回到站内待审批，由 HR 勾选或重新发起
            contract.approval_instance_code = None
            contract.approval_mode = LaborContract.APPROVAL_MANUAL
            counts["canceled"] += 1
            logger.info("续签审批实例被撤销: %s → 回站内待审批", contract.employee_number)
    if any(counts.values()):
        await db.flush()
    return counts
