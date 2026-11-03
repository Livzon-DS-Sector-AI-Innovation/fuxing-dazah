"""轻量 OpenAI 兼容客户端：仅用于缺失术语的批量补译（一次 JSON 调用）。

刻意不依赖任何其他工具/引擎——本工具完全独立可插拔。"""

from __future__ import annotations

import httpx

_SYSTEM = (
    "You are a professional translator for pharmaceutical analytical reports "
    "(HPLC/UPLC/fluorescence chromatography reports, Waters Empower style), "
    "Chinese -> English. "
    "Context: daptomycin specificity / forced-degradation and protein-impurity "
    "(BSA/HCP) method validation reports; peak table columns include retention "
    "time, area, area%, theoretical plates, height, tailing factor, resolution. "
    "Rules: use standard USP/pharma terminology, concise; person names -> pinyin "
    "(e.g. 杨雅琳 -> Yang Yalin); company short name 丽珠福兴 -> Livzon Fuxing; "
    "keep every non-Chinese character (digits, latin, symbols like β — * % \\) "
    "unchanged and in place; a string may be partial (a label without its value, "
    "or a value fragment) - translate only the Chinese part. "
    'Return a JSON object {"translations": {"<source>": "<english>", ...}} with '
    "the SAME key strings."
)


class LLMError(RuntimeError):
    """调用失败（网络/鉴权/响应不合法），消息可直接展示给用户"""


def translate_terms(
    base_url: str,
    api_key: str,
    model: str,
    strings: list[str],
    *,
    timeout: float = 120.0,
    retries: int = 2,
) -> dict[str, str]:
    """批量翻译缺失词条；返回 {原文: 译文}，失败抛 LLMError。"""
    if not strings:
        return {}
    import json

    payload = json.dumps({s: "" for s in strings}, ensure_ascii=False, indent=1)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": "Translate each string below for the report. "
                "JSON input:\n" + payload + "\n\n请以 JSON 格式返回结果。",
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    url = base_url.rstrip("/") + "/chat/completions"
    last_err = ""
    for _ in range(retries + 1):
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=timeout)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            tr = data.get("translations", data)
            missing = [s for s in strings if s not in tr]
            if missing:
                raise ValueError(f"模型返回缺少 {len(missing)} 条词条")
            return {s: str(tr[s]) for s in strings}
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as e:
            last_err = str(e) or e.__class__.__name__
    raise LLMError(f"术语补译失败（已重试 {retries} 次）：{last_err}")
