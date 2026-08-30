"""报告内容识别 — 统一走多模态 AI 视觉识别（DeepSeek vision）。

识别 4 个字段：instrument_name（仪表名称/样品名称）、serial_number（出厂编号）、
certificate_no（证书编号）、calibration_date（本次校准/检定日期）。

早期方案曾用 PDF 文本层正则提取，但各家机构版式差异大（关键字字间空格、
并排列粘连、干扰词），维护成本高，已废弃；统一 AI 识别，版式无关。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.meter.ai_service import (
    call_ai_vision_extract_report_fields,
    render_pdf_images_as_base64,
)

logger = logging.getLogger(__name__)


async def extract_report_fields(
    file_data: bytes, config: dict[str, str] | None
) -> dict[str, Any]:
    """AI 视觉识别报告字段，返回 {"instrument_name","serial_number","certificate_no",
    "calibration_date","method","error"}。method: vision / failed。
    """
    if not config:
        return {
            "instrument_name": None,
            "serial_number": None,
            "certificate_no": None,
            "calibration_date": None,
            "method": "failed",
            "error": "未配置 METER_AI_*，无法识别",
        }
    try:
        images = await render_pdf_images_as_base64(file_data)
        if not images:
            raise ValueError("PDF 无法提取页面图片，文件可能已损坏或加密")
        fields = await call_ai_vision_extract_report_fields(
            config["api_url"], config["api_key"], config["model"], images
        )
        return {**fields, "method": "vision", "error": None}
    except Exception as e:
        logger.warning("AI 识别失败: %s", e)
        return {
            "instrument_name": None,
            "serial_number": None,
            "certificate_no": None,
            "calibration_date": None,
            "method": "failed",
            "error": f"AI 识别失败: {e}",
        }
