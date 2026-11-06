"""正文引用编号 [N] → sources 文档的解析（标题锚定）。

2026-11-06 阻火器引用事故：一轮并行多次 knowledge_search 各自独立编号，
模型合并转述必然全局重编号，旧「[N]=sources[N-1] 位置契约」在该场景
必然错位。模型转述时会把 [N] 紧放在文档名旁（自然行为 + 工具 docstring
契约），据此做归一化标题匹配（knowledge/title_match.py：标准号+名称
双键）解析编号——天然免疫重编号与多调用合并。

消费方：
- 飞书卡片：feishu/business_agent_bot_handler._build_reply_card（参考法规栏）
- Web API：api/business_agent（sources 附 cite_no，前端徽标与正文 [N] 对齐）
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.safety.knowledge.title_match import titles_match

# 《文档名》…[N]（中间 ≤40 字符，容纳书名号外的标准号/括注）
_TITLE_FWD_RE = re.compile(r"《([^》]{2,80})》([^\[\]《》\n]{0,40})\[(\d+)\]")
# [N]…《文档名》（编号前置，中间更短）
_TITLE_REV_RE = re.compile(r"\[(\d+)\]([^\[\]《》\n]{0,10})《([^》]{2,80})》")

_BARE_NO_RE = re.compile(r"\[(\d+)\]")


def dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 doc_title 去重（首轮出现为准）。"""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for s in sources:
        title = s.get("doc_title", "未知文档")
        if title not in seen:
            seen.add(title)
            unique.append(s)
    return unique


def resolve_citations(
    answer_text: str, sources: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    """把正文 [N] 解析到具体 source（标题锚定优先，单源位置映射兜底）。

    Returns:
        [(编号, source)] 按编号升序；无法解析的编号宁缺毋错（不渲染）。
    """
    unique_sources = dedupe_sources(sources)

    anchors: list[tuple[int, str]] = []
    for m in _TITLE_FWD_RE.finditer(answer_text):
        anchors.append((int(m.group(3)), f"{m.group(1)}{m.group(2)}"))
    for m in _TITLE_REV_RE.finditer(answer_text):
        anchors.append((int(m.group(1)), f"{m.group(3)}{m.group(2)}"))

    resolved: dict[int, dict[str, Any]] = {}
    # 两轮：全等优先、互含次之；同编号首次配对为准
    for containment in (False, True):
        for n, anchor in anchors:
            if n in resolved:
                continue
            for s in unique_sources:
                if titles_match(anchor, s.get("doc_title", ""), containment=containment):
                    resolved[n] = s
                    break

    # 兜底：sources 仅 1 篇时编号无歧义，正文裸 [1] 按位置映射
    if len(unique_sources) == 1 and 1 not in resolved:
        if _BARE_NO_RE.search(answer_text):
            resolved[1] = unique_sources[0]

    return sorted(resolved.items())


def order_sources_for_answer(
    answer_text: str, sources: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """按正文引用解析结果重排 sources 并附 ``cite_no``（Web API 用）。

    未被正文引用的 source 保留在尾部（不编号）——供「知识库还检索到了什么」
    场景展示，前端徽标对 cite_no 缺省回退列表序号。
    """
    if not sources:
        return []
    cited = resolve_citations(answer_text, sources)
    cited_titles = {id(s) for _, s in cited}
    out: list[dict[str, Any]] = []
    for n, s in cited:
        item = dict(s)
        item["cite_no"] = n
        out.append(item)
    for s in dedupe_sources(sources):
        if id(s) not in cited_titles:
            out.append(dict(s))
    return out
