"""API 层共享辅助函数。"""

from __future__ import annotations

from typing import Any

from app.modules.meter.schemas import ReportItem

# Excel 把以这些字符开头的单元格当公式/引用执行；台账字段均用户可编辑，
# 导出前必须净化，否则导出文件本身成为注入载体
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value: Any) -> Any:
    """导出单元格防公式注入：危险开头的字符串前置单引号强制为文本。"""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _sanitize_row(values: list[Any]) -> list[Any]:
    """整行净化（导出 CSV/Excel 用）。"""
    return [_sanitize_cell(v) for v in values]

# ═══════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════


def _build_report_items(reports: list[Any]) -> list[dict[str, Any]]:
    """将 ORM report 对象转换为 ReportItem 字典列表。"""
    items: list[dict[str, Any]] = []
    for r in reports:
        items.append(
            ReportItem(
                id=str(r.id),
                file_name=r.file_name,
                file_size=r.file_size,
                content_type=r.content_type,
                certificate_no=r.certificate_no,
                report_date=r.report_date,
                remark=r.remark,
                uploaded_at=r.created_at,
                download_url=f"./reports/{r.id}/download",
            ).model_dump(mode="json")
        )
    return items
