"""①主链/复核员 prompt 的 md 化加载器（P1-3 E4 skills 化）。

设计（对齐 business_agent domain_prompts 先例 + 硬护栏留代码拍板）：

- md 文件位于 ``ai_hazard_identification/prompt_skills/<name>.md``，frontmatter
  三段式（``version`` 必填），body 即 prompt 块正文（逐字节）；
- **md 缺失/损坏一律回落调用方内置兜底常量**（离线可用、删除 md 即回滚）；
- mtime 缓存热更新：文件未变走缓存，改动后下次读取生效（无需重启）；
- 硬护栏（CRITICAL_CONSTRAINTS / OUTPUT_FORMAT / 引用强校验）**不经本加载器**，
  留在代码里——安全管理员改 md 只影响软性措辞，改不动输出 schema 与门禁。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROMPT_SKILLS_DIR = Path(__file__).parent / "prompt_skills"

# name -> (mtime_ns, version, body) 进程内缓存（mtime 未变不重读）
_cache: dict[str, tuple[int, str, str]] = {}


def _parse_md(raw: str) -> tuple[str, str]:
    """解析 md：frontmatter version + body。无/非法 frontmatter 时
    version 为空串、body 为原文（调用方回落兜底或直接用原文）。"""
    if not raw.startswith("---"):
        return "", raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return "", raw
    version = ""
    for line in parts[1].strip().splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "version":
            version = value.strip().strip('"').strip("'")
            break
    body = parts[2]
    # 去掉 frontmatter 结束标记后的第一个换行（写文件约定 ---\n<body>）
    if body.startswith("\n"):
        body = body[1:]
    return version, body


def _load(name: str) -> tuple[str, str] | None:
    """读 md 并维护 mtime 缓存；文件缺失返回 None。"""
    path = PROMPT_SKILLS_DIR / f"{name}.md"
    try:
        stat = path.stat()
    except OSError:
        _cache.pop(name, None)
        return None
    cached = _cache.get(name)
    if cached is not None and cached[0] == stat.st_mtime_ns:
        return cached[1], cached[2]
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("prompt md 读取失败: %s", path, exc_info=True)
        return None
    version, body = _parse_md(raw)
    _cache[name] = (stat.st_mtime_ns, version, body)
    return version, body


def load_text_block(name: str, *, fallback: str) -> str:
    """文本块：md 存在且非空 → body；否则 → fallback（内置常量）。"""
    loaded = _load(name)
    if loaded is None:
        return fallback
    _version, body = loaded
    if not version_ok(loaded[0]) or not body.strip():
        return fallback
    return body


def load_json_block(name: str, *, fallback: Any) -> Any:
    """JSON 块（few-shot 示例等）：解析失败回落 fallback。"""
    loaded = _load(name)
    if loaded is None:
        return fallback
    _version, body = loaded
    if not body.strip():
        return fallback
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        logger.warning("prompt md JSON 块解析失败，回落兜底: %s", name)
        return fallback


def block_version(name: str) -> str:
    """块版本号（frontmatter version）；缺失/未加载 → "fallback"。"""
    loaded = _load(name)
    if loaded is None:
        return "fallback"
    version, body = loaded
    if not version_ok(version) or not body.strip():
        return "fallback"
    return version


def version_ok(version: str) -> bool:
    return bool(version and version.strip())

# few-shot 单文件内 marker 与 JSON 的分隔标记（拍板⑤：不单独拆文件）
FEWSHOT_JSON_SEP = "<!-- FEWSHOT_JSON -->"


def load_fewshot(
    *, fallback_marker: str, fallback_examples: Any
) -> tuple[str, Any]:
    """few-shot 成对加载：单 md 内「marker 文本 + 分隔标记 + JSON 数组」。

    拆分保持逐字节还原（marker 去 1 个尾换行 / JSON 去 1 个首换行），
    md 缺失/损坏/分隔标记缺失 → 整体回落兜底常量。
    """
    loaded = _load("fewshot")
    if loaded is None:
        return fallback_marker, fallback_examples
    _version, body = loaded
    if FEWSHOT_JSON_SEP not in body:
        return fallback_marker, fallback_examples
    marker, _, json_part = body.partition(FEWSHOT_JSON_SEP)
    marker = marker[:-1] if marker.endswith("\n") else marker
    json_part = json_part[1:] if json_part.startswith("\n") else json_part
    if not marker.strip() or not json_part.strip():
        return fallback_marker, fallback_examples
    try:
        examples = json.loads(json_part)
    except (TypeError, ValueError):
        logger.warning("fewshot md JSON 解析失败，回落兜底")
        return fallback_marker, fallback_examples
    return marker, examples

