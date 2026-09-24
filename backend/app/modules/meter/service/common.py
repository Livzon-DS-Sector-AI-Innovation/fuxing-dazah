"""Meter 业务公共工具：显示状态计算与下次检定日期推算。"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.time import today as time_today

MODULE_CODE = "meter"


def normalize_report_content_type(content_type: str | None) -> str:
    """报告文件 content_type 白名单：仅放行 PDF 与图片，其余一律落为
    application/octet-stream。客户端可任意声明 content_type，preview 端点
    以 inline 回显，若原样透传 text/html 等类型会在 API 域下构成存储型 XSS。
    """
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct == "application/pdf" or ct.startswith("image/"):
        return ct
    return "application/octet-stream"


def compute_status(record_status: str | None, next_calibration_date: date | None) -> str | None:
    """计算显示状态。

    - 在用/超期 + 下次检定已过期 → 显示"超期"
    - 手动设为超期 + 下次检定未过期（或无日期） → 自动恢复为"在用"
    - 停用永不变为超期，原样返回
    """
    if record_status in ("在用", "超期") and next_calibration_date is not None and next_calibration_date < time_today():
        return "超期"
    if record_status == "超期" and (next_calibration_date is None or next_calibration_date >= time_today()):
        return "在用"
    return record_status


def _auto_calc_next_calibration_date(item: dict[str, Any]) -> None:
    """自动计算下次检定日期 = 检定日期 + 检定周期(月) - 1 天。

    仅在「已提供检定日期和检定周期、但未提供下次检定日期」时生效，
    不会覆盖用户已手动填写的下次检定日期。
    日期推算统一走 ai_service.calc_next_calibration_date，避免两套规则漂移。
    """
    from app.modules.meter.ai_service import calc_next_calibration_date

    cal_date = item.get("calibration_date")
    cycle = item.get("calibration_cycle_months")
    next_date = item.get("next_calibration_date")

    if cal_date is not None and cycle is not None and next_date is None:
        if isinstance(cal_date, date):
            item["next_calibration_date"] = calc_next_calibration_date(cal_date, cycle)


# ═══════════════════════════════════════════
# 标准计量器具
# ═══════════════════════════════════════════
