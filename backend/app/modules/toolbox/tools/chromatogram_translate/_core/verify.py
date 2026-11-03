"""三关校验：任何硬关不过，该文件不出产物（数据完整性优先于可用性）。

1. 前置：文本层存在 + 模板识别（在 pipeline 前置阶段做）
2. 残留中文 = 0（硬）
3. 数字串多重集一致（硬）——曾抓住遮盖误删 RT 值的回归
版式告警（缩字号/缩写/两行拆分）为软信息，进报告供人工复核。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import cast

import pymupdf

from .spans import has_cjk

_NUM_RE = re.compile(r"\d+\.\d+|\d+")


def digit_multiset(doc: pymupdf.Document) -> Counter[str]:
    text = "\n".join(cast(str, doc[i].get_text()) for i in range(len(doc)))
    return Counter(_NUM_RE.findall(text))


def residual_cjk_lines(doc: pymupdf.Document) -> list[str]:
    out: list[str] = []
    for pno in range(1, len(doc) + 1):
        for line in cast(str, doc[pno - 1].get_text()).splitlines():
            if has_cjk(line):
                out.append(f"P{pno}: {line.strip()[:60]}")
    return out


@dataclass
class VerifyResult:
    ok: bool = True
    hard_errors: list[str] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.ok = False
        self.hard_errors.append(message)


def verify_output(src: pymupdf.Document, out: pymupdf.Document) -> VerifyResult:
    """对源/译后文档执行三关（前置检查之外的关卡）。"""
    r = VerifyResult()
    residual = residual_cjk_lines(out)
    if residual:
        r.fail(f"译后残留中文 {len(residual)} 行（首行：{residual[0]}）")
    a, b = digit_multiset(src), digit_multiset(out)
    lost, extra = a - b, b - a
    if lost or extra:
        parts = [f"丢失 {dict(lost)}"] if lost else []
        parts += [f"新增 {dict(extra)}"] if extra else []
        r.fail(f"数字串多重集不一致（{'，'.join(parts)}）")
    r.stats["残留中文行"] = len(residual)
    r.stats["数字串种类(源)"] = len(a)
    r.stats["数字串种类(译后)"] = len(b)
    return r
