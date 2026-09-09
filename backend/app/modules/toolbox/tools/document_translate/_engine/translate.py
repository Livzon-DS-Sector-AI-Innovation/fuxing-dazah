"""LLM 翻译：批量请求、失败重试、JSON 严格解析；附带 Mock 实现用于离线测试。"""
from __future__ import annotations

import json
import re
import time


class TranslationError(Exception):
    pass


SYSTEM_PROMPT = """你是一名精通 GMP（药品生产质量管理规范）领域的资深专业翻译，\
擅长医药法规文件、批记录、工艺验证报告、标准操作规程等文档的中英文互译。

翻译要求：
1. 只做翻译，严禁增删内容，严禁添加解释、注释或原文没有的信息。
2. 译文使用正式的技术文档书面语体，术语准确、表述严谨。
3. 原文中形如 ⟦N1⟧、⟦N2⟧ 的占位符代表数字、日期、批号、规格、单位等关键信息，\
必须原样保留在译文中的对应位置，一个不能多、不能少、不能改写。
4. 严格遵守用户提供的术语对照表。
5. 原文若以编号开头（如 "1."、"2.3"、"(a)"），译文保留该编号。
6. 返回 JSON，不要输出任何 JSON 以外的内容。"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def build_user_prompt(items, target_lang: str, doc_type: str, glossary_lines: list[str], prev_context: str) -> str:
    parts = [f"文档类型：{doc_type}", f"目标语言：{target_lang}"]
    if glossary_lines:
        parts.append("术语表（必须严格执行）：\n" + "\n".join(glossary_lines))
    if prev_context:
        parts.append(f"（上一段原文，仅供上下文参考，无需翻译：{prev_context}）")
    parts.append(
        '请翻译以下段落，返回 JSON：{"t": [{"i": 段落编号, "s": "译文"}]}。'
        "必须覆盖全部输入编号，不得遗漏、不得增删段落。\n"
    )
    for i, text in items:
        parts.append(f"{i}|{text}")
    return "\n".join(parts)


class MockTranslator:
    """离线测试用：恒等替换。用于验证抽取/插入/校验全链路，不验证译文质量。"""

    name = "mock"

    def translate_batch(self, items, target_lang, doc_type, glossary_lines, prev_context) -> dict[int, str]:
        return {i: text for i, text in items}


# 结构化输出 schema：强制模型只能返回 {"t": [{"i": 编号, "s": 译文}]}
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "t": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer", "description": "段落编号"},
                    "s": {"type": "string", "description": "译文"},
                },
                "required": ["i", "s"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["t"],
    "additionalProperties": False,
}


class LLMTranslator:
    """OpenAI 兼容接口客户端（GLM / DeepSeek / Qwen / OpenAI 等均可）。"""

    name = "llm"

    def __init__(self, base_url: str, api_key: str, model: str, max_retries: int = 3, timeout: float = 180.0,
                 thinking_level: str = ""):
        from openai import OpenAI

        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model = model
        self.max_retries = max_retries
        # 思考等级（对应当前 API 的 reasoning_effort 参数，low/high/max；空=服务端默认）
        self.thinking_level = thinking_level
        # 优先 json_schema（strict）强约束；服务商/模型不支持时自动降级 json_object
        self._schema_ok = True

    def _request(self, user: str):
        from openai import BadRequestError

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        extra = {"reasoning_effort": self.thinking_level} if self.thinking_level else None
        if self._schema_ok:
            try:
                return self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0.1,
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "translation_result", "strict": True, "schema": RESULT_SCHEMA}},
                    extra_body=extra,
                )
            except BadRequestError:
                self._schema_ok = False  # 本批及后续全部降级为 json_object
        return self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0.1,
            response_format={"type": "json_object"},
            extra_body=extra,
        )

    def translate_batch(self, items, target_lang, doc_type, glossary_lines, prev_context) -> dict[int, str]:
        if not items:
            return {}
        ids = [i for i, _ in items]
        collected: dict[int, str] = {}
        pending = list(items)
        last_err = None
        for attempt in range(self.max_retries + 1):
            if not pending:
                break
            user = build_user_prompt(pending, target_lang, doc_type, glossary_lines, prev_context)
            try:
                resp = self._request(user)
                content = resp.choices[0].message.content or ""
                data = json.loads(_strip_fences(content))
                raw = data.get("t") or data.get("translations") or []
                for entry in raw:
                    collected[int(entry["i"])] = str(entry.get("s", ""))
                missing = [i for i in ids if i not in collected]
                if not missing:
                    return {i: collected[i] for i in ids}
                last_err = TranslationError(f"返回编号不完整，缺失: {missing}")
                # 长批上模型会随机漏发若干条：累积分部结果，下一轮只补翻缺失项——
                # 提示词变短更易完整返回，也避免同提示重复抽中同样的漏发
                pending = [(i, text) for i, text in items if i not in collected]
            except Exception as e:  # noqa: BLE001 —— 网络/解析/结构异常统一走重试
                last_err = e
            if attempt < self.max_retries:
                time.sleep(2**attempt)
        raise TranslationError(f"批次翻译失败（已重试 {self.max_retries} 次）: {last_err}")


def make_batches(units, max_units: int = 30, max_chars: int = 6000):
    """把连续单元切批，保持文档顺序，兼顾条数与字符量。"""
    batches, cur, cur_chars = [], [], 0
    for u in units:
        n = len(u.text)
        if cur and (len(cur) >= max_units or cur_chars + n > max_chars):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(u)
        cur_chars += n
    if cur:
        batches.append(cur)
    return batches
