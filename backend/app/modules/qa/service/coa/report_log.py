"""COA 出具登记的操作日志：登记、编辑、作废、生成各记一条。

读侧走 QA 操作日志的通用读模型（``service.audit.OPERATION_LOG_SOURCES`` 登记）。
结果值是硬删重插，事后能不能说清「谁在什么时候把哪个值从什么改成什么」
全靠这里的逐格前后快照：键=字段中文名，值形如 {值, 备注}。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa.models import CoaReport
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User

COA_LOG_RESOURCE = "qa.coa_report"

# COA 操作日志动作词表：登记 / 编辑 / 作废 / 生成 COA。
COA_LOG_ACTION_CREATED = "report_created"
COA_LOG_ACTION_UPDATED = "report_updated"
COA_LOG_ACTION_VOIDED = "report_voided"
COA_LOG_ACTION_RENDERED = "report_rendered"
COA_LOG_ACTIONS = (
    COA_LOG_ACTION_CREATED,
    COA_LOG_ACTION_UPDATED,
    COA_LOG_ACTION_VOIDED,
    COA_LOG_ACTION_RENDERED,
)

# 一格快照：{值, 备注}；None 表示这一格是空的。
Cell = dict[str, Any]

# 进日志的前后值：逐格快照，或作废时的汇总（{值数量: N}）。
LogCells = Mapping[str, Any]

REMARK_LABEL = "备注"


def _field(row: Any, key: str) -> Any:
    """CoaReportValue ORM 与待写行 dict 统一按 key 取字段。"""
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def value_cell(value_num: Any, value_text: Any, remark: Any) -> Cell | None:
    """结果值一格：与回填同口径——原文优先，没原文才用数值。"""
    raw = str(value_text or "").strip() or (
        str(value_num) if value_num is not None else ""
    )
    cell: Cell = {}
    if raw:
        cell["值"] = raw
    if remark:
        cell["备注"] = remark
    return cell or None


def _log_labels(pairs: Sequence[tuple[str, str]]) -> dict[str, str]:
    """(键, 中文名) → 键 → 日志里的格名；中文名撞了各自带上键。"""
    counts: dict[str, int] = {}
    for _key, label in pairs:
        counts[label] = counts.get(label, 0) + 1
    return {
        key: label if counts[label] == 1 else f"{label}（{key}）" for key, label in pairs
    }


def item_log_labels(items: Sequence[Any]) -> dict[uuid.UUID, str]:
    """项目 id → 日志里的格名；中文名重复时带上项目 code（code 在标准内唯一）。

    值行是硬删重插，逐格快照就是唯一的历史。同名项目不区分开，后一条会把前
    一条的格覆盖掉，改前一条时新旧快照相等 → 整条改动不记日志。
    """
    counts: dict[str, int] = {}
    for item in items:
        counts[item.name_cn] = counts.get(item.name_cn, 0) + 1
    return {
        item.id: (
            item.name_cn
            if counts[item.name_cn] == 1
            else f"{item.name_cn}（{item.code}）"
        )
        for item in items
    }


def report_cells(
    report: CoaReport,
    *,
    batch_info: Mapping[str, str],
    fields: Sequence[Mapping[str, Any]],
    values: Sequence[Any],
    item_labels: Mapping[uuid.UUID, str],
) -> dict[str, Cell]:
    """一份报告全部可变内容的快照：批次信息各字段 + 备注 + 各检测结果。

    品名由产品带出、登记改不了，不记。空格不入（diff 里缺键即空）。
    """
    cells: dict[str, Cell] = {}
    labels = _log_labels([(str(f["key"]), str(f["label_cn"])) for f in fields])
    for key, label in labels.items():
        if key != "product_name" and batch_info.get(key):
            cells[label] = {"值": batch_info[key]}
    if report.remark:
        cells[REMARK_LABEL] = {"值": report.remark}
    for row in values:
        item_id = _field(row, "item_id")
        if item_id is None:
            continue
        cell = value_cell(
            _field(row, "value_num"), _field(row, "value_text"), _field(row, "remark")
        )
        if cell is None:
            continue
        label = item_labels.get(item_id) or f"（已移除的项目）{item_id}"
        if label in cells:  # 项目名与批次字段同名：标明这是检测结果
            label = f"{label}（检测结果）"
        cells[label] = cell
    return cells


def diff_cells(
    old: dict[str, Cell], new: dict[str, Cell]
) -> tuple[dict[str, Cell | None], dict[str, Cell | None]]:
    """逐格 diff：只含实际变化的格；被清空的格旧值记内容、新值记 None。"""
    old_out: dict[str, Cell | None] = {}
    new_out: dict[str, Cell | None] = {}
    for label in list(old) + [key for key in new if key not in old]:
        if old.get(label) != new.get(label):
            old_out[label] = old.get(label)
            new_out[label] = new.get(label)
    return old_out, new_out


async def record_report_log(
    db: AsyncSession,
    *,
    action: str,
    report: CoaReport,
    user: User | None,
    product_name: str | None,
    standard_code: str | None,
    old_cells: LogCells | None = None,
    new_cells: LogCells | None = None,
    **extra: Any,
) -> None:
    """写一条 COA 出具登记的操作日志；extra 是定位上下文（前端列表直接读）。"""
    await record_audit_log(
        db,
        action=action,
        user=user,
        resource_type=COA_LOG_RESOURCE,
        resource_id=report.id,
        old_value=dict(old_cells) if old_cells is not None else None,
        new_value=dict(new_cells) if new_cells is not None else None,
        extra={
            "product_id": str(report.product_id),
            "product_name": product_name,
            "standard_id": str(report.standard_id),
            "standard_code": standard_code,
            "report_id": str(report.id),
            "batch_no": report.batch_no,
            **extra,
        },
    )
