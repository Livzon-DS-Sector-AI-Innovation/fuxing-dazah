"""领域预读（profiling）：翻译前先读 PDF 前 N 页，让模型生成"领域档案"，
注入后续每一批翻译的提示词——用户提出的译效增强手段。

档案内容：文档类型判定、所属领域、关键术语英→中建议译法、翻译风格要点。
与 config.json 的 doc_type 关系：档案追加在 doc_type 之后（人工指定优先表达，
自动档案补充领域细节）；与术语表冲突时以术语表为准（提示词中明确声明）。
"""
from __future__ import annotations

import json
import time

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_kind": {"type": "string", "description": "文档类型判定，如：ICH 指导原则草案（Step 2 征询意见稿）"},
        "domain": {"type": "string", "description": "所属专业领域及细分方向"},
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "en": {"type": "string"},
                    "zh": {"type": "string"},
                },
                "required": ["en", "zh"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "description": "翻译风格与注意事项要点"},
    },
    "required": ["doc_kind", "domain", "terms", "notes"],
    "additionalProperties": False,
}

_SYSTEM = (
    "你是医药法规领域的资深文档分析专家。阅读给定文档的开头部分，"
    "判断它是什么类型的文件、属于什么专业领域，提炼关键术语的建议中文译法"
    "（优先采用中国药监/NMPA、ICH 中文版、药典的既有惯例译法），"
    "并给出翻译该文档时的风格要点。只输出 JSON。"
)


def collect_profile_text(blocks, max_page: int, cap_chars: int = 15000) -> str:
    """从第 ≤max_page 页的结构块收集档案用文本（标题+段落，跳过表格）。"""
    parts: list[str] = []
    n = 0
    for b in blocks:
        if b.page > max_page or b.kind == "table":
            continue
        if b.text:
            parts.append(b.text)
            n += len(b.text)
            if n >= cap_chars:
                break
    return "\n".join(parts)[:cap_chars]


def format_profile(data: dict) -> str:
    """LLM 返回的结构化档案 → 注入提示词的紧凑文本。"""
    lines = [f"文档类型：{data.get('doc_kind', '')}", f"所属领域：{data.get('domain', '')}"]
    terms = data.get("terms") or []
    if terms:
        lines.append("关键术语建议译法（与术语表冲突时以术语表为准）：")
        lines += [f"- {t.get('en', '')}→{t.get('zh', '')}" for t in terms[:40]]
    if data.get("notes"):
        lines.append(f"翻译要点：{data['notes']}")
    return "\n".join(lines)


def _parse_profile(content: str) -> str:
    """解析模型返回：剥代码围栏 + 兼容模型自创的字段名/结构。"""
    from ..translate import _strip_fences

    data = json.loads(_strip_fences(content))
    if not isinstance(data, dict):
        raise ValueError("返回不是 JSON 对象")
    kind = data.get("doc_kind") or data.get("document_type") or data.get("文档类型") or ""
    domain = data.get("domain") or data.get("professional_field") or data.get("所属领域") or ""
    terms = data.get("terms") or data.get("key_terms") or data.get("术语") or []
    if isinstance(terms, dict):  # {"英文": "中文"} 形式
        terms = [{"en": k, "zh": v} for k, v in terms.items()]
    notes = data.get("notes") or data.get("style_notes") or data.get("翻译要点") or ""
    if not kind and not terms:
        raise ValueError("返回结构无法解析为领域档案")
    return format_profile({"doc_kind": str(kind), "domain": str(domain),
                           "terms": terms, "notes": str(notes)})


def run_profile(api_base_url: str, api_key: str, model: str, text: str,
                thinking_level: str = "", max_retries: int = 2, timeout: float = 120.0) -> str:
    """调用 LLM 生成领域档案，返回格式化文本。失败直接抛错（显式报错，无兜底）。"""
    if not text.strip():
        raise ValueError("前 N 页未抽取到任何文本，无法生成领域档案（可将 profile_pages 设为 0 关闭）")
    from openai import BadRequestError, OpenAI

    client = OpenAI(base_url=api_base_url, api_key=api_key, timeout=timeout)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            "以下是某份待翻译文档的开头部分（已剥离页眉页脚与行号），请分析。\n"
            '返回 JSON：{"doc_kind": "文档类型", "domain": "所属领域", '
            '"terms": [{"en": "英文术语", "zh": "中文译法"}], "notes": "翻译要点"}，'
            "不要输出 JSON 以外的内容。\n\n" + text
        )},
    ]
    extra = {"reasoning_effort": thinking_level} if thinking_level else None
    schema_ok = True  # json_schema 不被服务商支持时降级 json_object
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            if schema_ok:
                try:
                    resp = client.chat.completions.create(
                        model=model, messages=messages, temperature=0.1,
                        response_format={"type": "json_schema", "json_schema": {
                            "name": "domain_profile", "strict": True, "schema": PROFILE_SCHEMA}},
                        extra_body=extra,
                    )
                except BadRequestError:
                    schema_ok = False
            if not schema_ok:
                resp = client.chat.completions.create(
                    model=model, messages=messages, temperature=0.1,
                    response_format={"type": "json_object"}, extra_body=extra,
                )
            return _parse_profile(resp.choices[0].message.content or "")
        except Exception as e:  # noqa: BLE001 —— 网络/解析/结构异常统一走重试
            last_err = e
        if attempt < max_retries:
            time.sleep(2**attempt)
    raise ValueError(f"领域档案生成失败（已重试 {max_retries} 次）: {last_err}")
