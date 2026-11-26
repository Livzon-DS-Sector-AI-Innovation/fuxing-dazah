"""COA 模板 AI 标注：只产提案，不落库。

把带地址的模板文本与字段清单交给模型，模型判断每个字段写进哪个数据位；
模型输出解析成载荷后交给 review.assemble 做确定性校验与人工核对。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.modules.qa.service.coa.ai_parse import (
    _EXTRACT_TIMEOUT,
    _MAX_TOKENS,
    _require_ai,
)
from app.modules.qa.service.coa.common import get_standard_or_404
from app.modules.qa.service.coa.template_bind.fields import FieldDef, build_fields
from app.modules.qa.service.coa.template_bind.review import assemble
from app.modules.qa.service.coa.template_bind.store import (
    BIND_PROMPT_VERSION,
    load_template_data,
    parse_template,
    template_summary,
)

logger = logging.getLogger(__name__)

_PROMPT = """你是制药 QA 系统的文档标注器。下面是一份产品检验报告单（COA）docx 的带地址文本，以及系统里该模板的字段清单。请判断每个字段的值应当写入文档的哪个位置，只输出一个 json 对象，不要输出任何其他文字。

地址规则：
- 方括号里是地址，标识一个可以写入文字的段落。P=正文段落，T=表格单元格（T表号.R行号.G列号.p段号，列号是表格网格列，跨列的格子会占掉多个列号），H/F=页眉/页脚。
- 一行里的各单元格用「｜」分隔，「⏎」表示换行；〖跨N列〗〖同上〗是合并单元格标记。

字段清单（返回时 field 原样使用）：
{fields}

标注规则：
1. item 的值写在检测项目表中该项目的「结果」列（表头写「结果/Results」的那一列，所有行都是同一个列号）。项目名格可能跨行合并（多行共用一个项目名），要结合该行的标准文字判断是哪一行。
2. batch 字段的值通常在标签格（如「批号⏎Batch No.」）的右侧或下方；同一字段的值可能在文档中出现多次（页眉、表格内），全部列出，但这些位置的当前值必须相同。
3. 值夹在固定文字中间时（如「CERTIFICATE OF ANALYSIS  26112401」），也绑定该段地址，sample 只填值本身。
4. 模板可能还没有填写：值的位置为空，或是占位符（如 XXXXXXXX、×××、____、年 月 日），这些位置同样要绑定。sample 只填值本身——照抄占位符，位置为空时填空字符串；绝不要把周围的固定文字（如 CERTIFICATE OF ANALYSIS、No.:、批号）写进 sample。
5. 标签、标准规定、报告编号（如 No.:COA-XX-0000-000）、品名、储存条件、公司信息、签字栏、结论等是模板里的固定文字，不是任何字段的值，不要绑定。字段清单里的每个字段都要在文档里找到它的值位置。
6. 一个地址最多绑定一个字段；每个字段至少绑定一个位置；文档里确实找不到位置的字段放进 unmapped，不要编造地址。
7. 同一字段绑定多个位置时，这些位置的当前值必须相同；值不同的位置不能算同一个字段。
8. 流水号（batch:serial_no）就是标题行 CERTIFICATE OF ANALYSIS 右侧的数字串或占位符（如 XXXXXXXX），这个位置永远绑定流水号；批号（batch:batch_no）只绑定「批号 / Batch No. / Lot No.」标签旁的值。

json 结构：
{{
  "bindings": [
    {{"field": "batch:batch_no", "slots": [{{"id": "T0.R0.G3.p0", "sample": "2611001"}}]}}
  ],
  "unmapped": ["item:9"]
}}

<document>
{doc}
</document>"""


def _prompt_fields(fields: list[FieldDef]) -> tuple[str, dict[str, FieldDef]]:
    """字段清单文本；检测项目按序号交给模型（item:1…），返回「模型用的键→字段」。"""
    lines: list[str] = []
    ai_keys: dict[str, FieldDef] = {}
    index = 0
    for field in fields:
        if field.kind == "batch":
            ai_key = field.key
            kind = "日期" if field.field_type == "date" else "文字"
            lines.append(
                f"- {ai_key}：批次信息「{field.label_cn} / {field.label_en or ''}」（{kind}）"
            )
        else:
            index += 1
            ai_key = f"item:{index}"
            bits = [f"- {ai_key}：检测项目「{field.label_cn}」"]
            if field.label_en:
                bits.append(f"英文 {field.label_en}")
            if field.spec_text:
                bits.append(f"标准 {field.spec_text}")
            if field.unit:
                bits.append(f"单位 {field.unit}")
            lines.append("，".join(bits))
        ai_keys[ai_key] = field
    return "\n".join(lines), ai_keys


def _parse_annotation(content: str) -> dict[str, Any]:
    """模型输出 → 标注载荷；解掉偶发的外包装并校验结构，不合格抛 ValueError 触发重试。"""
    try:
        payload: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型输出不是合法 JSON: {exc}") from exc
    if isinstance(payload, list):
        payload = {"bindings": payload}
    resolved: dict[str, Any] | None = None
    if isinstance(payload, dict):
        for candidate in (payload, payload.get("content"), payload.get("data")):
            if isinstance(candidate, dict) and isinstance(candidate.get("bindings"), list):
                resolved = candidate
                break
    if resolved is None:
        raise ValueError("模型输出缺少 bindings 数组")
    cleaned: list[dict[str, Any]] = []
    for binding in resolved["bindings"]:
        if not isinstance(binding, dict) or not isinstance(binding.get("field"), str):
            raise ValueError("bindings 元素缺少 field")
        slots = binding.get("slots")
        if not isinstance(slots, list) or not all(
            isinstance(s, dict) and isinstance(s.get("id"), str) for s in slots
        ):
            raise ValueError(f"{binding.get('field')} 的 slots 结构不合法")
        cleaned.append(
            {
                "field": binding["field"],
                "slots": [
                    {"id": str(s["id"]), "sample": str(s.get("sample") or "")} for s in slots
                ],
            }
        )
    unmapped = resolved.get("unmapped")
    return {
        "bindings": cleaned,
        "unmapped": [str(k) for k in unmapped if isinstance(k, str)]
        if isinstance(unmapped, list)
        else [],
    }


async def _chat_json(prompt: str) -> dict[str, Any]:
    """deepseek-flash 标注（逐次重试 + 总时限兜底），口径同 ai_parse._chat_extract。"""
    settings = get_settings()
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        base_url=settings.QA_AI_BASE_URL.rstrip("/"),
        headers={"Authorization": f"Bearer {settings.QA_AI_API_KEY}"},
        timeout=_EXTRACT_TIMEOUT,
    ) as client:
        try:
            async with asyncio.timeout(_EXTRACT_TIMEOUT * 2):
                for _ in range(max(1, int(settings.QA_AI_MAX_RETRIES) + 1)):
                    try:
                        resp = await client.post(
                            "/chat/completions",
                            json={
                                "model": settings.QA_AI_MODEL,
                                "messages": [{"role": "user", "content": prompt}],
                                "temperature": 0,
                                "max_tokens": _MAX_TOKENS,
                                "response_format": {"type": "json_object"},
                            },
                        )
                        if resp.status_code >= 400:
                            raise RuntimeError(
                                f"模型请求失败 HTTP {resp.status_code}: {resp.text[:200]}"
                            )
                        choice = resp.json()["choices"][0]
                        if choice.get("finish_reason") != "stop":
                            raise RuntimeError("模型输出被截断（finish_reason != stop）")
                        return _parse_annotation(str(choice["message"]["content"]))
                    except Exception as exc:  # noqa: BLE001 — 逐次记日志再重试
                        last_error = exc
                        logger.warning("COA 模板标注尝试失败: %s", exc)
        except TimeoutError as exc:
            raise AppException(status_code=502, message="AI 标注超时，请稍后重试") from exc
    raise AppException(status_code=502, message=f"AI 标注失败，请稍后重试（{last_error}）")


async def annotate_template(db: AsyncSession, standard_id: uuid.UUID) -> dict[str, Any]:
    """AI 标注：返回给人工核对的提案（不落库）。"""
    _require_ai()
    standard = await get_standard_or_404(db, standard_id)
    doc = await asyncio.to_thread(
        parse_template, await load_template_data(standard)
    )
    fields = await build_fields(db, standard)
    if not fields:
        raise AppException(status_code=400, message="该标准还没有检测项目，无法标注模板")
    fields_text, ai_keys = _prompt_fields(fields)
    prompt = _PROMPT.format(fields=fields_text, doc=doc.addressed())
    payload = await _chat_json(prompt)
    return {
        "template": template_summary(standard),
        "grid": doc.grid(),
        "result_columns": doc.result_columns(),
        "prompt_version": BIND_PROMPT_VERSION,
        **assemble(doc, fields, ai_keys, payload),
    }
