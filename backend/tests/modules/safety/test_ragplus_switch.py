"""三壳 ragplus 开关分支单测 — 接缝：壳公开方法（假 client 注入）。

只测外部行为：开关关=旧本地路径（不触碰 ragplus 工厂）；开关开=检索
结果来自 ragplus 且字段映射正确；不可用=聊天话术/管线标注/直用方抛错。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.safety.knowledge import cache as rag_cache
from app.modules.safety.knowledge import retriever as rag_retriever
from app.modules.safety.knowledge.query_service import (
    RAGPLUS_UNAVAILABLE_ANSWER,
    run_knowledge_chat,
)
from app.modules.safety.knowledge.ragplus_client import (
    RagplusHit,
    RagplusUnavailableError,
)
from app.modules.safety.knowledge.retriever import (
    HybridRetriever,
    KnowledgeContext,
    SafetyKnowledgeRetriever,
)

_SWITCH = "SAFETY_RAGPLUS_SEARCH_ENABLED"


def _hit(**kw) -> RagplusHit:
    defaults: dict = dict(
        chunk_id="ck-1",
        content="第三条 动火作业应当办理作业票，作业前进行气体分析。",
        doc_name="GB 30871-2022 危险化学品企业特殊作业安全规范.pdf",
        document_id="doc-1",
        dataset_id="ds-law",
        page=12,
        similarity=0.83,
        highlight="",
    )
    defaults.update(kw)
    return RagplusHit(**defaults)


def _fake_client(hits: list[RagplusHit] | None = None, error: Exception | None = None):
    client = MagicMock()
    if error is not None:
        client.search = AsyncMock(side_effect=error)
    else:
        client.search = AsyncMock(return_value=hits or [])
    return client


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch):
    """RAG/chat 缓存隔离：读恒 MISS、写丢弃（跨测试不串味）。"""
    monkeypatch.setattr(rag_cache, "get_rag_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(rag_cache, "set_rag_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(rag_cache, "get_chat_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(rag_cache, "set_chat_cache", AsyncMock(return_value=None))
    monkeypatch.delenv(_SWITCH, raising=False)
    yield


class TestSafetyKnowledgeRetrieverSwitch:
    async def test_switch_off_uses_local_pipeline(
        self, db_session, monkeypatch
    ) -> None:
        """开关关：走旧本地路径（空索引→fallback），绝不触碰 ragplus 工厂。"""
        monkeypatch.setattr(
            rag_retriever,
            "get_ragplus_client",
            lambda: pytest.fail("开关关闭时不应构建 ragplus 客户端"),
        )
        retriever = SafetyKnowledgeRetriever(db_session)
        ctx = await retriever.retrieve("防爆电箱堵头未封堵", target_chunks=4)
        assert ctx.degradation not in ("ragplus", "ragplus_unavailable")
        assert ctx.chunks == []

    async def test_switch_on_returns_ragplus_context(
        self, db_session, monkeypatch
    ) -> None:
        """开关开：跳过本地图谱层，返回 ragplus 映射上下文（法规名+条款定位）。"""
        monkeypatch.setenv(_SWITCH, "true")
        client = _fake_client([_hit()])
        monkeypatch.setattr(rag_retriever, "get_ragplus_client", lambda: client)

        retriever = SafetyKnowledgeRetriever(db_session)
        ctx = await retriever.retrieve("动火作业要办什么手续", target_chunks=5)

        assert ctx.degradation == "ragplus"
        client.search.assert_awaited_once_with("动火作业要办什么手续", top_k=5)
        chunk = ctx.chunks[0]
        assert chunk.source_doc == "GB 30871-2022 危险化学品企业特殊作业安全规范"
        assert chunk.source_article == "第三条"
        assert chunk.vector_score == pytest.approx(0.83)
        assert chunk.retrieval_path == "ragplus"
        assert "第三条" in ctx.markdown and "GB 30871" in ctx.markdown

    async def test_switch_on_ref_falls_back_to_page(
        self, db_session, monkeypatch
    ) -> None:
        """片段无条款号时，条款定位兜底页码。"""
        monkeypatch.setenv(_SWITCH, "true")
        hit = _hit(content="作业前应对作业区域进行可燃气体检测。", page=7)
        monkeypatch.setattr(
            rag_retriever,
            "get_ragplus_client",
            lambda: _fake_client([hit]),
        )
        ctx = await SafetyKnowledgeRetriever(db_session).retrieve(
            "动火检测", target_chunks=3
        )
        assert ctx.chunks[0].source_article == "第7页"

    async def test_rerank_scale_similarity_normalized(
        self, db_session, monkeypatch
    ) -> None:
        """引擎 rerank 分为 0~10 量纲：vector_score 归一到 0~1 对齐 0.55 阈值。"""
        monkeypatch.setenv(_SWITCH, "true")
        hit = _hit(similarity=5.453)
        monkeypatch.setattr(
            rag_retriever,
            "get_ragplus_client",
            lambda: _fake_client([hit]),
        )
        ctx = await SafetyKnowledgeRetriever(db_session).retrieve(
            "rerank量纲", target_chunks=3
        )
        assert ctx.chunks[0].vector_score == pytest.approx(0.5453)
        assert ctx.chunks[0].score == pytest.approx(5.453)  # 原始分保留

    async def test_unavailable_context_is_not_cached(
        self, db_session, monkeypatch
    ) -> None:
        """故障态不写缓存：ragplus 恢复后同查询必须立即可用（不等 TTL）。"""
        monkeypatch.setenv(_SWITCH, "true")
        monkeypatch.setattr(
            rag_retriever,
            "get_ragplus_client",
            lambda: _fake_client(error=RagplusUnavailableError("连接失败")),
        )
        retriever = SafetyKnowledgeRetriever(db_session)
        ctx = await retriever.retrieve("不可用不应缓存查询", target_chunks=4)
        assert ctx.degradation == "ragplus_unavailable"
        rag_cache.set_rag_cache.assert_not_awaited()

    async def test_switch_on_unavailable_returns_annotated_context(
        self,
        db_session,
        monkeypatch,
    ) -> None:
        """ragplus 不可用：管线消费方拿到显式标注空上下文（不静默无依据）。"""
        monkeypatch.setenv(_SWITCH, "true")
        monkeypatch.setattr(
            rag_retriever,
            "get_ragplus_client",
            lambda: _fake_client(error=RagplusUnavailableError("连接失败")),
        )
        ctx = await SafetyKnowledgeRetriever(db_session).retrieve(
            "隐患定级依据", target_chunks=4
        )
        assert ctx.degradation == "ragplus_unavailable"
        assert ctx.chunks == []
        assert "不可用" in ctx.markdown


class TestHybridRetrieverSwitch:
    async def test_switch_off_local_path(self, db_session, monkeypatch) -> None:
        monkeypatch.setattr(
            rag_retriever,
            "get_ragplus_client",
            lambda: pytest.fail("开关关闭时不应构建 ragplus 客户端"),
        )
        report = await HybridRetriever(db_session).retrieve(
            "受限空间作业", target_chunks=4
        )
        assert report.degradation_level != "ragplus"

    async def test_switch_on_returns_ragplus_report(
        self, db_session, monkeypatch
    ) -> None:
        monkeypatch.setenv(_SWITCH, "true")
        client = _fake_client([_hit(similarity=0.9)])
        monkeypatch.setattr(rag_retriever, "get_ragplus_client", lambda: client)

        report = await HybridRetriever(db_session).retrieve("动火作业", target_chunks=8)
        assert report.degradation_level == "ragplus"
        assert report.results[0].chunk_text.startswith("第三条")
        assert report.results[0].score == pytest.approx(0.9)
        client.search.assert_awaited_once_with("动火作业", top_k=8)

    async def test_switch_on_unavailable_raises(self, db_session, monkeypatch) -> None:
        """直用方（sop_ai）语义：不可用抛错，由其现有 except 转 warnings 标注。"""
        monkeypatch.setenv(_SWITCH, "true")
        monkeypatch.setattr(
            rag_retriever,
            "get_ragplus_client",
            lambda: _fake_client(error=RagplusUnavailableError("超时")),
        )
        with pytest.raises(RagplusUnavailableError):
            await HybridRetriever(db_session).retrieve("动火作业", target_chunks=8)


class TestQueryServiceUnavailable:
    async def test_unavailable_returns_error_answer_without_ai(
        self, monkeypatch
    ) -> None:
        """聊天链路：ragplus 不可用→显式报错话术，不调 AI、不联网。"""
        unavailable_ctx = KnowledgeContext(
            chunks=[],
            markdown="（知识检索服务（ragplus）不可用）",
            degradation="ragplus_unavailable",
        )
        stub_retriever = MagicMock()
        stub_retriever.retrieve = AsyncMock(return_value=unavailable_ctx)
        monkeypatch.setattr(
            "app.modules.safety.knowledge.query_service.SafetyKnowledgeRetriever",
            lambda *a, **kw: stub_retriever,
        )
        ai_service = MagicMock()
        ai_service.chat = AsyncMock(return_value="不应被调用")
        ai_service.close = AsyncMock()
        monkeypatch.setattr(
            "app.modules.safety.knowledge.query_service.create_ai_service",
            lambda *a, **kw: ai_service,
        )

        answer, sources = await run_knowledge_chat(
            "动火作业有什么要求？",
            db=MagicMock(),
            enable_web_search=True,
        )

        assert answer == RAGPLUS_UNAVAILABLE_ANSWER
        assert sources == []
        ai_service.chat.assert_not_awaited()


class TestRagCacheEngineMarker:
    def test_engine_marker_makes_distinct_keys(self) -> None:
        """同一查询 local/ragplus 缓存键不同（开关切换不脏读）。

        直接验证键构造语义：get/set 同走 _rag_cache_key，键隔离即读写隔离。
        （不走真实 redis：模块级连接池绑定首个事件循环，跨 loop 会炸。）
        """
        local_key = rag_cache._rag_cache_key("动火作业", None, 8, 2, 0, "local")
        ragplus_key = rag_cache._rag_cache_key("动火作业", None, 8, 2, 0, "ragplus")
        assert local_key != ragplus_key
        # 同引擎键稳定（幂等读写的前提）
        assert local_key == rag_cache._rag_cache_key("动火作业", None, 8, 2, 0, "local")
