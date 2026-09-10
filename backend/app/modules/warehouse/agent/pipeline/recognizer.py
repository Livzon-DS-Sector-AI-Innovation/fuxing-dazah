"""送货单 Vision 识别器（S2 ticket 01，spec Implementation Decisions 2）。

职责单一：一张送货单图片（base64）→ 结构化 ``RecognizedReceipt``。
LLM 只做识别一件事：``WarehouseLLMClient.chat_with_tools(messages=视觉消息,
tools=None)``——messages 纯透传（S0 五重验证⑤），识别 prompt 独立于 Runner
系统提示词（温度 0.1 / max_tokens 4000 独立配置）。

字段分级（spec Implementation Decisions 2）：
- 必提 8：物料名称/厂家批号/数量/单位/供应商/生产商/车牌/合同号——
  低置信度也强制给值（value 允许 null，但字段必须出现在输出里）；
- 选提 5：包装规格/生产日期/到货时间段/备注/联系人——识别不到为 None。

JSON 解析容错：剥 markdown 代码块与首尾杂文字；解析失败重试识别 1 次
（prompt 强调"只输出 JSON"），仍失败抛 :class:`WarehouseLLMError`。
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.modules.warehouse.agent.llm_client import WarehouseLLMClient, WarehouseLLMError

logger = logging.getLogger(__name__)

# 识别调用参数（独立于 Runner，spec Further Notes：温度/token 独立配置）。
# max_tokens 必须给足：vision 模型（deepseek-v4-flash-vision-exp）是 reasoning
# 模型，reasoning_tokens 实测波动 3k-8k+，给小了 content 被耗尽为空
# （llm_client.py 模块注释同款契约，默认 16384）。
RECOGNIZE_TEMPERATURE = 0.1
RECOGNIZE_MAX_TOKENS = 16384

RECOGNIZE_PROMPT = """你是制药厂仓库的送货单识别助手。请仔细识别图片中的送货单/出库单/报告单信息，提取以下字段。

## 必提字段（8 个，每个都必须出现在输出中）
- material_name：物料名称（别名：品名、原料名称、材料名称）
- vendor_batch_no：厂家批号（别名：批号、LOT、生产批号、批次号、炉批号）
- quantity：入库数量（别名：数量、实收数量、送货数量；只给数字）
- unit：单位（如 Kg、kg、瓶、桶、L、包、个）
- supplier：供应商（别名：发货单位、供货单位、供方）
- manufacturer：生产商（别名：生产厂家、制造单位、生产企业）
- plate_no：车牌号（别名：车牌、运输车牌、车号）
- contract_no：合同编号或订单号（别名：合同号、订单号、采购订单、PO 号）

## 选提字段（7 个，识别不到就填 null）
- material_code：物料代码（别名：代码、物料编码；请验单/送货单常有此栏——
  这是物料身份的强标识，务必优先仔细辨认）
- package_count：件数（别名：件数、桶数、包数；如「总数量/件数 1404/14桶」取 14，只给数字）
- package_spec：包装规格（如 25Kg/包、500ml/瓶）
- produced_at：生产日期（别名：生产批号日期、制造日期）
- arrival_period：到货时间段
- remark：备注
- contact：联系人（别名：送货人、经手人、联系电话）

## 输出要求（严格遵守）
1. 只输出一个 JSON 对象，禁止输出任何解释文字或 markdown 代码块。
2. JSON 结构（15 个字段全部出现，格式统一）：
   {"material_name": {"value": "硫酸", "confidence": 0.95}, "vendor_batch_no": {"value": "H26050902", "confidence": 0.9}, ...}
3. 每个字段的 confidence 是 0 到 1 的小数，表示辨认把握程度：清晰可辨 ≥0.8，模糊但可推断 0.4-0.8，猜测 <0.4。
4. 无法辨认时 value 填 null 并给低 confidence，但必提字段必须基于图片给出最佳猜测，不要轻易填 null。
5. quantity 的 value 必须是数字或数字字符串（如 "1200" 或 1200），不要带单位。
6. 图片可能是送货单、物料请验单、厂家报告单、外包装或标签照片——字段名随单据类型自适应映射：请验单的「批号」→ vendor_batch_no、「总数量/件数」中的数量 → quantity、「物料代码」→ material_code；无论哪种单据都按必提字段提取图中可见信息；仅当图片完全没有文字时，必提字段 value 才填 null。
7. 图片可能是手写单据：逐字仔细辨认手写内容，书写潦草时结合上下文（物料代码/批号前缀与名称的对应关系）推断，但禁止把图中没有的信息编造为高置信度——辨认不清就给低 confidence。
"""

# JSON 解析失败/必提全空的追加指令（强调只输出 JSON + 必提字段不可全空）
_JSON_RETRY_PROMPT = (
    "你上一次的输出不合规：{reason}。请重新识别并只输出一个严格 JSON 对象："
    "不要 markdown 代码块、不要任何解释文字，直接以 {{ 开头、以 }} 结尾。"
    "必提 8 字段必须逐一看图给出最佳猜测（批号/品名/数量等常出现在报告单、"
    "外包装和标签上），不允许全部为 null。"
)

# 必提 8 字段（RecognizedReceipt 必填，解析缺省时 value=None/confidence=0）
REQUIRED_FIELDS: tuple[str, ...] = (
    "material_name",
    "vendor_batch_no",
    "quantity",
    "unit",
    "supplier",
    "manufacturer",
    "plate_no",
    "contract_no",
)

# 选提 5 字段（识别不到字段本身为 None）
OPTIONAL_FIELDS: tuple[str, ...] = (
    "package_spec",
    "produced_at",
    "arrival_period",
    "remark",
    "contact",
)


class RecognizedField(BaseModel):
    """单字段识别结果：值 + 置信度（0-1）。"""

    value: str | float | None = None
    confidence: float = 0.0


class RecognizedReceipt(BaseModel):
    """一张送货单的完整识别结果。

    - 必提 8 字段恒存在（无法辨认时 value=None、confidence=0）；
    - 选提 5 字段识别不到时字段本身为 None；
    - raw 保留 LLM 原始识别 JSON（dict），供对齐/审计回溯。
    """

    material_name: RecognizedField
    vendor_batch_no: RecognizedField
    quantity: RecognizedField
    unit: RecognizedField
    supplier: RecognizedField
    manufacturer: RecognizedField
    plate_no: RecognizedField
    contract_no: RecognizedField

    material_code: RecognizedField | None = None  # 物料代码（对齐代码锚点，2026-09-09）
    package_count: RecognizedField | None = None  # 件数（如「1404/14桶」的 14）
    package_spec: RecognizedField | None = None
    produced_at: RecognizedField | None = None
    arrival_period: RecognizedField | None = None
    remark: RecognizedField | None = None
    contact: RecognizedField | None = None

    raw: dict[str, Any] = Field(default_factory=dict)


def build_vision_message(image_b64: str, content_type: str = "image/jpeg") -> dict[str, Any]:
    """构造 vision 识别消息（chat_with_tools 纯透传的 user content 数组）。"""
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": RECOGNIZE_PROMPT},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{content_type};base64,{image_b64}"},
            },
        ],
    }


def _extract_json_text(content: str) -> str:
    """剥 markdown 代码块包裹（```json ... ``` / ``` ... ```）。"""
    text = content.strip()
    if "```" in text:
        chunks = [c.strip() for c in text.split("```") if c.strip()]
        # 优先取 ```json 标记后的块；否则取第一个含 { 的块
        for i, chunk in enumerate(chunks):
            body = chunk[4:].strip() if chunk.lower().startswith("json") else chunk
            if body.startswith("{"):
                return body
        if chunks:
            return chunks[0]
    return text


def parse_receipt_payload(content: str) -> dict[str, Any]:
    """把 LLM 输出容错解析为识别 JSON dict。

    容错顺序：原样 loads → 剥代码块 → 截取首个 { 到最后一个 } 之间子串。
    全部失败抛 ValueError（由 recognize_receipt 捕获触发重试）。
    """
    candidates = [content.strip(), _extract_json_text(content)]
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        candidates.append(content[start : end + 1])
    for text in candidates:
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"识别输出不是合法 JSON: {content[:200]}")


def _clamp(value: Any) -> float:
    """confidence 夹到 [0, 1]，非数字缺省 0。"""
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def _to_field(item: Any) -> RecognizedField:
    """把单字段原始值归一为 RecognizedField（兼容裸字符串/数字输出）。"""
    if isinstance(item, dict):
        return RecognizedField(value=item.get("value"), confidence=_clamp(item.get("confidence")))
    if item is None:
        return RecognizedField()
    return RecognizedField(value=item, confidence=0.0)


def build_receipt(payload: dict[str, Any]) -> RecognizedReceipt:
    """把识别 JSON dict 构造为 RecognizedReceipt（字段缺省容错）。"""
    kwargs: dict[str, Any] = {"raw": payload}
    for name in REQUIRED_FIELDS:
        kwargs[name] = _to_field(payload.get(name))
    for name in OPTIONAL_FIELDS:
        if payload.get(name) is not None:
            kwargs[name] = _to_field(payload[name])
    return RecognizedReceipt(**kwargs)


def required_all_missing(payload: dict[str, Any]) -> bool:
    """必提 8 字段是否全部为空值。

    实测（2026-09-07）：模型偶发把"非送货单图片"误判为不可识别——
    必提字段全 null 而选提字段（包装规格/备注）有值。此形态对下游
    Pipeline 是废结果，由 recognize_receipt 据此触发一次重试。
    """
    for name in REQUIRED_FIELDS:
        item = payload.get(name)
        if isinstance(item, dict):
            value = item.get("value")
            if value is not None and str(value).strip():
                return False
        elif item is not None and str(item).strip():
            return False
    return True


async def _call_recognize(
    client: WarehouseLLMClient, messages: list[dict[str, Any]]
) -> str:
    """单次识别调用，返回 LLM 原始文本输出。"""
    response = await client.chat_with_tools(
        messages=messages,
        tools=None,
        temperature=RECOGNIZE_TEMPERATURE,
        max_tokens=RECOGNIZE_MAX_TOKENS,
    )
    logger.debug(
        "recognize_receipt 用量=%s finish=%s",
        response.usage,
        response.finish_reason,
    )
    return response.content or ""


ROTATION_PROMPT = (
    "这是一张单据/文件的照片。判断照片需要顺时针旋转多少度，"
    "才能让单据上的文字变成正常横向可读（从左到右）。"
    "只输出一个 JSON：{\"rotation\": 0}、{\"rotation\": 90}、"
    "{\"rotation\": 180} 或 {\"rotation\": 270}（顺时针角度）。"
    "如果文字已经是正常方向可读，输出 {\"rotation\": 0}。"
)


async def detect_rotation(
    image_b64: str, content_type: str = "image/jpeg"
) -> int:
    """识别前方向预判：返回需要顺时针旋转的角度（0/90/180/270）。

    背景：手机横持拍照且无 EXIF 方向标记时，像素数据本身是旋转的——
    视觉模型对旋转单据的识别会大量幻觉（2026-09-09 实测：同一张手写
    请验单，0° 识别为「羟苯磺酸钙」，矫正 90° 后正确识别「纸箱(3#)」）。
    轻量调用（缩略图 + 小 max_tokens），失败/超时默认 0（不旋转）。
    """
    # 缩略图降成本：方向判断不需要原始分辨率（长边压到 768px）
    try:
        from io import BytesIO

        from PIL import Image

        raw = base64.b64decode(image_b64)
        img = Image.open(BytesIO(raw))
        img.thumbnail((768, 768))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        thumb_b64 = base64.b64encode(buf.getvalue()).decode()
        content_type = "image/jpeg"
    except Exception:  # noqa: BLE001 — 缩略失败用原图
        thumb_b64 = image_b64

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": ROTATION_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{content_type};base64,{thumb_b64}"},
                },
            ],
        }
    ]
    try:
        async with WarehouseLLMClient() as client:
            msg = await client.chat_with_tools(
                messages, tools=None, temperature=0.0, max_tokens=2000
            )
        content = msg.content or ""
        data = parse_receipt_payload(content)
        rotation = int(data.get("rotation") or 0)
        return rotation if rotation in (0, 90, 180, 270) else 0
    except Exception:  # noqa: BLE001 — 方向判断失败不阻断识别
        logger.warning("方向预判失败，按 0° 处理", exc_info=True)
        return 0


async def recognize_receipt(
    image_b64: str, content_type: str = "image/jpeg"
) -> RecognizedReceipt:
    """识别一张送货单图片（base64），返回结构化识别结果。

    输出不合规（JSON 解析失败，或必提 8 字段被模型整批置空）重试识别
    1 次（附原输出并强调只输出 JSON / 必提不可全空）；重试后 JSON 仍
    解析失败抛 :class:`WarehouseLLMError`，必提仍全空则诚实返回空字段
    （图片确实无文字的场景）。LLM 调用本身的网络/网关错误由客户端重试
    语义处理。
    """
    async with WarehouseLLMClient() as client:
        messages = [build_vision_message(image_b64, content_type)]
        content = await _call_recognize(client, messages)

        try:
            payload = parse_receipt_payload(content)
        except ValueError:
            payload = None

        if payload is None or required_all_missing(payload):
            reason = (
                "输出不是合法 JSON"
                if payload is None
                else "必提 8 字段全部为空（图片无文字时才允许）"
            )
            logger.warning("识别输出不合规，重试 1 次: %s", reason)
            retry_messages = [
                *messages,
                {"role": "assistant", "content": content or "（空输出）"},
                {"role": "user", "content": _JSON_RETRY_PROMPT.format(reason=reason)},
            ]
            content = await _call_recognize(client, retry_messages)
            try:
                payload = parse_receipt_payload(content)
            except ValueError as retry_error:
                raise WarehouseLLMError(
                    f"识别结果 JSON 解析失败（重试后仍失败）: {retry_error}"
                ) from retry_error
        return build_receipt(payload)
