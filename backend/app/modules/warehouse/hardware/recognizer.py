"""五金库送货单 OCR 识别器（M2 主通道，设计 §四 4.1/§六）。

复用原辅料 receipt_recognition 管线骨架（recognizer.py 公有件）：
``detect_rotation`` 方向预判 + ``build_vision_message``/``parse_receipt_payload``
+ ``_recognize_with_retry`` 重试框架 + ``_make_thumbnail`` 缩略图；场景开关/
模型选路/审计经 scenario=hardware_receipt_recognition 全继承（audited_client
内层熔断），resource 用 hardware_receipt_parse / hardware_rotate_detect 区分。

输出 ``HardwareRecognizedReceipt``：供应商/送货单号/到货日期/多行
品名+规格+数量（打印体，识别准确率高）。识别结果只产草稿，人确认入账。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modules.warehouse.ai_audit.context import set_audit_resource
from app.modules.warehouse.agent.pipeline.recognizer import (
    build_vision_message,
    detect_rotation,
    parse_receipt_payload,
)

logger = logging.getLogger(__name__)

HARDWARE_SCENARIO = "hardware_receipt_recognition"

# 必提字段（全部为空才触发重试/报错——打印体单据至少有品名与数量）
HARDWARE_REQUIRED_FIELDS = ("rows",)

HARDWARE_RECEIPT_PROMPT = """你是一名五金仓库的仓管助理。图片是一张打印体五金送货单（供应商随货单据）。
请提取以下信息，严格输出 JSON（不要输出任何其他文字、不要 markdown 代码块包裹）：

{
  "supplier": "供应商名称（抬头/公章/落款处的公司名，识别不到为 null）",
  "delivery_note_no": "送货单号（单据编号，识别不到为 null）",
  "arrived_date": "到货/送货日期 YYYY-MM-DD（识别不到为 null）",
  "remark": "备注（含申购部门/领用车间等线索时原样提取，识别不到为 null）",
  "rows": [
    {
      "code": "物料编码（单上有编码才填，没有为 null）",
      "name": "品名（物资名称，必填）",
      "spec": "规格型号（如 DN25、φ108*4、304，识别不到为 null）",
      "quantity": 数量（数字，必填）,
      "unit": "单位（个/台/米/片/套/副，识别不到为 null）"
    }
  ]
}

要求：
- rows 逐行对应单据上的物料行，宁多勿漏，不改写品名（保留原文）；
- 数量必须是纯数字（去千分位）；
- 全部字段无法识别时填 null，rows 至少返回 []。"""

_HARDWARE_JSON_RETRY_PROMPT = (
    "上次输出不合规：{reason}。请重新严格按 JSON schema 输出，"
    "不要任何解释文字或代码块标记。"
)


class RecognizedRow(BaseModel):
    """识别出的单行物料。"""

    code: str | None = None
    name: str = ""
    spec: str | None = None
    quantity: float | None = None
    unit: str | None = None


class HardwareRecognizedReceipt(BaseModel):
    """五金送货单结构化提取结果（ocr_result JSON 留痕的形状）。"""

    supplier: str | None = None
    delivery_note_no: str | None = None
    arrived_date: str | None = None
    remark: str | None = None
    rows: list[RecognizedRow] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_quantity(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def build_hardware_receipt(payload: dict[str, Any]) -> HardwareRecognizedReceipt:
    """LLM payload → 结构化模型（容错：行缺必填字段丢弃）。"""
    rows: list[RecognizedRow] = []
    for raw_row in payload.get("rows") or []:
        if not isinstance(raw_row, dict):
            continue
        name = _to_str(raw_row.get("name"))
        qty = _to_quantity(raw_row.get("quantity"))
        if not name or qty is None or qty <= 0:
            continue
        rows.append(
            RecognizedRow(
                code=_to_str(raw_row.get("code")),
                name=name,
                spec=_to_str(raw_row.get("spec")),
                quantity=qty,
                unit=_to_str(raw_row.get("unit")),
            )
        )
    return HardwareRecognizedReceipt(
        supplier=_to_str(payload.get("supplier")),
        delivery_note_no=_to_str(payload.get("delivery_note_no")),
        arrived_date=_to_str(payload.get("arrived_date")),
        remark=_to_str(payload.get("remark")),
        rows=rows,
        raw=payload,
    )


async def recognize_hardware_receipt(
    image_b64: str, content_type: str = "image/jpeg"
) -> HardwareRecognizedReceipt:
    """五金送货单识别（重试框架复用原辅料管线）。"""
    from app.modules.warehouse.agent.llm_client import (
        WarehouseLLMError,
        get_llm_client,
    )
    from app.modules.warehouse.agent.pipeline.recognizer import (
        required_all_missing_for,
    )

    set_audit_resource("hardware_receipt_parse")
    async with get_llm_client() as client:
        messages = [build_vision_message(image_b64, content_type, prompt=HARDWARE_RECEIPT_PROMPT)]
        content = await client.chat_with_tools(
            messages, tools=None, temperature=0.1, max_tokens=16384
        )
        text = _assistant_text(content)
        payload = _parse_or_none(text)

        if payload is None or required_all_missing_for(payload, HARDWARE_REQUIRED_FIELDS):
            reason = "输出不是合法 JSON" if payload is None else "物料行为空"
            logger.warning("五金送货单识别输出不合规，重试 1 次: %s", reason)
            retry_messages = [
                *messages,
                {"role": "assistant", "content": text or "（空输出）"},
                {"role": "user", "content": _HARDWARE_JSON_RETRY_PROMPT.format(reason=reason)},
            ]
            content = await client.chat_with_tools(
                retry_messages, tools=None, temperature=0.1, max_tokens=16384
            )
            payload = _parse_or_none(_assistant_text(content))
            if payload is None:
                raise WarehouseLLMError("五金送货单识别 JSON 解析失败（重试后仍失败）")
        return build_hardware_receipt(payload)


def _assistant_text(message: Any) -> str | None:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "\n".join(p for p in parts if p) or None
    return None


def _parse_or_none(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        return parse_receipt_payload(text)
    except ValueError:
        return None


async def rotate_image_if_needed(image_b64: str, content_type: str = "image/jpeg") -> tuple[str, str]:
    """方向预判+旋正（复用原辅料管线 detect_rotation）。"""
    set_audit_resource("hardware_rotate_detect")
    rotation = await detect_rotation(image_b64, content_type)
    if not rotation:
        return image_b64, content_type
    import base64
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(base64.b64decode(image_b64)))
    img = img.rotate(rotation, expand=True)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"
