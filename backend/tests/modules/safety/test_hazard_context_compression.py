"""P2-3 T02 知识注入段 per-chunk 截断 —— ①主链上下文压缩（E19）。

S2 纯函数（context_compression）：
- 0 = 关闭截断，原样返回 context.markdown（身份语义）；
- 空 chunks → 原样返回（占位语义不重写）；
- 全部句子在预算内 → 与注入格式契约（_expected_markdown 字面实现）逐字节一致
  （重建格式不变式）；
- 超预算 → 截断点必在句末标点后、带截断标记、总长受控；
- 含条号/法规引用的句子永不丢弃（引用可用性优先于预算）；
- chunk 元数据头行（[i] 《法规》 条号）与 graph_path 原样保留。

S1 wiring（_identify_one 注入点）：
- 截断开启 → plugin 收到的 knowledge_context 为压缩文本，CitationEvidence
  仍从完整 chunks 构建（引用验证语义零变化）；
- 截断关闭（0）→ 原始 markdown 逐字节透传。

全部 fake：不连真实网络 / DB / Redis / Bitable / 文件系统 / AI。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.knowledge.retriever import KnowledgeContext
from app.modules.safety.service.hazard_direct import (
    ai_analysis,
    bitable_repo,
    context_compression,
)

MAX_CHARS_KEY = "SAFETY_HAZARD_KNOWLEDGE_CONTEXT_MAX_CHARS"


def _expected_markdown(chunks: list[Any], graph_path: str | None = None) -> str:
    """注入格式契约的**本地**字面实现（parity 基准）。

    不调 retriever 的 build_markdown：该方法在 HEAD 为私有 ``_build_markdown``、
    在未提交 WIP 中改名公开——依赖任一名字都会绑死他人 hunk。格式契约由此处
    字面锁死，截断器重建漂移在此可测；retriever 侧格式变更由其 own 测试守护。
    """
    parts: list[str] = []
    if graph_path:
        parts.append(graph_path)
    blocks: list[str] = []
    for i, c in enumerate(chunks, 1):
        ref = f"《{c.source_doc}》"
        if c.source_article:
            ref += f" {c.source_article}"
        blocks.append(f"[{i}] {ref}\n{c.chunk_text}")
    parts.append("## 相关法规条款\n\n" + "\n\n---\n\n".join(blocks))
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# 样本构造
# ═══════════════════════════════════════════════════════════════


def _chunk(chunk_id: str, doc: str, article: str, text: str) -> Any:
    """duck 形态检索结果（与 efficiency_wiring 先例同款规避 list-item 噪声）。"""
    return SimpleNamespace(
        chunk_id=chunk_id, source_doc=doc, source_article=article, chunk_text=text,
    )


SHORT_CHUNK = _chunk(
    "c1", "消防法", "第十条",
    "第十条 应设置防护栏杆。栏杆高度不低于1.1米。",
)
LONG_BODY_SENTENCES = [
    "第五条 生产经营单位应当具备安全生产条件。",
    "生产经营单位的主要负责人对本单位的安全生产工作全面负责。",
    "各单位应当建立健全全员安全生产责任制。",
    "第六条 生产经营单位应当对从业人员进行安全生产教育培训。",
    "从业人员经培训合格后方可上岗作业。",
    "培训情况应当记录并存档备查。",
]
# 远端条号句（构造在预算之外，验证条号句永不丢弃）
LONG_CHUNK = _chunk(
    "c2", "安全生产法", "第五条", "。".join(LONG_BODY_SENTENCES) + "。",
)
CITATION_LATE_CHUNK = _chunk(
    "c3", "GB 30871-2022", "第5.2条",
    "高处作业应有防护。" * 60 + "GB 30871-2022 第5.2条：高处作业应正确佩戴安全带。",
)


# ═══════════════════════════════════════════════════════════════
# S2 纯函数
# ═══════════════════════════════════════════════════════════════


def test_zero_disables_truncation_identity() -> None:
    ctx = KnowledgeContext(chunks=[LONG_CHUNK], markdown="## 相关法规条款\n\n原始")
    out = context_compression.compress_knowledge_context(ctx, max_chunk_chars=0)
    assert out is ctx.markdown, "0 必须原样返回（身份语义，非重建）"


def test_empty_chunks_unchanged() -> None:
    ctx = KnowledgeContext(chunks=[], markdown="（知识库中暂无与查询相关的法规条款）")
    out = context_compression.compress_knowledge_context(ctx, max_chunk_chars=350)
    assert out == ctx.markdown


def test_within_budget_equals_build_markdown() -> None:
    """预算内：重建结果与注入格式契约（_expected_markdown）逐字节一致。"""
    ctx = KnowledgeContext(
        chunks=[SHORT_CHUNK],
        markdown=_expected_markdown([SHORT_CHUNK]),
    )
    out = context_compression.compress_knowledge_context(ctx, max_chunk_chars=350)
    assert out == _expected_markdown([SHORT_CHUNK])


def test_truncation_at_sentence_boundary_with_marker() -> None:
    ctx = KnowledgeContext(chunks=[LONG_CHUNK], markdown="orig")
    out = context_compression.compress_knowledge_context(ctx, max_chunk_chars=30)
    body = out.split("\n", 1)[1]  # 首行是 [1] 《安全生产法》 第五条
    # 截断标记存在
    assert "……" in body
    # 保留的每个句子都在句末标点处结束（无半个句子）
    kept = body.replace("……", "").strip()
    assert kept, "至少保留一个句子"
    assert kept.endswith(("。", "；", "！", "？")), kept
    # 非条号句子受预算约束（30 字预算下不可能装下全部六个句子）
    assert len(kept) < len("。".join(LONG_BODY_SENTENCES))


def test_citation_sentence_never_dropped() -> None:
    """条号/引用句在预算外也必须保留（引用可用性优先于预算）。"""
    ctx = KnowledgeContext(chunks=[CITATION_LATE_CHUNK], markdown="orig")
    out = context_compression.compress_knowledge_context(ctx, max_chunk_chars=10)
    assert "第5.2条" in out, "条号句被预算丢弃"
    assert "正确佩戴安全带" in out, "引用句正文被预算丢弃"


def test_header_and_graph_path_preserved() -> None:
    graph = "## 图谱导航\n\nA → B"
    ctx = KnowledgeContext(
        chunks=[SHORT_CHUNK],
        markdown=_expected_markdown([SHORT_CHUNK], graph),
        graph_path=graph,
    )
    out = context_compression.compress_knowledge_context(ctx, max_chunk_chars=350)
    assert out.startswith(graph), "graph_path 必须原样保留在前"
    assert "[1] 《消防法》 第十条" in out, "chunk 元数据头行必须完整"


# ═══════════════════════════════════════════════════════════════
# S1 wiring（_identify_one 注入点）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _ragplus_on(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.modules.safety.knowledge.ragplus_client as ragplus_client

    monkeypatch.setattr(ragplus_client, "ragplus_search_enabled", lambda: True)


@pytest.fixture()
def wiring(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """复刻 efficiency_wiring 的 _identify_one fake 全家桶（最小集）。"""
    holder = SimpleNamespace(plugins=[], evidence=None)
    long_ctx = KnowledgeContext(
        chunks=[LONG_CHUNK, CITATION_LATE_CHUNK],
        markdown=_expected_markdown([LONG_CHUNK, CITATION_LATE_CHUNK]),
        degradation="ragplus",
    )

    async def fake_load(session: Any, description: str) -> tuple[KnowledgeContext | None, None]:
        return long_ctx, None

    monkeypatch.setattr(ai_analysis, "_load_knowledge_context", fake_load)

    import app.core.database as database

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[Any]:
        yield object()

    monkeypatch.setattr(database, "async_session_factory", fake_session)

    async def fake_download(client: Any, fields: Any, *, record_id: str,
                            include_rectification: bool = True) -> dict[str, list[str]]:
        return {"defect": [], "rectification": []}

    monkeypatch.setattr(bitable_repo, "download_photos", fake_download)

    monkeypatch.setattr(bitable_repo, "photos_to_data_uris", lambda paths: [])

    import app.modules.safety.ai_hazard_identification as pkg

    class FakeIdentifier:
        def __init__(self, ai_service: Any, plugin_config: Any = None,
                     knowledge_context: str | None = None,
                     citation_evidence: Any = None, **kwargs: Any) -> None:
            self.knowledge_context = knowledge_context
            self.citation_evidence = citation_evidence
            holder.plugins.append(self)

        async def identify(self, input_data: Any) -> Any:
            return SimpleNamespace(
                key_defect="测试",
                hazard_type=SimpleNamespace(value="unsafe_condition"),
                hazard_category=SimpleNamespace(value="instrument_electrical"),
                hazard_level=SimpleNamespace(value="general"),
                major_hazard_basis="《安全生产法》第五条：'句原文'",
                defect_substance=SimpleNamespace(value="substantive"),
                defect_substance_reasoning="两步物理必然推断链",
                rectification_suggestion=SimpleNamespace(
                    corrective="整改" * 30, preventive="预防" * 30,
                ),
            )

    monkeypatch.setattr(pkg, "AIHazardIdentifier", FakeIdentifier)
    holder.long_ctx = long_ctx
    return holder


def _view() -> Any:
    return SimpleNamespace(
        record_id="recT02", hazard_no=None, description="防爆电箱引入口未封堵",
        department="生产一部", discovered_at="2026-11-10",
        raw={"隐患描述": "防爆电箱引入口未封堵"},
    )


async def test_wiring_compressed_injected_evidence_intact(
    wiring: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """截断开启：plugin 收到压缩文本；引用证据仍来自完整 chunks。"""
    monkeypatch.setenv(MAX_CHARS_KEY, "60")
    await ai_analysis._identify_one(object(), _view())
    plugin = wiring.plugins[-1]

    assert plugin.knowledge_context is not None
    assert plugin.knowledge_context != wiring.long_ctx.markdown, "未压缩即注入"
    assert len(plugin.knowledge_context) < len(wiring.long_ctx.markdown)
    assert "第5.2条" in plugin.knowledge_context, "条号句被截断丢弃"

    # 引用证据：完整 chunks 构建（两个 chunk、正文未截断）
    assert plugin.citation_evidence is not None
    entries = plugin.citation_evidence.entries
    assert len(entries) == 2
    assert entries[0].chunk_text == wiring.long_ctx.chunks[0].chunk_text


async def test_wiring_zero_passes_original_through(
    wiring: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """截断关闭：原始 markdown 逐字节透传。"""
    monkeypatch.setenv(MAX_CHARS_KEY, "0")
    await ai_analysis._identify_one(object(), _view())
    plugin = wiring.plugins[-1]
    assert plugin.knowledge_context == wiring.long_ctx.markdown
