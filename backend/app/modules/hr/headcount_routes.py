"""编制数（部门定编）查询接口。

数据由员工档案同步顺带拉取（同一 Base 的定编数表 → hr.headcount_plans）；
现有人数/缺编不用飞书手填值，按 hr.employees 实时统计（口径：未离职）。
"""

import re
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, get_hr_scope, require_hr_access
from app.modules.hr.models import Employee, HeadcountPlan

router = APIRouter(prefix="/headcount", tags=["HR-编制数"])

# 在编口径：排除离职人员（在职/试用期/病假/产假等均计入）
_DEPARTED = "离职"

# 「岗位×N」解析：支持 ×/x/X/* 与全/半角分号，岗位名可含空格与括号
_POSITION_SPLIT = re.compile(r"[;；]")
_POSITION_ITEM = re.compile(r"^(.+?)[×xX*](\d+)$")


def _parse_positions(detail: str) -> list[dict[str, Any]]:
    """岗位明细原文 → [{name, count}]（无法解析的片段原样保留、count=None）。"""
    items: list[dict[str, Any]] = []
    for raw in _POSITION_SPLIT.split(detail or ""):
        name = raw.strip()
        if not name:
            continue
        matched = _POSITION_ITEM.match(name)
        if matched:
            items.append({"name": matched.group(1).strip(), "count": int(matched.group(2))})
        else:
            items.append({"name": name, "count": None})
    return items


def _normalize_department(name: str) -> str:
    """部门名归一：去首尾/内部空白（含全角）、全角括号→半角、统一小写。

    定编表与员工表的部门写法可能有细节差异（如「质量保证部（QA部）」
    vs「质量保证部(QA部)」），精确不匹配时用归一形式兜底。
    """
    text = (name or "").strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    return text.lower()


async def _collect_plans(session: AsyncSession, hr_scope: HrAccessContext) -> dict[str, Any]:
    """定编 + 在编实时统计组装（列表与导出共用）。

    - 在编 = 未软删且状态非「离职」的员工，按体现部门（department）分组；
    - 部门匹配：精确 → 归一化兜底（全半角/空白差异），仍未匹配的标
      matched=false 供前端提示核对名称；
    - 受数据范围限制的用户只看得到授权部门（与员工档案口径一致）。
    """
    plans = (await session.execute(
        select(HeadcountPlan)
        .where(HeadcountPlan.is_deleted.is_(False))
        .order_by(HeadcountPlan.sort_order, HeadcountPlan.department)
    )).scalars().all()

    # 在编统计 + 全量部门名（含「只剩离职员工」的部门，用于 matched 判断）
    active_rows = (await session.execute(
        select(Employee.department, func.count(Employee.id))
        .where(
            Employee.is_deleted.is_(False),
            Employee.status != _DEPARTED,
        )
        .group_by(Employee.department)
    )).all()
    active_counts = {dept: int(cnt) for dept, cnt in active_rows}

    all_departments = {
        str(row[0])
        for row in (await session.execute(
            select(Employee.department).where(
                Employee.is_deleted.is_(False),
                Employee.department.is_not(None),
            ).distinct()
        )).all()
        if row[0]
    }
    # 归一化兜底索引：归一名 → 任一实际写法的在编数合计
    normalized_active: dict[str, int] = {}
    normalized_known: set[str] = set()
    for dept in all_departments:
        normalized_known.add(_normalize_department(dept))
    for dept, cnt in active_counts.items():
        normalized_active[_normalize_department(dept)] = (
            normalized_active.get(_normalize_department(dept), 0) + cnt
        )

    scoped = None
    if not hr_scope.is_unrestricted and hr_scope.data_scope != "self_only":
        scoped = set(hr_scope.scoped_departments)

    rows: list[dict[str, Any]] = []
    total_quota = total_actual = 0
    unmatched: list[str] = []
    for plan in plans:
        if scoped is not None and plan.department not in scoped:
            continue
        exact = plan.department in all_departments
        norm_key = _normalize_department(plan.department)
        matched = exact or norm_key in normalized_known
        # 部门存在但全员离职时不在 active_counts 里，缺省 0
        actual_count = (
            active_counts.get(plan.department, 0)
            if exact
            else normalized_active.get(norm_key, 0)
        )
        vacancy = plan.department_quota - actual_count
        total_quota += plan.department_quota
        total_actual += actual_count
        if not matched:
            unmatched.append(plan.department)
        rows.append({
            "department": plan.department,
            "department_quota": plan.department_quota,
            "actual_count": actual_count,
            "source_current_count": plan.source_current_count,
            "vacancy": vacancy,
            "position_detail": plan.position_detail,
            "positions": _parse_positions(plan.position_detail),
            "sort_order": plan.sort_order,
            "matched": matched,
            "feishu_synced_at": (
                plan.feishu_synced_at.isoformat() if plan.feishu_synced_at else None
            ),
        })

    return {
        "plans": rows,
        "summary": {
            "total_quota": total_quota,
            "total_actual": total_actual,
            "total_vacancy": total_quota - total_actual,
            "achievement_rate": (
                round(total_actual / total_quota * 100, 1) if total_quota else 0.0
            ),
            "department_count": len(rows),
            "unmatched_departments": unmatched,
        },
    }


@router.get("/plans", summary="部门定编一览（在编实时统计 + 缺编 + 岗位明细）")
async def list_headcount_plans(
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
    _perm: HrAccessContext = Depends(require_hr_access("hr:profile:read")),
) -> JSONResponse:
    return success_response(data=await _collect_plans(session, hr_scope))


@router.get("/plans/export", summary="导出编制对账（Excel）")
async def export_headcount_plans(
    keyword: str | None = None,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
    _perm: HrAccessContext = Depends(require_hr_access("hr:profile:read")),
):
    """导出编制对账为 Excel：数据范围与列表一致，keyword 按部门模糊过滤（与前端搜索框同口径），末行合计。"""
    from datetime import date

    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app.modules.hr.xlsx_utils import write_sheet, xlsx_response

    data = await _collect_plans(session, hr_scope)
    plans = data["plans"]
    if keyword:
        kw = keyword.strip()
        plans = [p for p in plans if kw in (p["department"] or "")]

    rows = [[
        p["department"], p["department_quota"], p["actual_count"],
        p["source_current_count"], p["vacancy"], p["position_detail"],
        p["feishu_synced_at"],
    ] for p in plans]

    # 合计按（过滤后）实际导出的行累计，keyword 过滤时不等于全量 summary
    total_quota = sum(p["department_quota"] for p in plans)
    total_actual = sum(p["actual_count"] for p in plans)

    wb = Workbook()
    ws = wb.active
    ws.title = "编制对账"
    write_sheet(
        ws,
        ["部门", "定编人数", "实际在编", "飞书表现有人数", "缺口", "岗位明细", "飞书同步时间"],
        rows,
    )
    # 末行合计（加粗）
    total_row_idx = len(rows) + 2
    totals = ["合计", total_quota, total_actual, "", total_quota - total_actual, "", ""]
    for col_idx, val in enumerate(totals, 1):
        cell = ws.cell(row=total_row_idx, column=col_idx, value="" if val is None else str(val))
        cell.font = Font(bold=True)
    return xlsx_response(wb, f"编制对账_{date.today().isoformat()}.xlsx")
