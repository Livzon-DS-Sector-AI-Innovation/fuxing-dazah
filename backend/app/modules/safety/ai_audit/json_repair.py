"""AI 输出 JSON 本地修复（纯函数，无 IO）。

背景（A1「隐患 AI 识别 P0 加固」，2026-11-05；数字与
``.scratch/hazard-ai-p0/evidence/offline-replay.md`` 对齐）：
    近 30 天共 496 次调用（视觉 416 / 文本 80）：
    - 视觉「现状合法」（剥围栏后 ``json.loads``）89.9% → 本地修复后 **97.1%**
      （修复 30 次）；
    - 文本 91.2% → **96.2%**（修复 4 次）；
    - 合计 90.1% → **97.0%**（本地修复 34 次，全部为尾逗号），**零额外 AI 调用**。
    调用数最多的单日重跑窗口（288 次调用、**全链路**而非仅视觉）：257/288 =
    89.2% → 279/288 = 96.9%；31 条非法样本里 22 条只是尾逗号 ``",\\n }"``。

    口径提醒：审计字段 ``extra.json_valid`` = 「原文能否直接 ``json.loads``
    （不剥围栏）」，与本模块「修复后合法」、以及回放脚本「现状合法（剥围栏后
    loads）」是**三套不同口径**，不可直接互比（见 ``AuditedAIService``）。

修复级联（每级在前一级产物上叠加，逐级 ``json.loads``，首个成功即返回；
``→`` 后为落审计的 ``repair_stages`` stage 串）：
    1. ``strip_fences``              剥 markdown 代码围栏（```json ... ```）→ ``fence``
    2. ``slice_object``              取首个 ``{`` 到末个 ``}``（丢弃前后包裹文字）→ ``slice_object``
    3. ``drop_trailing_commas``      删对象/数组闭合前的尾逗号（字符串内逗号不动）→ ``trailing_comma``
    4. ``normalize_fullwidth_quotes`` 全角引号 ``“”`` → ``"``（仅末级兜底）→ ``fullwidth_quotes``

明确不做：截断补齐 / 括号配平。实测 30 天审计无一例 ``finish_reason=length``
截断（输出最大 1224 tokens，远低于 4096 上限），残余结构性畸形交给「带错误
反馈重试一次」路径处理（见 ``AuditedAIService.chat_vision_parsed``）。

修复结果仍由调用方执行 ``expected_keys`` / dict / 布尔串校验；本模块不校验
schema —— 「能解析」不等于「是有效业务输出」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

__all__ = [
    "JsonRepair",
    "drop_trailing_commas",
    "normalize_fullwidth_quotes",
    "repair_json",
    "repair_json_object",
    "slice_object",
    "strip_fences",
]


@dataclass(frozen=True)
class JsonRepair:
    """一次本地修复的结果。

    Attributes:
        data: 解析出的 JSON 值（dict/list/标量）；修复失败为 ``None``。
        stages: 实际生效的修复阶段（未改动不记；``fence`` 属历史既有行为）。
        error: 失败时的最后一个解析错误（人类可读，用于日志/重试反馈）。
    """

    data: Any = None
    stages: tuple[str, ...] = ()
    error: str | None = None

    @property
    def repaired(self) -> bool:
        """是否经本地修复后才成功（围栏/截取/尾逗号/全角引号任一阶段均算）。"""
        return self.data is not None and bool(self.stages)


def strip_fences(text: str) -> str:
    """剥 markdown 代码围栏（与历史 ``_parse_json_response`` 逻辑一致）。

    兼容 ``\\`\\`\\`json`` / ``\\`\\`\\``` 开围栏 + 结尾 ``\\`\\`\\``；无围栏原样返回。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        for i, line in enumerate(lines):
            if not line.strip().startswith("```"):
                cleaned = "\n".join(lines[i:])
                break
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return cleaned


def slice_object(text: str) -> str:
    """取首个 ``{`` 到末个 ``}``；无法定位时原样返回。

    只针对对象输出（``chat_parsed`` / ``chat_vision_parsed`` 均要求 dict）；数组
    输出**不截取**（否则会把 ``[{"a":1}]`` 切成 ``{"a":1}`` 丢失数组语义），
    数组合并语义由调用方在解析后按平台行为处理。
    """
    if text.lstrip().startswith("["):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def drop_trailing_commas(text: str) -> str:
    """删除 ``}`` / ``]`` 前的尾逗号（字符串内部的 ``",}"`` 不受影响）。

    逐字符状态机（跟踪 in_str / escape），只删除「逗号 + 空白 + 闭合符」中的逗号；
    逗号后的空白保留，避免破坏可读性。
    """
    out: list[str] = []
    in_str = False
    escaped = False
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if in_str:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < length and text[j] in " \t\r\n":
                j += 1
            if j < length and text[j] in "}]":
                i += 1  # 丢弃逗号，保留其后的空白
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def normalize_fullwidth_quotes(text: str) -> str:
    """把中文全角双引号 ``“”`` 归一为 ASCII ``"``（仅末级兜底）。"""
    return text.replace("“", '"').replace("”", '"')


def _try_parse(text: str) -> tuple[bool, Any, str | None]:
    try:
        return True, json.loads(text), None
    except (json.JSONDecodeError, ValueError) as exc:  # noqa: PERF203 — 每级歧义小
        return False, None, f"{type(exc).__name__}: {exc}"


def repair_json(raw: str) -> JsonRepair:
    """把 AI 原始文本尽力修复为可解析 JSON（任意 JSON 值）。

    成功时返回首个可解析候选；失败时 ``data=None`` 且带最后一个解析错误。
    """
    if not isinstance(raw, str) or not raw.strip():
        return JsonRepair(error="empty response")

    stages: list[str] = []
    candidate = raw
    last_error: str | None = None

    def _attempt() -> JsonRepair | None:
        nonlocal last_error
        ok, data, error = _try_parse(candidate)
        if ok:
            return JsonRepair(data=data, stages=tuple(stages))
        last_error = error
        return None

    # 0) 原样（含仅空白差异）：先试可能直接成功
    result = _attempt()
    if result is not None:
        return result

    # 1) 剥围栏
    stripped = strip_fences(candidate)
    if stripped != candidate:
        stages.append("fence")
        candidate = stripped
        result = _attempt()
        if result is not None:
            return result

    # 2) 取首个 { 到末个 }
    sliced = slice_object(candidate)
    if sliced != candidate:
        stages.append("slice_object")
        candidate = sliced
        result = _attempt()
        if result is not None:
            return result

    # 3) 删尾逗号
    dropped = drop_trailing_commas(candidate)
    if dropped != candidate:
        stages.append("trailing_comma")
        candidate = dropped
        result = _attempt()
        if result is not None:
            return result

    # 4) 全角引号归一（末级兜底）
    quoted = normalize_fullwidth_quotes(candidate)
    if quoted != candidate:
        stages.append("fullwidth_quotes")
        candidate = quoted
        result = _attempt()
        if result is not None:
            return result

    return JsonRepair(data=None, stages=tuple(stages), error=last_error)


def repair_json_object(raw: str) -> JsonRepair:
    """``repair_json`` 的 dict-only 包装（视觉/文本解析链均要求对象输出）。"""
    result = repair_json(raw)
    if result.data is not None and not isinstance(result.data, dict):
        return JsonRepair(
            data=None,
            stages=result.stages,
            error=f"expected JSON object, got {type(result.data).__name__}",
        )
    return result
