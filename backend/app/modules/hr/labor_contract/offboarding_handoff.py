"""「转入离职办理」衔接：合同到期未续签 / 部门不同意续签 → 为员工建离职办理单。

建单走离职管理的现成服务（offboarding.service.create_case）：「员工已是离职状态则拒绝」
「已有进行中办理单则 409」等校验由它负责，这里原样抛出、不重复实现。建单后把合同关联到
办理单的离职记录；合同尚未终止的置 terminated——离职办理一发起，合同即归入离职台账、
退出在职台账，不再参与到期预警。
"""

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.models import LaborContract

logger = logging.getLogger(__name__)

# 转入后写在被终止合同上的原因（已终止的合同不改写原原因）
TRANSFER_TERMINATED_REASON = "合同到期未续签，转入离职办理"
REASON_UNRENEWED = "劳动合同到期未续签"
REASON_REFUSED = "劳动合同到期，部门不同意续签"


def default_offboarding_date(contract: LaborContract, *, today: date) -> date:
    """未指定离职日期：合同到期日在今天及以后用到期日，否则用今天。"""
    if contract.end_date is not None and contract.end_date >= today:
        return contract.end_date
    return today


def default_reason(contract: LaborContract) -> str:
    """未指定离职原因：部门已登记不同意按「部门不同意续签」，其余按「到期未续签」。"""
    if contract.dept_decision == LaborContract.DECISION_DISAGREE:
        return REASON_REFUSED
    return REASON_UNRENEWED


def handoff_remark(contract: LaborContract) -> str:
    end = contract.end_date.isoformat() if contract.end_date else "无固定期限"
    return f"由劳动合同管理转入（合同 {contract.start_date.isoformat()}~{end}）"


def case_brief(case: Any) -> dict[str, Any]:
    """办理单精简视图：前端据此跳转离职办理页（完整结构见离职管理自己的 Out schema）。"""
    return {
        "id": str(case.id),
        "case_no": case.case_no,
        "status": case.status,
        "status_label": case.status_label,
        "offboarding_date": case.offboarding_date.isoformat(),
        "offboarding_type": case.offboarding_type,
    }


async def transfer_to_offboarding(
    db: AsyncSession, contract: LaborContract, *,
    offboarding_date: date | None, reason: str | None,
    user_id: UUID | None = None, initiator_name: str | None = None,
) -> dict[str, Any]:
    """为合同对应员工创建离职办理单（类型「合同到期」）并衔接合同状态。

    返回新办理单的精简视图。create_case 自带的校验（员工已离职 / 已有进行中办理单）
    原样抛出，由接口层转成 400 / 409。
    """
    # 懒导入：离职管理的模型与服务在演进中，避免本模块导入期就绑定其内部结构
    from app.modules.hr.offboarding import service as offboarding_service
    from app.modules.hr.offboarding.models import OffboardingCase

    employee = await repo.get_employee(db, contract.employee_number)
    if employee is None:
        raise NotFoundException("员工档案", f"工号 {contract.employee_number}")

    case = await offboarding_service.create_case(
        db,
        employee_id=employee.id,
        offboarding_date=offboarding_date or default_offboarding_date(
            contract, today=date.today(),
        ),
        offboarding_type=OffboardingCase.TYPE_CONTRACT_END,
        reason=(reason or "").strip() or default_reason(contract),
        remark=handoff_remark(contract),
        user_id=user_id,
        initiator_name=initiator_name,
    )
    if case.departure_record_id is not None:
        contract.departure_record_id = case.departure_record_id
    if contract.status != LaborContract.STATUS_TERMINATED:
        contract.status = LaborContract.STATUS_TERMINATED
        contract.terminated_reason = TRANSFER_TERMINATED_REASON
        contract.terminated_at = datetime.now(UTC)
    contract.updated_by = user_id
    await db.flush()
    logger.info(
        "劳动合同转入离职办理: %s 第%d份 → 办理单 %s",
        contract.employee_number, contract.seq_no, case.case_no,
    )
    return case_brief(case)
