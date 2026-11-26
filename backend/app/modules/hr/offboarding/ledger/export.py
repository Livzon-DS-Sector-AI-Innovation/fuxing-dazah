"""离职台账导出：字段注册表（勾选导出）+ Excel 工作簿 + 导出留痕（方案 §3.8）。

EXPORT_COLUMNS 是导出字段的唯一口径：导出弹窗的可勾选项、保存视图里存的字段 key、
导出留痕记录的 columns 都指向这里，按需求「离职人员台账」分五组。
身份证号沿用原导出的脱敏规则（全部屏蔽）。
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding.ledger import query
from app.modules.hr.offboarding.models import (
    HrExportLog,
    OffboardingCase,
    OffboardingClearanceItem,
)

logger = logging.getLogger(__name__)

EXPORT_MODULE = "departure"  # 导出留痕表（hr.export_logs）里的台账标识
EXPORT_MAX_ROWS = 100_000
_UNDONE_STATUSES = (
    OffboardingCase.STATUS_DRAFT, OffboardingCase.STATUS_APPROVING, OffboardingCase.STATUS_CLEARING,
    OffboardingCase.STATUS_CERT_ISSUING, OffboardingCase.STATUS_DELIVERING, OffboardingCase.STATUS_SIGNED,
)
_TEMPLATE_LABELS = {
    OffboardingCase.CERT_ELECTRONIC: "电子单张版",
    OffboardingCase.CERT_PAPER: "纸质两联版",
}


@dataclass(frozen=True, slots=True)
class ExportColumn:
    """一个可导出字段：key 全局唯一（视图 / 留痕存 key），label 是 Excel 表头。"""

    key: str
    label: str
    group: str
    getter: Callable[[dict[str, Any], dict[str, Any]], Any]


# ─── 取值辅助 ───

def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _dt(value: Any) -> str:
    """ISO 时间 → YYYY-MM-DD HH:MM。"""
    return _s(value)[:16].replace("T", " ")


def _joined(*values: Any) -> str:
    return " / ".join(str(v) for v in values if v)


def _list(value: Any) -> str:
    return "、".join(str(v) for v in value) if isinstance(value, list) else _s(value)


def _field(name: str) -> Callable[[dict[str, Any], dict[str, Any]], str]:
    return lambda row, _ctx: _s(row.get(name))


def _case_field(name: str) -> Callable[[dict[str, Any], dict[str, Any]], str]:
    def get(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
        case = row.get("_case")
        return _s(getattr(case, name, None)) if case is not None else ""
    return get


def _mask_id_card(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
    value = row.get("id_card") or ""
    return "*" * len(value)


def _entry_date(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
    return _s(row.get("livo_entry_date") or row.get("factory_entry_date"))


def _cert_signed_at(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
    return _dt(row.get("cert_signed_at"))


def _sign_channel(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
    if not row.get("cert_signed"):
        return ""
    return "线上手写签名" if row.get("has_sign_image") else "纸质当面签收"


def _cert_template(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
    case = row.get("_case")
    if case is None:
        return ""
    template: str | None = getattr(case, "cert_template", None)
    return _TEMPLATE_LABELS.get(template, "") if template else ""


def _cert_file(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
    case = row.get("_case")
    if case is None:
        return ""
    return "已归档" if getattr(case, "cert_storage_key", None) else "未归档"


def _approval_node(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
    return _s(row.get("approval_status_label")) if row.get("approval_status") else query.APPROVAL_NONE_LABEL


def _current_handler(row: dict[str, Any], ctx: dict[str, Any]) -> str:
    """当前处理人：按所处阶段给出该动手的人（未发起 / 已结束为空）。"""
    case = row.get("_case")
    if case is None or case.status not in _UNDONE_STATUSES:
        return ""
    if case.status == OffboardingCase.STATUS_APPROVING:
        return ctx["managers"].get(case.department) or "部门负责人"
    if case.status == OffboardingCase.STATUS_CLEARING:
        return "清退会签各部门"
    if case.status == OffboardingCase.STATUS_DRAFT:
        return case.initiator_name or "HR"
    return case.cert_issued_by or case.initiator_name or "人力资源部"


def _category_progress(category: str) -> Callable[[dict[str, Any], dict[str, Any]], str]:
    def get(row: dict[str, Any], _ctx: dict[str, Any]) -> str:
        bucket = (row.get("clearance") or {}).get(category) or {}
        return f"{bucket['done']}/{bucket['total']}" if bucket.get("total") else ""
    return get


def _category_amount(category: str, field_name: str) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
    def get(row: dict[str, Any], _ctx: dict[str, Any]) -> Any:
        bucket = (row.get("clearance") or {}).get(category) or {}
        value = bucket.get(field_name) or 0
        return value if value else ""
    return get


def _build_columns() -> list[ExportColumn]:
    columns = [
        # ─── 人员信息 ───
        ExportColumn("name", "姓名", "人员信息", _field("name")),
        ExportColumn("employee_number", "工号", "人员信息", _field("employee_number")),
        ExportColumn("id_card", "身份证号", "人员信息", _mask_id_card),
        ExportColumn("gender", "性别", "人员信息", _field("gender")),
        ExportColumn("education", "学历", "人员信息", _field("education")),
        ExportColumn("department", "部门", "人员信息", _field("department")),
        ExportColumn("team", "班组", "人员信息", _field("team")),
        ExportColumn("position", "岗位", "人员信息", _field("position")),
        ExportColumn("duty", "职务", "人员信息", _field("duty")),
        ExportColumn("rank", "职级", "人员信息", lambda row, _c: _joined(row.get("rank"), row.get("rank_category"))),
        ExportColumn("entry_date", "入职日期", "人员信息", _entry_date),
        ExportColumn("phone", "联系电话", "人员信息", _field("phone")),
        # ─── 离职信息 ───
        ExportColumn("offboarding_date", "离职日期", "离职信息", _field("offboarding_date")),
        ExportColumn("offboarding_type", "离职类型", "离职信息", _field("offboarding_type")),
        ExportColumn("offboarding_reason", "离职原因", "离职信息",
                     lambda row, _ctx: _list(row.get("offboarding_reason"))),
        ExportColumn("employee_category", "用工类型", "离职信息", _field("employee_category")),
        ExportColumn("application_submitted", "是否递交离职申请", "离职信息", _case_field("application_submitted")),
        ExportColumn("company_tenure_at_leave", "离职时司龄", "离职信息", _field("company_tenure_at_leave")),
        # ─── 证明信息 ───
        ExportColumn("cert_issued", "是否已开具证明", "证明信息", _field("cert_issued")),
        ExportColumn("cert_issued_at", "证明开具时间", "证明信息", lambda row, _c: _dt(row.get("cert_issued_at"))),
        ExportColumn("cert_issued_by", "HR 负责人", "证明信息", _case_field("cert_issued_by")),
        ExportColumn("cert_template", "证明模板", "证明信息", _cert_template),
        ExportColumn("cert_file", "证明附件", "证明信息", _cert_file),
        ExportColumn("cert_signed", "是否已签收", "证明信息", _field("cert_signed")),
        ExportColumn("cert_signed_at", "签收时间", "证明信息", _cert_signed_at),
        ExportColumn("cert_sign_name", "签收人", "证明信息", _field("cert_sign_name")),
        ExportColumn("cert_sign_channel", "签收方式", "证明信息", _sign_channel),
    ]
    # ─── 清退与结算：四部门各自的清退进度与扣补金额 ───
    for category, label in OffboardingClearanceItem.CATEGORY_LABELS.items():
        columns += [
            ExportColumn(f"{category}_progress", f"{label}清退进度", "清退与结算", _category_progress(category)),
            ExportColumn(f"{category}_deduction", f"{label}扣款", "清退与结算", _category_amount(category, "deduction")),
            ExportColumn(f"{category}_supplement", f"{label}补发", "清退与结算", _category_amount(category, "supplement")),
        ]
    columns += [
        # ─── 流程信息 ───
        ExportColumn("case_no", "申请编号", "流程信息", _case_field("case_no")),
        ExportColumn("initiator", "发起人", "流程信息", _case_field("initiator_name")),
        ExportColumn("init_department", "发起部门", "流程信息", _case_field("department")),
        ExportColumn("initiated_at", "发起时间", "流程信息", lambda row, _c: _dt(_case_value(row, "created_at"))),
        ExportColumn("approval_node", "审批节点", "流程信息", _approval_node),
        ExportColumn("current_handler", "当前处理人", "流程信息", _current_handler),
        ExportColumn("finished_at", "完成时间", "流程信息", lambda row, _c: _dt(_case_value(row, "closed_at"))),
    ]
    return columns


def _case_value(row: dict[str, Any], name: str) -> Any:
    case = row.get("_case")
    return getattr(case, name, None) if case is not None else None


EXPORT_COLUMNS: tuple[ExportColumn, ...] = tuple(_build_columns())
COLUMN_BY_KEY: dict[str, ExportColumn] = {column.key: column for column in EXPORT_COLUMNS}
# 导出弹窗的默认勾选：原导出的 16 列 + 办理状态 / 证明签收
DEFAULT_EXPORT_KEYS: tuple[str, ...] = (
    "name", "employee_number", "department", "position", "entry_date",
    "offboarding_date", "offboarding_type", "offboarding_reason", "employee_category",
    "company_tenure_at_leave", "education", "phone", "id_card",
    "approval_node", "cert_issued", "cert_signed",
)
assert len(COLUMN_BY_KEY) == len(EXPORT_COLUMNS), "导出字段 key 重复"


def resolve_columns(keys: Sequence[str]) -> list[ExportColumn]:
    """key → 字段（按传入顺序）；未知 key 直接拒绝，不让前端传什么就导什么。"""
    unknown = [key for key in keys if key not in COLUMN_BY_KEY]
    if unknown:
        raise AppException(message=f"未知的导出字段：{'、'.join(unknown)}", status_code=422)
    return [COLUMN_BY_KEY[key] for key in keys]


def column_catalog() -> list[dict[str, Any]]:
    """给导出弹窗的分组字段清单（顺序即 Excel 列序）。"""
    return [
        {"key": column.key, "label": column.label, "group": column.group}
        for column in EXPORT_COLUMNS
    ]


def _display_width(text: str) -> int:
    """列宽估算：中日韩字符按 2 个字符宽计。"""
    return sum(2 if ord(char) > 0x2E7F else 1 for char in text)


def _write_table(ws: Worksheet, headers: list[str], body: list[list[Any]]) -> None:
    """表头加粗居中，观感同 xlsx_utils.write_sheet，但数值保持数值。

    不直接用 write_sheet：它把所有单元格 str()，扣补金额会变成文本，Excel 里没法求和。
    """
    from openpyxl.styles import Alignment, Font

    for idx, label in enumerate(headers, 1):
        cell = ws.cell(row=1, column=idx, value=label)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for row_idx, row in enumerate(body, 2):
        for col_idx, value in enumerate(row, 1):
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            ws.cell(row=row_idx, column=col_idx, value=value if is_number else _s(value))


def build_workbook(
    rows: Sequence[dict[str, Any]], columns: Sequence[ExportColumn], context: dict[str, Any],
) -> Workbook:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "离职台账"
    body = [[column.getter(row, context) for column in columns] for row in rows]
    _write_table(ws, [column.label for column in columns], body)
    for idx, column in enumerate(columns, 1):
        # 列宽：表头与前 200 行内容取最宽，夹在 10~40 之间
        width = max(
            [len(column.label) * 2]
            + [_display_width(str(row[idx - 1])) for row in body[:200]]
        )
        ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 10), 40)
    return wb


async def export_ledger(
    db: AsyncSession,
    filters: dict[str, Any],
    column_keys: Sequence[str],
    *,
    scoped: set[str] | None,
    operator_id: Any,
    operator_name: str | None,
    sort_by: str = "offboarding_date",
    sort_order: str = "desc",
) -> tuple[Workbook, int, list[str]]:
    """按筛选 + 勾选字段导出，并写一条导出留痕（操作人 / 时间 / 条件 / 字段 / 条数）。

    返回 (工作簿, 导出条数, 表头)；导出与列表同一筛选口径、不分页。
    """
    columns = resolve_columns(column_keys)
    rows, _total = await query.query(
        db, filters, scoped=scoped, sort_by=sort_by, sort_order=sort_order,
        limit=EXPORT_MAX_ROWS, with_case=True,
    )
    managers = await repo.department_manager_map(db, {
        row["_case"].department for row in rows if row.get("_case") is not None
    })
    workbook = build_workbook(rows, columns, {"managers": managers})
    await repo.add_export_log(
        db, module=EXPORT_MODULE, operator_id=operator_id, operator_name=operator_name,
        filters={key: value for key, value in filters.items() if value not in (None, "")},
        columns=[column.key for column in columns], row_count=len(rows),
    )
    await db.commit()
    logger.info("离职台账导出: %s 行，%d 个字段", len(rows), len(columns))
    return workbook, len(rows), [column.label for column in columns]


def export_log_dict(log: HrExportLog) -> dict[str, Any]:
    """导出留痕 → 接口行（筛选条件还原成中文，便于直接看）。"""
    filters = log.filters if isinstance(log.filters, dict) else {}
    created: datetime | None = log.created_at
    return {
        "id": str(log.id),
        "operator_name": log.operator_name or "-",
        "created_at": created.isoformat() if created else None,
        "filters": {
            _FILTER_LABELS.get(key, key): _display_filter(key, value) for key, value in filters.items()
        },
        "columns": [
            COLUMN_BY_KEY[key].label if key in COLUMN_BY_KEY else str(key)
            for key in (log.columns if isinstance(log.columns, list) else [])
        ],
        "row_count": log.row_count,
    }


def _display_filter(key: str, value: Any) -> Any:
    """留痕里存的是原始筛选值；给人看时把状态码转成文案（closed → 已办结）。"""
    if key == "approval_status" and isinstance(value, str):
        if value == "none":
            return "未发起"
        return OffboardingCase.STATUS_LABELS.get(value, value)
    return value


_FILTER_LABELS = {
    "keyword": "关键词", "department": "部门", "position": "岗位",
    "offboarding_type": "离职类型", "offboarding_reason": "离职原因", "gender": "性别",
    "education": "学历", "employee_category": "用工类型",
    "offboarding_date_from": "离职日期起", "offboarding_date_to": "离职日期止",
    "approval_status": "办理状态", "cert_issued": "是否已开证明", "cert_signed": "是否已领取",
}


__all__ = [
    "COLUMN_BY_KEY",
    "DEFAULT_EXPORT_KEYS",
    "EXPORT_COLUMNS",
    "EXPORT_MODULE",
    "ExportColumn",
    "build_workbook",
    "column_catalog",
    "export_ledger",
    "export_log_dict",
    "resolve_columns",
]
