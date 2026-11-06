"""① 多路检索接线单测（P1-1 R1/R2，S2 接缝）。

monkeypatch ``SafetyKnowledgeRetriever``（``ai_analysis`` 延迟 import 在调用时解析）：
- 开关开（默认）：逐路检索（每路 CANDIDATES）+ 客户端 RRF 合并取 TOP_K；
- 开关关：单路原语义（描述原文 + TOP_K，与现状行为等价）；
- 辅路异常不吞主路；主路异常整体失败（收敛 None，闸门判 retrieval_degraded）；
- LLM 改写默认关，不产生额外 AI 调用。
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from app.modules.safety.knowledge.retriever import (
    KnowledgeContext,
    RetrievalResult,
)
from app.modules.safety.service.hazard_direct import (
    ai_analysis,
)
from app.modules.safety.service.hazard_direct import (
    retrieval_query as rq,
)


def _chunk(chunk_id: str, doc: str, text: str = "条文") -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        chunk_text=text,
        source_doc=doc,
        source_article="第1条",
        doc_category="laws_regulations",
        priority="P1",
        score=0.9,
    )


def _ctx(chunks: list[RetrievalResult], degradation: str = "ragplus") -> KnowledgeContext:
    return KnowledgeContext(
        chunks=chunks, graph_path=None, article_ids=[], markdown="", degradation=degradation,
    )


class _FakeRetriever:
    """按 query 返回预设上下文；query 未预设时返回空上下文。"""

    def __init__(
        self,
        session: Any,
        routes: dict[str, KnowledgeContext | Exception] | None = None,
    ) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, int]] = []

    async def retrieve(
        self,
        description: str = "",
        categories: list[str] | None = None,
        target_chunks: int = 8,
        max_hops: int = 2,
    ) -> KnowledgeContext:
        self.calls.append((description, target_chunks))
        if description not in self.routes:
            return _ctx([])
        result = self.routes[description]
        if isinstance(result, Exception):
            raise result
        return result


def _wire_retriever(monkeypatch: pytest.MonkeyPatch, routes: dict[str, Any]) -> _FakeRetriever:
    fake = _FakeRetriever(session=None, routes=routes)
    monkeypatch.setattr(
        "app.modules.safety.knowledge.retriever.SafetyKnowledgeRetriever",
        lambda session: fake,
    )
    return fake


class TestMultiQueryWiring:
    async def test_multi_on_merges_routes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        description = "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        plan = rq.build_retrieval_queries(description)
        assert len(plan.queries) == 2  # 前置：该描述确实产出两路

        routes = {
            plan.queries[0]: _ctx([_chunk("c-1", "《主路文档》")]),
            plan.queries[1]: _ctx([_chunk("c-2", "《关键词路文档》")]),
        }
        fake = _wire_retriever(monkeypatch, routes)

        context, meta = await ai_analysis._load_knowledge_context(None, description)

        assert context is not None
        docs = {c.source_doc for c in context.chunks}
        assert docs == {"《主路文档》", "《关键词路文档》"}
        # 每路候选数 = CANDIDATES（默认 12）
        assert [c[1] for c in fake.calls] == [12, 12]
        assert meta is not None
        assert meta.multi_query_count == 2
        assert meta.rewrite_hit is False
        assert meta.docs == ("《主路文档》", "《关键词路文档》")

    async def test_multi_off_single_route_byte_equivalent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAFETY_HAZARD_MULTI_QUERY_ENABLED", "false")
        description = "10月5日检查发现：3号罐区静电跨接断裂"
        routes = {description: _ctx([_chunk("c-1", "《原文直查文档》")])}
        fake = _wire_retriever(monkeypatch, routes)

        context, meta = await ai_analysis._load_knowledge_context(None, description)

        # 原文直查、top_k=8（与改造前硬编码一致）——逐字节等价
        assert fake.calls == [(description, 8)]
        assert context is not None and len(context.chunks) == 1
        assert meta is not None and meta.multi_query_count == 1
        assert meta.queries == (description,)

    async def test_aux_route_exception_does_not_swallow_primary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        description = "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        plan = rq.build_retrieval_queries(description)
        routes = {
            plan.queries[0]: _ctx([_chunk("c-1", "《主路文档》")]),
            plan.queries[1]: RuntimeError("辅路引擎超时"),
        }
        _wire_retriever(monkeypatch, routes)

        context, meta = await ai_analysis._load_knowledge_context(None, description)

        assert context is not None
        assert [c.source_doc for c in context.chunks] == ["《主路文档》"]
        assert context.degradation == "ragplus"  # 主路 degradation 决定闸门输入
        assert meta is not None and meta.docs == ("《主路文档》",)

    async def test_primary_route_exception_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        description = "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        plan = rq.build_retrieval_queries(description)
        routes = {
            plan.queries[0]: RuntimeError("ragplus 不可用"),
            plan.queries[1]: _ctx([_chunk("c-2", "《辅路》")]),
        }
        _wire_retriever(monkeypatch, routes)

        context, meta = await ai_analysis._load_knowledge_context(None, description)
        assert context is None
        assert meta is None

    async def test_primary_degradation_propagates_to_merged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """主路降级（ragplus_unavailable）→ 合并上下文降级 → 闸门判失败（语义不变）。"""
        description = "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        plan = rq.build_retrieval_queries(description)
        routes = {
            plan.queries[0]: _ctx([], degradation="ragplus_unavailable"),
            plan.queries[1]: _ctx([_chunk("c-2", "《辅路健康文档》")]),
        }
        _wire_retriever(monkeypatch, routes)

        context, _meta = await ai_analysis._load_knowledge_context(None, description)
        assert context is not None
        assert context.degradation == "ragplus_unavailable"
        # 闸门行为不变：降级上下文仍被 ensure_knowledge 拒绝
        from app.modules.safety.service.hazard_direct import quality_gate

        with pytest.raises(quality_gate.QualityGateError) as exc_info:
            quality_gate.ensure_knowledge(context)
        assert exc_info.value.category == quality_gate.RETRIEVAL_DEGRADED

    async def test_llm_rewrite_off_by_default_no_extra_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        description = "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        plan = rq.build_retrieval_queries(description)
        routes = {q: _ctx([_chunk(f"c-{i}", f"《文档{i}》")]) for i, q in enumerate(plan.queries)}
        fake = _wire_retriever(monkeypatch, routes)

        called: list[str] = []

        async def _spy(query: str) -> str | None:
            called.append(query)
            return None

        monkeypatch.setattr(rq, "llm_rewrite_query", _spy)

        await ai_analysis._load_knowledge_context(None, description)
        assert called == []  # 默认关：不发起 LLM 改写
        assert len(fake.calls) == len(plan.queries)

    async def test_llm_rewrite_on_appends_route(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAFETY_HAZARD_QUERY_LLM_REWRITE_ENABLED", "true")
        description = "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        plan = rq.build_retrieval_queries(description)

        async def _fake_rewrite(query: str) -> str | None:
            return "配电箱 未封堵 消防通道 占用 隐患排查"

        monkeypatch.setattr(rq, "llm_rewrite_query", _fake_rewrite)
        routes = {
            q: _ctx([_chunk(f"c-{i}", f"《文档{i}》")])
            for i, q in enumerate((*plan.queries, "配电箱 未封堵 消防通道 占用 隐患排查"))
        }
        fake = _wire_retriever(monkeypatch, routes)

        context, meta = await ai_analysis._load_knowledge_context(None, description)
        assert context is not None
        assert len(fake.calls) == len(plan.queries) + 1  # 改写路追加
        assert meta is not None and meta.multi_query_count == len(plan.queries) + 1

    async def test_candidates_top_k_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SAFETY_HAZARD_RETRIEVAL_CANDIDATES", "15")
        monkeypatch.setenv("SAFETY_HAZARD_RETRIEVAL_TOP_K", "5")
        description = "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        plan = rq.build_retrieval_queries(description)
        routes = {q: _ctx([_chunk(f"c-{i}-{j}", f"《文档{i}-{j}》") for j in range(10)])
                  for i, q in enumerate(plan.queries)}
        fake = _wire_retriever(monkeypatch, routes)

        context, _meta = await ai_analysis._load_knowledge_context(None, description)
        assert context is not None
        assert [c[1] for c in fake.calls] == [15, 15]
        assert len(context.chunks) == 5  # TOP_K=5


class TestRetrievalObservabilityWiring:
    """检索维度 → 审计 extra（T03）：与引用质量维度同链路合并。"""

    @staticmethod
    def _capture_mark(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        async def _fake_mark(fields: dict[str, Any]) -> None:
            captured.update(fields)

        monkeypatch.setattr(
            "app.modules.safety.ai_audit.audited_client.mark_audit_extra", _fake_mark
        )
        return captured

    async def test_record_citation_quality_merges_retrieval_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture_mark(monkeypatch)
        plugin = types.SimpleNamespace(last_citation_report=None)
        meta = rq.RetrievalMeta(
            query="主路查询",
            queries=("主路查询", "关键词 查询"),
            rewrite_hit=True,
            docs=("《文档A》",),
        )

        await ai_analysis._record_citation_quality(
            plugin, None, strict=True, retrieval_meta=meta
        )

        # 引用维度（既有）与检索维度（新）合并在同一次 mark_audit_extra
        assert captured["citation_strict"] is True
        assert captured["retrieval_query"] == "主路查询"
        assert captured["multi_query_count"] == 2
        assert captured["rewrite_hit"] is True

    async def test_record_without_meta_keeps_citation_fields_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture_mark(monkeypatch)
        plugin = types.SimpleNamespace(last_citation_report=None)

        await ai_analysis._record_citation_quality(
            plugin, None, strict=True, retrieval_meta=None
        )

        assert captured["citation_strict"] is True
        assert "retrieval_query" not in captured
