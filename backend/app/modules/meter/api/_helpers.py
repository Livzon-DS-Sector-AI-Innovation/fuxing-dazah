"""API 层共享辅助函数。"""

from __future__ import annotations

from typing import Any

from app.modules.meter.schemas import ReportItem

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
