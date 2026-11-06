"""① 检索评测脚本纯函数单测（P1-1 R5，S4 接缝）。

全部合成数据：不依赖 /tmp、不连真库；快照用 tmp_path 合成文件；
检索策略评测注入 fake retrieve 函数。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.modules.safety.knowledge.retriever import KnowledgeContext

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "hazard_retrieval_eval.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hazard_retrieval_eval", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = _load_script()


# ══════════════════════════════════════════════════════════════
# 描述提取 / 名称归一 / 弱标签
# ══════════════════════════════════════════════════════════════


class TestExtractionAndLabels:
    def test_extract_description_from_prompt(self) -> None:
        prompt = "隐患编号：HZ-1\n责任部门：甲车间\n隐患描述：受限空间标识脱落\n\n## 相关法规条款"
        assert ev.extract_description_from_prompt(prompt) == "受限空间标识脱落"

    def test_extract_description_missing_returns_none(self) -> None:
        assert ev.extract_description_from_prompt("无标记文本") is None

    def test_normalize_name_collapses_spaces_and_marks(self) -> None:
        assert ev.normalize_name("GB 30871-2022") == ev.normalize_name("GB30871_2022")

    def test_doc_matches_label_containment_both_ways(self) -> None:
        # doc 带年后缀含 label；反向 label 含 doc
        assert ev.doc_matches_label("GB 30871-2022 危险化学品企业特殊作业安全规范", ["GB 30871"])
        assert ev.doc_matches_label("受限空间", ["受限空间作业安全管理制度"])

    def test_doc_not_matches_unrelated_label(self) -> None:
        assert not ev.doc_matches_label("MSDS 甲醇", ["GB 30871"])

    def test_extract_citation_docs_book_and_bracket(self) -> None:
        basis = "《安全生产法》第41条：…；[AQ 3047-2013 化学品作业场所安全警示标志规范]第3条：…"
        docs = ev.extract_citation_docs(basis)
        assert "安全生产法" in docs
        assert "AQ 3047-2013 化学品作业场所安全警示标志规范" in docs

    def test_suggest_weak_labels_confined_space(self) -> None:
        labels = ev.suggest_weak_labels("受限空间标识脱落")
        assert any("30871" in label or "特殊作业" in label for label in labels)
        assert any("受限空间" in label for label in labels)

    def test_suggest_weak_labels_hot_work(self) -> None:
        labels = ev.suggest_weak_labels("罐区动火作业未办理作业票")
        assert any("30871" in label or "特殊作业" in label for label in labels)

    def test_suggest_weak_labels_empty_for_unknown(self) -> None:
        assert ev.suggest_weak_labels("某处物件摆放杂乱") == []


# ══════════════════════════════════════════════════════════════
# 快照读写
# ══════════════════════════════════════════════════════════════


def _entry(
    record_id: str,
    description: str,
    source: str,
    labels: list[str],
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "description": description,
        "source": source,
        "weak_labels": labels,
        "label_provenance": "合成测试",
    }


class TestSnapshot:
    def test_load_snapshot_filters_unlabeled_and_invalid(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.jsonl"
        path.write_text(
            "\n".join(
                [
                    json.dumps(_entry("r1", "受限空间标识脱落", "failure_57", ["GB 30871"]), ensure_ascii=False),
                    json.dumps(_entry("r2", "无标签描述", "failure_57", []), ensure_ascii=False),
                    "not-json-line",
                ]
            ),
            encoding="utf-8",
        )
        entries = ev.load_snapshot(path)
        assert [e["record_id"] for e in entries] == ["r1"]

    def test_load_snapshot_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            ev.load_snapshot(tmp_path / "nope.jsonl")


# ══════════════════════════════════════════════════════════════
# 策略评测（fake retrieve）
# ══════════════════════════════════════════════════════════════


def _normalize(doc: str) -> str:
    return "".join(ch for ch in doc if ch.isalnum())


def _ctx_docs(docs: list[str]) -> KnowledgeContext:
    """fake retrieve 返回值：只带 source_doc 的轻量上下文（chunk_id 按 doc 唯一）。"""
    from app.modules.safety.knowledge.retriever import RetrievalResult

    chunks = [
        RetrievalResult(
            chunk_id=f"c-{_normalize(doc)}", chunk_text="条文", source_doc=doc,
            source_article="第1条", doc_category="laws_regulations",
            priority="P1", score=0.9,
        )
        for doc in docs
    ]
    return KnowledgeContext(
        chunks=chunks, graph_path=None, article_ids=[], markdown="x" * 100,
        degradation="ragplus",
    )


def normalize(doc: str) -> str:
    return "".join(ch for ch in doc if ch.isalnum())


class TestEvaluateStrategy:
    async def test_baseline_strategy_single_route_original_query(self) -> None:
        calls: list[tuple[str, int]] = []

        async def fake_retrieve(description: str, target_chunks: int):
            calls.append((description, target_chunks))
            return _ctx_docs(["GB 30871-2022 特殊作业安全规范"])

        entries = [_entry("r1", "受限空间标识脱落", "failure_57", ["GB 30871"])]
        result = await ev.evaluate_strategy(
            entries, retrieve=fake_retrieve, strategy="baseline", top_k=8
        )
        assert calls == [("受限空间标识脱落", 8)]  # 原文单路
        assert result["aggregate"]["labeled"] == 1
        assert result["aggregate"]["hit"] == 1
        assert result["aggregate"]["recall"] == 100.0
        assert result["aggregate"]["avg_routes"] == 1.0

    async def test_multi_strategy_uses_query_plan_and_merges(self) -> None:
        routes: dict[str, list[str]] = {}

        async def fake_retrieve(description: str, target_chunks: int):
            return _ctx_docs(routes.get(description, []))

        description = "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用"
        from app.modules.safety.service.hazard_direct import retrieval_query as rq

        plan = rq.build_retrieval_queries(description)
        routes[plan.queries[0]] = ["无关文档"]
        routes[plan.queries[1]] = ["GB 30871-2022 特殊作业安全规范"]

        entries = [_entry("r1", description, "failure_57", ["GB 30871"])]
        result = await ev.evaluate_strategy(
            entries, retrieve=fake_retrieve, strategy="multi", top_k=8, candidates=12
        )
        # 关键词路召回了目标文档 → 多路合并命中（单路主查询会漏）
        assert result["aggregate"]["hit"] == 1
        assert result["aggregate"]["avg_routes"] == float(len(plan.queries))

    async def test_multi_rescue_counts_improved_over_baseline(self) -> None:
        """方向目标口径：基线漏检、多路命中的条目计为 improved。"""

        async def baseline_retrieve(description: str, target_chunks: int):
            return _ctx_docs(["无关文档"])

        calls: list[str] = []

        async def multi_retrieve(description: str, target_chunks: int):
            # 主路（第一个调用）返回无关文档；关键词路召回目标文档
            calls.append(description)
            if len(calls) == 1:
                return _ctx_docs(["无关文档"])
            return _ctx_docs(["GB 30871-2022 特殊作业安全规范"])

        entries = [
            _entry("r1", "一号车间三级配电箱底部孔洞未封堵且消防通道被杂物占用",
                   "failure_57", ["GB 30871"]),
        ]
        baseline = await ev.evaluate_strategy(
            entries, retrieve=baseline_retrieve, strategy="baseline", top_k=8
        )
        multi = await ev.evaluate_strategy(
            entries, retrieve=multi_retrieve, strategy="multi", top_k=8, candidates=12
        )
        improved = ev.count_improved(baseline["per_entry"], multi["per_entry"])
        assert improved == 1

    async def test_unlabeled_entries_excluded_from_recall(self) -> None:
        async def fake_retrieve(description: str, target_chunks: int):
            return _ctx_docs(["任意"])

        entries = [_entry("r1", "杂乱", "failure_57", [])]
        result = await ev.evaluate_strategy(
            entries, retrieve=fake_retrieve, strategy="baseline", top_k=8
        )
        assert result["aggregate"]["labeled"] == 0
        assert result["aggregate"]["recall"] == 0.0
