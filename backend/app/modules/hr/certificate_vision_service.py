"""证件扫描件视觉识别：上传后自动提取证号/姓名/发证日期/有效期等要素。

复用 meter 模块的视觉模型网关（METER_AI_BASE_URL/KEY/MODEL，全项目唯一的
多模态接入点，读仪表照片同款场景与鉴权形态）；pdfplumber 把 PDF 首页转图。
识别结果仅作表单预填，HR 核对后保存——证件要素以人确认为准。
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

from app.platform.integrations.ai.client import AIOutputError, AIService

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 送识别的图片上限（原件入库仍按 20MB）

_VISION_PROMPT = """你是证件信息提取助手。请从这张证件扫描件（身份证/学历证/职业资格证/特种作业操作证/健康证等）中提取以下字段：
- certificate_no：证件号码（身份证号/证书编号/操作证编号/健康证编号等印在证上的编号）
- holder_name：持证人姓名（身份证或印有姓名的证件才有）
- issue_date：发证日期/签发日期/起始日期，格式 YYYY-MM-DD，识别不出返回 null
- expiry_date：有效期至/失效日期/截止日期，格式 YYYY-MM-DD，识别不出返回 null
- is_permanent：证件标注"长期"/"长期有效"时为 true，否则 false
- certificate_name：证件全名（如"中华人民共和国特种作业操作证（低压电工作业）"，能看清才填，否则 null）

只提取图片上印刷的信息，不要推测。返回严格 JSON，形如：
{"certificate_no": "...", "holder_name": "...", "issue_date": "YYYY-MM-DD", "expiry_date": null, "is_permanent": false, "certificate_name": null}
"""

_EXPECTED_KEYS = ["certificate_no", "holder_name", "issue_date", "expiry_date", "is_permanent", "certificate_name"]


class CertificateVisionConfigError(Exception):
    """视觉模型网关未配置（功能不可用，前端回落手填）。"""


def _pdf_first_page_as_data_url(file_data: bytes) -> str | None:
    """PDF 首页 → PNG data URL（150dpi，证件首页即含全部要素）。"""
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(file_data)) as pdf:
            if not pdf.pages:
                return None
            img = pdf.pages[0].to_image(resolution=150)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/png;base64,{b64}"
    except Exception as e:  # noqa: BLE001
        logger.warning("证件 PDF 首页转图失败: %s", e)
        return None


def _build_data_url(file_bytes: bytes, ext: str) -> str | None:
    """图片直转 data URL；PDF 取首页。"""
    if ext == "pdf":
        return _pdf_first_page_as_data_url(file_bytes)
    if len(file_bytes) > _MAX_IMAGE_BYTES:
        raise ValueError("图片超过 10MB，无法自动识别，请手动填写或压缩后重试")
    mime = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "webp": "image/webp", "bmp": "image/bmp",
    }.get(ext)
    if mime is None:
        return None
    b64 = base64.b64encode(file_bytes).decode()
    return f"data:{mime};base64,{b64}"


def _get_vision_service() -> AIService:
    """视觉模型客户端：复用 meter 网关配置（平台唯一多模态接入点）。"""
    from app.core.config import get_settings

    s = get_settings()
    if not s.METER_AI_BASE_URL or not s.METER_AI_API_KEY:
        raise CertificateVisionConfigError(
            "视觉识别未配置（METER_AI_BASE_URL/METER_AI_API_KEY），请手动填写证件要素"
        )
    return AIService(
        api_key=s.METER_AI_API_KEY,
        base_url=s.METER_AI_BASE_URL,
        model=s.METER_AI_MODEL,
    )


async def parse_certificate(file_bytes: bytes, ext: str) -> dict[str, Any]:
    """证件扫描件 → 要素 dict（证号/姓名/发证/有效期/长期有效/证件名）。

    返回值直接用于表单预填；识别失败抛 ValueError（前端回落手填）。
    """
    data_url = _build_data_url(file_bytes, ext)
    if not data_url:
        raise ValueError("无法将该文件转为图片识别（仅支持图片与 PDF）")

    service = _get_vision_service()
    try:
        result = await service.chat_vision_parsed(
            _VISION_PROMPT, [data_url], expected_keys=_EXPECTED_KEYS,
        )
    except AIOutputError as e:
        logger.warning("证件识别输出异常: %s", e)
        raise ValueError("证件识别失败，请手动填写要素") from e
    except CertificateVisionConfigError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("证件识别调用失败: %s", e)
        raise ValueError("证件识别服务暂不可用，请手动填写要素") from e

    # 规整：空串→None；日期格式校验（宽松接受 YYYY.MM.DD / YYYY年M月D日）
    from datetime import date

    def _norm_date(v: object) -> str | None:
        if not v or not isinstance(v, str):
            return None
        raw = (v.strip()
               .replace("年", "-").replace("月", "-").replace("日", "")
               .replace(".", "-").replace("/", "-"))
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            return None

    return {
        "certificate_no": (str(result["certificate_no"]).strip() or None) if result.get("certificate_no") else None,
        "holder_name": (str(result["holder_name"]).strip() or None) if result.get("holder_name") else None,
        "issue_date": _norm_date(result.get("issue_date")),
        "expiry_date": _norm_date(result.get("expiry_date")),
        "is_permanent": bool(result.get("is_permanent")),
        "certificate_name": (str(result["certificate_name"]).strip() or None) if result.get("certificate_name") else None,
    }
