"""法规标准标题归一化匹配（跨命名域）。

2026-11-06 阻火器引用事故：同一部法规在三处命名各不相同——

- ragplus 文档名：``GB50160-2008_石油化工企业设计防火标准``（标准号前缀）
- knowledge_articles 表标题：``石油化工企业设计防火标准``（无标准号）
- 模型正文引用：``《石油化工企业设计防火标准》GB 50160-2008 [4]``（标准号在书名号外）

精确全等在三处之间全部失配，导致 feishu_url 回填为空、参考栏编号错位。
本模块提供「标准号 + 归一化名称」双键匹配，供 sources URL 回填
（query_service._build_sources）与卡片编号锚定（bot handler）共用。

匹配语义：标准号相等视为同一文档（不同年份版本视为同部，链接指向任一版可接受）；
无标准号或仅一侧有标准号时，退化为归一化名称全等/互含比对。
"""

from __future__ import annotations

import re

# 带年份标准号：GB/T 20801.6-2006 / GB50160-2008 / SH/T 3020-2013 / AQ 3017-2008 …
_STD_RE = re.compile(
    r"([A-Z]{1,4}(?:/[TZ])?)\s*\.?\s*(\d{2,6}(?:\.\d{1,2})?)\s*[-—–]\s*(\d{4})"
)
# 无年份标准号（草案/报批稿等）：GB 5908 / SH/T 3007。要求前面非字母数字，
# 避免「第6部分」「IIIA1」这类正文碎片误命中；后面不跟数字/点/横线避免吞年份。
_STD_NOYEAR_RE = re.compile(
    r"(?:^|[^A-Z0-9])([A-Z]{1,4}(?:/[TZ])?)\s*\.?\s*(\d{2,6}(?:\.\d{1,2})?)(?![\d.\-])"
)

# 归一化名称只保留中文/字母/数字（去空格、书名号、连字符、括号等）
_NAME_CHAR_RE = re.compile(r"[^0-9A-Z\u4e00-\u9fff]")


def _upper_norm(text: str) -> str:
    """大写 + Unicode 斜杠归一（知识库存在 ``SH∕T3007`` 这类 U+2215 除号斜杠）。"""
    return text.upper().replace("∕", "/").replace("／", "/")


def extract_std_key(text: str) -> str:
    """提取标准号键（大写、去斜杠/点，去年份）。

    ``GB/T 20801.6-2006`` → ``GBT20801.6``；``gb 5908`` → ``GB5908``；
    无标准号返回 ``""``。年份不参与（同号不同版视为同部）。
    """
    if not text:
        return ""
    up = _upper_norm(text)
    m = _STD_RE.search(up)
    if m:
        return f"{m.group(1).replace('/', '')}{m.group(2)}"
    m2 = _STD_NOYEAR_RE.search(up)
    if m2:
        return f"{m2.group(1).replace('/', '')}{m2.group(2)}"
    return ""


def normalize_name(text: str) -> str:
    """剥离标准号后仅保留中文/字母/数字（小写），用于名称比对。"""
    if not text:
        return ""
    up = _upper_norm(text)
    up = _STD_RE.sub(" ", up)
    up = _STD_NOYEAR_RE.sub(" ", up)
    return _NAME_CHAR_RE.sub("", up).lower()


def titles_match(a: str, b: str, *, containment: bool = True) -> bool:
    """判断两段标题文本是否指向同一部法规/标准。

    Args:
        a, b: 任意命名域的标题文本（可含书名号、标准号、前缀后缀）。
        containment: 是否允许名称互含（短边 ≥4 字符防碎片误配）。
            严格轮（全等）应传 False，互含轮再传 True。
    """
    if not a or not b:
        return False
    a_std, b_std = extract_std_key(a), extract_std_key(b)
    if a_std and b_std:
        # 双方都有标准号：以标准号为唯一判据（名称差异可能是分册/别名）
        return a_std == b_std
    a_name, b_name = normalize_name(a), normalize_name(b)
    if not a_name or not b_name:
        return False
    if a_name == b_name:
        return True
    if containment:
        shorter, longer = sorted((a_name, b_name), key=len)
        if len(shorter) >= 4 and shorter in longer:
            return True
    return False
