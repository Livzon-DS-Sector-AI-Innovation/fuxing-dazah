"""P2-3 E19 —— ①主链知识注入段 per-chunk 句子边界截断。

设计要点（.scratch/hazard-cost-p23/spec.md）：
- 输入 ``KnowledgeContext``（不解析 markdown 字符串），按
  ``SafetyKnowledgeRetriever.build_markdown`` 同款格式重建注入文本，每 chunk
  正文截断至 ``max_chunk_chars``；
- 0 = 关闭：原样返回 ``context.markdown``（身份语义，热回滚零成本）；
- 截断点必在句末标点后；含法规引用（书名号/标准号/条号——判定复用
  ``citations.has_citation`` 唯一事实源）的句子**永不丢弃**：引用可用性优先
  于预算，C2 引用强约束的注入面不因压缩缩水；
- chunk 元数据头行（``[i] 《法规》 条号``）与 graph_path 原样保留，不占正文
  预算；
- chunks 集合与 ``CitationEvidence`` 不动：本模块只产注入文本，不改检索结果
  对象，质量闸门/引用校验输入语义零变化。

仅 ① 识别主链接入（``ai_analysis._identify_one``）；② 初审与例外复核员共享
本压缩器但暂不接入（spec 范围决策）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.modules.safety.ai_hazard_identification.citations import has_citation

if TYPE_CHECKING:
    from app.modules.safety.knowledge.retriever import KnowledgeContext

__all__ = [
    "compress_knowledge_context",
    "injection_markdown",
    "knowledge_context_max_chars",
]

# 句末边界：中文句读 + 换行（句子在此处完整结束，截断不会切半个句子）
_SENTENCE_BOUNDARIES = "。；？！\n"

# app_config 键（registry 已注册：int，默认 200，0=off，热生效）
# 默认值拍板（2026-11-10）：离线四象限度量 350→-22.6% 未达标 / 250→-28.0% /
# 200→-30.6% 冲刺达成，且 30 样本条号头行 0 丢失、引用句永不丢（单测锁）。
_MAX_CHARS_KEY = "SAFETY_HAZARD_KNOWLEDGE_CONTEXT_MAX_CHARS"
_DEFAULT_MAX_CHARS = 200

# 截断标记（模型可见的省略号，表明条文有删节）
_ELLIPSIS = "……"


def knowledge_context_max_chars() -> int:
    """per-chunk 截断上限（app_config 热生效；0 = 关闭截断）。"""
    from app.modules.safety.app_config.store import store as config_store

    return config_store.get_int(_MAX_CHARS_KEY, _DEFAULT_MAX_CHARS, minimum=0)


def _split_sentences(text: str) -> list[str]:
    """按句末标点切句（边界字符保留在句尾，join 后与原文逐字节一致）。"""
    sentences: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in _SENTENCE_BOUNDARIES:
            sentences.append("".join(buf))
            buf = []
    if buf:
        sentences.append("".join(buf))
    return sentences


def _truncate_body(text: str, max_chars: int) -> str:
    """单 chunk 正文截断。

    保留规则（按序判定，确定性）：
    1. 引用句（has_citation）永远保留——引用可用性优先于预算；
    2. 预算内（累计长度 + 句长 ≤ max_chars）保留；
    3. 首句保底：即使超预算也整句保留（不可句中切，防空 chunk）。
    发生丢弃时追加省略号标记。
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    kept: list[str] = []
    used = 0
    dropped = False
    for sentence in _split_sentences(text):
        if has_citation(sentence) or not kept or used + len(sentence) <= max_chars:
            kept.append(sentence)
            used += len(sentence)
        else:
            dropped = True
    return "".join(kept) + (_ELLIPSIS if dropped else "")


def compress_knowledge_context(
    context: KnowledgeContext, *, max_chunk_chars: int
) -> str:
    """重建压缩后的注入 markdown（与 build_markdown 同款格式）。

    - ``max_chunk_chars <= 0`` 或空 chunks → 原样返回 ``context.markdown``；
    - graph_path 与 chunk 头行原样保留；正文按句截断、引用句不丢。
    """
    chunks = list(context.chunks or [])
    if max_chunk_chars <= 0 or not chunks:
        return context.markdown

    parts: list[str] = []
    if context.graph_path:
        parts.append(context.graph_path)

    chunk_blocks: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        ref = f"《{chunk.source_doc}》"
        if chunk.source_article:
            ref += f" {chunk.source_article}"
        body = _truncate_body(chunk.chunk_text, max_chunk_chars)
        chunk_blocks.append(f"[{i}] {ref}\n{body}")
    parts.append("## 相关法规条款\n\n" + "\n\n---\n\n".join(chunk_blocks))
    return "\n\n".join(parts)


def injection_markdown(context: KnowledgeContext) -> str:
    """①主链接入口：读配置截断上限后压缩（0=off 原样透传）。"""
    return compress_knowledge_context(
        context, max_chunk_chars=knowledge_context_max_chars()
    )
