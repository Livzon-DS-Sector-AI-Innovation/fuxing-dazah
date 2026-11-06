"""① 检索 query 构建 / 多路合并纯函数单测（P1-1 R1/R2，S1 接缝）。

全部纯函数测试：不碰 DB / 网络 / LLM / Redis；参数读取只经 monkeypatch env
（store 读取链 env > DB(stub 空) > registry 默认）。
"""

from __future__ import annotations

import pytest

from app.modules.safety.knowledge.retriever import (
    KnowledgeContext,
    RetrievalResult,
)
from app.modules.safety.service.hazard_direct import retrieval_query as rq


def _chunk(chunk_id: str, doc: str, text: str = "条文内容") -> RetrievalResult:
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
        chunks=chunks,
        graph_path=None,
        article_ids=[],
        markdown="",
        degradation=degradation,
    )


# ══════════════════════════════════════════════════════════════
# clean_description
# ══════════════════════════════════════════════════════════════


class TestCleanDescription:
    def test_strips_leading_date_and_finding_prefix(self) -> None:
        assert (
            rq.clean_description("10月5日检查发现：3号罐区静电跨接断裂")
            == "3号罐区静电跨接断裂"
        )

    def test_strips_iso_like_dates(self) -> None:
        assert (
            rq.clean_description("2026.11.3，配电室配电箱底部孔洞未封堵")
            == "配电室配电箱底部孔洞未封堵"
        )

    def test_collapses_whitespace(self) -> None:
        assert rq.clean_description("  受限空间\n 标识 脱落 ") == "受限空间 标识 脱落"

    def test_truncates_overlong_description(self) -> None:
        cleaned = rq.clean_description("隐患" * 200)
        assert len(cleaned) <= rq.MAX_QUERY_CHARS

    def test_empty_and_none_safe(self) -> None:
        assert rq.clean_description("") == ""
        assert rq.clean_description(None) == ""  # type: ignore[arg-type]

    def test_plain_description_unchanged(self) -> None:
        assert rq.clean_description("灭火器压力表指针不在绿区") == "灭火器压力表指针不在绿区"

    def test_decimal_prefixed_description_not_mangled(self) -> None:
        # 序号剥离不能误伤小数开头描述（"1.5米" ≠ 序号 "1."）
        assert rq.clean_description("1.5米范围内堆放杂物") == "1.5米范围内堆放杂物"
        assert rq.clean_description("3.5米高处作业未系安全带") == "3.5米高处作业未系安全带"
        assert rq.clean_description("2.5公斤灭火器配置不足") == "2.5公斤灭火器配置不足"

    def test_sequence_prefix_still_stripped(self) -> None:
        assert rq.clean_description("3、配电室绝缘垫破损") == "配电室绝缘垫破损"
        assert rq.clean_description("(2)安全阀铅封缺失") == "安全阀铅封缺失"


# ══════════════════════════════════════════════════════════════
# build_retrieval_queries
# ══════════════════════════════════════════════════════════════


class TestBuildRetrievalQueries:
    def test_primary_route_is_cleaned_description(self) -> None:
        plan = rq.build_retrieval_queries("10月5日检查发现：受限空间标识脱落")
        assert plan.primary == "受限空间标识脱落"
        assert plan.rewrite_hit is True
        assert plan.queries[0] == plan.primary

    def test_keyword_route_added_when_lexicon_matches(self) -> None:
        # 关键词路是主路的「提炼」（去掉填充词）时追加
        plan = rq.build_retrieval_queries(
            "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        )
        assert len(plan.queries) == 2
        assert "配电箱" in plan.queries[1]
        assert plan.keyword_route is True

    def test_keyword_route_skipped_when_query_is_distillation_duplicate(self) -> None:
        # 关键词串 ≈ 主路连续子串（描述本身即关键词串联）→ 加路无增量
        plan = rq.build_retrieval_queries("3号罐区动火作业未办理作业票")
        assert plan.queries == ("3号罐区动火作业未办理作业票",)
        assert plan.keyword_route is False

    def test_no_keyword_match_single_route(self) -> None:
        plan = rq.build_retrieval_queries("某处物件摆放杂乱无章")
        assert len(plan.queries) == 1
        assert plan.keyword_route is False

    def test_keyword_route_deduped_against_primary(self) -> None:
        # 关键词 query 恰与主路相同（描述本身即一个关键词）→ 不重复加路
        plan = rq.build_retrieval_queries("受限空间")
        assert plan.queries == ("受限空间",)
        assert plan.keyword_route is False

    def test_standard_number_extracted_into_keyword_route(self) -> None:
        plan = rq.build_retrieval_queries(
            "罐区检修作业未按GB 30871要求办理动火作业票"
        )
        assert len(plan.queries) == 2
        assert any("30871" in q for q in plan.queries[1:])

    def test_short_description_single_route(self) -> None:
        plan = rq.build_retrieval_queries("标识脱落")
        assert len(plan.queries) == 1

    def test_multi_subject_description_gets_keyword_route(self) -> None:
        # 多主体：配电箱未封堵 + 消防通道被占 → 关键词路命中两个主体词
        plan = rq.build_retrieval_queries("配电箱孔洞未封堵，消防通道被杂物占用")
        assert len(plan.queries) == 2
        keywords = plan.queries[1]
        assert "配电箱" in keywords
        assert "消防通道" in keywords or "占用" in keywords

    def test_queries_all_non_empty(self) -> None:
        for description in ("", "   ", "10月5日", "动火作业"):
            plan = rq.build_retrieval_queries(description)
            assert all(q.strip() for q in plan.queries)


# ══════════════════════════════════════════════════════════════
# merge_route_contexts
# ══════════════════════════════════════════════════════════════


class TestMergeRouteContexts:
    def test_rrf_both_routes_chunk_ranks_first(self) -> None:
        both = _chunk("c-both", "《两路命中》")
        only_primary = _chunk("c-p", "《仅主路》", "主路独有条文")
        only_aux = _chunk("c-a", "《仅辅路》", "辅路独有条文")
        primary = _ctx([only_primary, both])
        aux = _ctx([only_aux, both])
        merged = rq.merge_route_contexts([primary, aux], top_k=8)
        assert merged.chunks[0].chunk_id == "c-both"

    def test_dedup_by_chunk_id(self) -> None:
        shared = _chunk("c-1", "《共享》")
        merged = rq.merge_route_contexts(
            [_ctx([shared]), _ctx([shared])], top_k=8
        )
        assert [c.chunk_id for c in merged.chunks] == ["c-1"]

    def test_top_k_cap(self) -> None:
        contexts = [_ctx([_chunk(f"c-{i}", f"《文档{i}》") for i in range(10)])]
        merged = rq.merge_route_contexts(contexts, top_k=5)
        assert len(merged.chunks) == 5

    def test_degradation_from_primary_route(self) -> None:
        primary = _ctx([_chunk("c-1", "《A》")], degradation="ragplus")
        aux = _ctx([_chunk("c-2", "《B》")], degradation="text_only")
        merged = rq.merge_route_contexts([primary, aux], top_k=8)
        assert merged.degradation == "ragplus"

    def test_graph_path_from_primary_route(self) -> None:
        primary = KnowledgeContext(
            chunks=[_chunk("c-1", "《A》")],
            graph_path="图谱路径",
            article_ids=[],
            markdown="",
            degradation="ragplus",
        )
        merged = rq.merge_route_contexts([primary, _ctx([])], top_k=8)
        assert merged.graph_path == "图谱路径"

    def test_markdown_rebuilt_with_chunk_numbering(self) -> None:
        primary = _ctx([_chunk("c-1", "《受限空间制度》", "第八条内容")])
        aux = _ctx([_chunk("c-2", "《GB 30871》", "第六条内容")])
        merged = rq.merge_route_contexts([primary, aux], top_k=8)
        assert "《受限空间制度》" in merged.markdown
        assert "《GB 30871》" in merged.markdown
        assert "## 相关法规条款" in merged.markdown

    def test_empty_aux_contexts_tolerated(self) -> None:
        primary = _ctx([_chunk("c-1", "《A》")])
        merged = rq.merge_route_contexts([primary, _ctx([]), _ctx([])], top_k=8)
        assert [c.chunk_id for c in merged.chunks] == ["c-1"]

    def test_merged_chunk_score_is_weighted_rrf_sum(self) -> None:
        both = _chunk("c-both", "《两路命中》")
        merged = rq.merge_route_contexts(
            [_ctx([both]), _ctx([both])], top_k=8
        )
        # 主路加权 2.0 + 辅路 1.0（均为 rank 0）
        expected = (rq.PRIMARY_ROUTE_WEIGHT + 1.0) / (rq.RRF_K + 1)
        assert merged.chunks[0].score == pytest.approx(expected)

    def test_primary_chunk_not_displaced_by_aux_noise(self) -> None:
        """主路加权：辅路大量新 chunk 不应把主路 top 命中挤出 top-k。"""
        primary_hit = _chunk("c-primary-hit", "《主路目标》")
        aux_noise = [_chunk(f"c-aux-{i}", f"《辅路噪声{i}》") for i in range(12)]
        merged = rq.merge_route_contexts(
            [_ctx([primary_hit]), _ctx(aux_noise)], top_k=8
        )
        assert any(c.chunk_id == "c-primary-hit" for c in merged.chunks)

    def test_both_routes_hit_outranks_primary_only(self) -> None:
        both = _chunk("c-both", "《双路命中》")
        only_primary = _chunk("c-p", "《仅主路》")
        only_aux = _chunk("c-a", "《仅辅路》")
        merged = rq.merge_route_contexts(
            [_ctx([only_primary, both]), _ctx([only_aux, both])], top_k=8
        )
        assert merged.chunks[0].chunk_id == "c-both"

    def test_requires_at_least_one_context(self) -> None:
        with pytest.raises(ValueError):
            rq.merge_route_contexts([], top_k=8)


# ══════════════════════════════════════════════════════════════
# 参数读取（app_config 读取链：env > DB(stub) > registry 默认）
# ══════════════════════════════════════════════════════════════


class TestParams:
    def test_defaults(self) -> None:
        assert rq.multi_query_enabled() is True
        assert rq.retrieval_top_k() == 8
        assert rq.retrieval_candidates() == 12
        assert rq.llm_rewrite_enabled() is False

    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_HAZARD_MULTI_QUERY_ENABLED", "false")
        monkeypatch.setenv("SAFETY_HAZARD_RETRIEVAL_TOP_K", "6")
        monkeypatch.setenv("SAFETY_HAZARD_RETRIEVAL_CANDIDATES", "15")
        monkeypatch.setenv("SAFETY_HAZARD_QUERY_LLM_REWRITE_ENABLED", "true")
        assert rq.multi_query_enabled() is False
        assert rq.retrieval_top_k() == 6
        assert rq.retrieval_candidates() == 15
        assert rq.llm_rewrite_enabled() is True


# ══════════════════════════════════════════════════════════════
# 审计 extra 检索维度字段（T03）
# ══════════════════════════════════════════════════════════════


class TestRetrievalAuditFields:
    def test_fields_shape(self) -> None:
        meta = rq.RetrievalMeta(
            query="主路查询",
            queries=("主路查询", "关键词 查询"),
            rewrite_hit=True,
            docs=("《文档A》", "《文档B》"),
        )
        assert rq.retrieval_audit_fields(meta) == {
            "retrieval_query": "主路查询",
            "retrieval_queries": ["主路查询", "关键词 查询"],
            "multi_query_count": 2,
            "rewrite_hit": True,
            "retrieval_docs": ["《文档A》", "《文档B》"],
        }

    def test_none_meta_returns_empty(self) -> None:
        assert rq.retrieval_audit_fields(None) == {}

    def test_docs_capped_at_eight(self) -> None:
        meta = rq.RetrievalMeta(
            query="q",
            queries=("q",),
            rewrite_hit=False,
            docs=tuple(f"《文档{i}》" for i in range(12)),
        )
        fields = rq.retrieval_audit_fields(meta)
        assert len(fields["retrieval_docs"]) == 8
