"""特殊作业报备查询与审批工具（agent-action-p2）。

query_special_operation_reports（只读，四角色）+ approve /
reject_special_operation_report（写，仅 safety_admin——部门负责人可能是
报备发起方，避免自审自发，spec 拍板②）。工具体不重写业务逻辑，直接调
SpecialOperationReportService；report_no / report_id 双态定位（resolve_pg_record
同款模式，用户口头引用报备编号即可）。
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

_STATUS_CN2EN = {
    "草稿": "draft", "draft": "draft",
    "审批中": "submitted", "已提交": "submitted", "submitted": "submitted",
    "已审批": "approved", "approved": "approved",
    "已驳回": "rejected", "rejected": "rejected",
}


def _norm_status(value: str) -> str | None:
    return _STATUS_CN2EN.get((value or "").strip()) if value else None


def _serialize_report(item: Any) -> dict[str, Any]:
    from app.modules.safety.service.special_operation_report import (
        OP_LEVEL_EN2CN,
        OP_TYPE_EN2CN,
        STATUS_EN2CN,
    )

    def _iso(v: Any) -> str | None:
        return v.isoformat() if v else None

    return {
        "id": str(item.id),
        "report_no": item.report_no,
        "operation_type": OP_TYPE_EN2CN.get(item.operation_type, item.operation_type),
        "operation_level": OP_LEVEL_EN2CN.get(
            item.operation_level, item.operation_level
        ),
        "department": item.department,
        "location": item.location,
        "work_description": item.work_description,
        "work_leader_name": item.work_leader_name,
        "applicant_name": item.applicant_name,
        "planned_start_time": _iso(item.planned_start_time),
        "planned_end_time": _iso(item.planned_end_time),
        "status": item.status,
        "display_status": STATUS_EN2CN.get(item.status, item.status),
        "is_critical": item.is_critical,
    }


async def query_special_operation_reports(
    ctx: RunContext[SafetyDeps],
    status: str = "",
    operation_type: str = "",
    department: str = "",
    keyword: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询特殊作业报备单列表（八大特殊作业报备，PG 库；审批前先查待审清单）。

    数据源为平台报备表（Web 表单提交的报备单），与特殊作业判定明细
    （query_special_op_records，Bitable 同步）不同源。

    典型用法：用户说「有哪些待审批的报备」「待审批的动火报备」「报备审批
    情况」时调用；查到报备编号（XZ-…）后可直接用于 approve/reject。

    Args:
        status: 状态（draft=草稿 / submitted=审批中 / approved=已审批 /
            rejected=已驳回；也接受对应中文）
        operation_type: 作业类型（hot_work/confined_space/height_work/
            temporary_electricity/blind_plate/excavation/lifting/
            road_breaking；也接受中文如「动火作业」）
        department: 报备部门
        keyword: 关键词（匹配报备编号/作业内容/作业地点）
        date_from: 计划开始日期起（YYYY-MM-DD）
        date_to: 计划结束日期止（YYYY-MM-DD）
        page: 页码（默认 1）
        page_size: 每页条数（默认 20）

    返回报备单列表：编号/作业类型/级别/部门/作业内容/负责人/计划时间/状态。
    """
    from app.modules.safety.service.special_operation_report import (
        OP_TYPE_CN2EN,
        SpecialOperationReportService,
    )

    status_en = _norm_status(status) if status else None
    if status and status_en is None:
        return {
            "success": False,
            "error": (
                f"未知 status={status!r}，可选：draft（草稿）/ submitted（审批中）/"
                "approved（已审批）/ rejected（已驳回）"
            ),
        }
    op_type_en = (
        OP_TYPE_CN2EN.get(operation_type.strip(), operation_type.strip())
        if operation_type else None
    )

    service = SpecialOperationReportService(ctx.deps.db)
    skip = (max(page, 1) - 1) * page_size
    items, total = await service.get_reports(
        skip, page_size,
        status=status_en, operation_type=op_type_en or None,
        department=department or None, keyword=keyword or None,
        date_from=date_from or None, date_to=date_to or None,
    )
    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_report(i) for i in items],
    }


async def _resolve_report(
    db: Any, report_ref: str,
) -> Any:
    """报备单双态定位：UUID → 按 id；其余 → 按报备编号（XZ-…）。"""
    from sqlalchemy import select

    from app.modules.safety.models import SpecialOperationReport
    from app.modules.safety.service.special_operation_report import (
        SpecialOperationReportService,
    )

    ref = (report_ref or "").strip()
    if not ref:
        return None
    try:
        rid = _uuid.UUID(ref)
    except ValueError:
        rid = None
    if rid is not None:
        return await SpecialOperationReportService(db).get_report(rid)
    result = await db.execute(
        select(SpecialOperationReport).where(
            SpecialOperationReport.report_no == ref,
            SpecialOperationReport.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def _load_submitted_report(db: Any, report_ref: str) -> tuple[Any, dict | None]:
    """审批/驳回共用守卫：双态定位 + 状态校验。

    Returns:
        (report, None)：定位成功且状态为 submitted，可执行流转。
        (None, error)：不存在或状态不允许（error 已含给用户的说明）。
    """
    from app.modules.safety.service.special_operation_report import STATUS_EN2CN

    report = await _resolve_report(db, report_ref)
    if report is None:
        return None, {
            "success": False,
            "error": f"报备单不存在：{report_ref}（可用报备编号 XZ-… 或 UUID）",
        }
    if report.status != "submitted":
        return None, {
            "success": False,
            "error": (
                f"报备 {report.report_no} 当前状态为"
                f"「{STATUS_EN2CN.get(report.status, report.status)}」，"
                "仅「审批中」的报备可以执行此操作"
            ),
        }
    return report, None


async def approve_special_operation_report(
    ctx: RunContext[SafetyDeps],
    report_id: str,
) -> dict[str, Any]:
    """审批通过特殊作业报备（已提交→已审批，仅安全管理员可用）。

    审批前建议先用 query_special_operation_reports 查看待审批清单，
    在确认卡中向用户复述报备编号/作业类型/部门/负责人后再执行。

    Args:
        report_id: 报备编号（XZ-…）或报备单 UUID（必填）

    返回状态流转结果；非「审批中」状态的报备会被拒绝并说明原因。
    注意：此操作会变更报备状态，需要用户确认后才执行。
    """
    from app.modules.safety.service.special_operation_report import (
        STATUS_EN2CN,
        SpecialOperationReportService,
    )

    report, error = await _load_submitted_report(ctx.deps.db, report_id)
    if error is not None:
        return error
    item = await SpecialOperationReportService(ctx.deps.db).approve_report(
        report.id,
    )
    await ctx.deps.db.commit()
    if item is None:
        return {"success": False, "error": "审批失败，请重试"}
    return {
        "success": True,
        "action": "special_operation_report_approved",
        "report_no": item.report_no,
        "status": STATUS_EN2CN.get(item.status, item.status),
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
        "message": f"报备 {item.report_no} 已审批通过",
    }


async def reject_special_operation_report(
    ctx: RunContext[SafetyDeps],
    report_id: str,
    reason: str,
) -> dict[str, Any]:
    """驳回报备（已提交→已驳回，仅安全管理员可用；驳回原因必填）。

    驳回原因会写回报备单，报备部门据此修改后重新提交。

    Args:
        report_id: 报备编号（XZ-…）或报备单 UUID（必填）
        reason: 驳回原因（必填，如「安全措施不完整，需补充动火分析」）

    返回状态流转结果；非「审批中」状态的报备会被拒绝并说明原因。
    注意：此操作会变更报备状态，需要用户确认后才执行。
    """
    from app.modules.safety.service.special_operation_report import (
        STATUS_EN2CN,
        SpecialOperationReportService,
    )

    if not (reason or "").strip():
        return {"success": False, "error": "驳回必须填写原因（reason）"}
    report, error = await _load_submitted_report(ctx.deps.db, report_id)
    if error is not None:
        return error
    item = await SpecialOperationReportService(ctx.deps.db).reject_report(
        report.id, reason.strip(),
    )
    await ctx.deps.db.commit()
    if item is None:
        return {"success": False, "error": "驳回失败，请重试"}
    return {
        "success": True,
        "action": "special_operation_report_rejected",
        "report_no": item.report_no,
        "status": STATUS_EN2CN.get(item.status, item.status),
        "rejection_reason": item.rejection_reason,
        "message": f"报备 {item.report_no} 已驳回：{item.rejection_reason}",
    }


__all__ = [
    "query_special_operation_reports",
    "approve_special_operation_report",
    "reject_special_operation_report",
]
