"""P2-4 T03 —— ②初审与例外复核员接入知识压缩 单测。

口径（.scratch/hazard-p2-closeout/spec.md §4.4 拍板）：
- ② ``review._load_knowledge_context`` 返回压缩后注入文本（复用
  ``context_compression.injection_markdown``，同键 200/0=off 热生效）；
- 复核员 ``search_regulations`` 工具：返回给 LLM 的 chunk_text 截断
  （引用句永不丢），``searched_entries`` 保全量（rescued/cross_check
  引用验证语义零变化）。

全部 fake：monkeypatch 检索器/检索面，零网络零 DB。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.knowledge.retriever import (
    KnowledgeContext,
    RetrievalResult,
)
from app.modules.safety.service.hazard_direct import context_compression, review

_MAX_CHARS_KEY = "SAFETY_HAZARD_KNOWLEDGE_CONTEXT_MAX_CHARS"


def _chunk(text: str, *, doc: str = "危险化学品安全管理条例", article: str = "第四条") -> Any:
    return RetrievalResult(
        chunk_id="c1",
        chunk_text=text,
        source_doc=doc,
        source_article=article,
        doc_category="regulation",
        priority="normal",
        score=1.0,
    )


def _context(text: str) -> KnowledgeContext:
    """构造含单长 chunk 的上下文（markdown 与 build_markdown 同构）。"""
    md = f"## 相关法规条款\n\n[1] 《危险化学品安全管理条例》 第四条\n{text}"
    return KnowledgeContext(chunks=[_chunk(text)], markdown=md)


_LONG_TEXT = (
    "生产经营单位必须加强安全生产管理。这是第一句很长的话用来占预算。" * 6
    + "《危险化学品安全管理条例》第四条要求落实全员安全生产责任制。"
    + "结尾还有一句超预算的普通句子，应当被截断丢弃。"
)


def _set_max_chars(monkeypatch: pytest.MonkeyPatch, value: int) -> None:
    """app_config 截断档位（house 配方：delenv + _fetch_rows + invalidate）。"""
    from app.modules.safety.app_config.store import store as app_config_store

    monkeypatch.delenv(_MAX_CHARS_KEY, raising=False)
    monkeypatch.setattr(
        app_config_store, "_fetch_rows", lambda: {_MAX_CHARS_KEY: str(value)}
    )
    app_config_store.invalidate()


@pytest.fixture
def fake_retriever(monkeypatch: pytest.MonkeyPatch):
    """把 review 模块内惰性 import 的检索器换成 fake（返回固定上下文）。"""

    class _FakeRetriever:
        def __init__(self, session: Any) -> None:
            pass

        async def retrieve(
            self, *, description: str, target_chunks: int = 8
        ) -> KnowledgeContext:
            return _context(_LONG_TEXT)

    import app.modules.safety.knowledge.retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "SafetyKnowledgeRetriever", _FakeRetriever)
    return _FakeRetriever


# ── ② 初审 ─────────────────────────────────────────────────────


async def test_review_injects_compressed_context(
    monkeypatch: pytest.MonkeyPatch, fake_retriever: Any
) -> None:
    """② 注入文本走压缩器：200 档生效（引用句保留+省略号）。"""
    _set_max_chars(monkeypatch, 200)
    result = await review._load_knowledge_context(None, "任何描述")
    expected = context_compression.compress_knowledge_context(
        _context(_LONG_TEXT), max_chunk_chars=200
    )
    assert result == expected
    assert result is not None and len(result) < len(_context(_LONG_TEXT).markdown)
    assert "……" in result  # 发生了截断
    assert "全员安全生产责任制" in result  # 引用句永不丢


async def test_review_zero_off_passthrough(
    monkeypatch: pytest.MonkeyPatch, fake_retriever: Any
) -> None:
    """0=off：原样透传全量 markdown（热回滚零成本）。"""
    _set_max_chars(monkeypatch, 0)
    result = await review._load_knowledge_context(None, "任何描述")
    assert result == _context(_LONG_TEXT).markdown


# ── 复核员工具截断 ──────────────────────────────────────────────


async def test_search_tool_truncates_llm_view_keeps_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工具返回值截断（引用句保留）；searched_entries 全量。"""
    from app.modules.safety.service.hazard_direct import exception_reviewer as er

    _set_max_chars(monkeypatch, 200)

    class _Searcher:
        async def search(self, query: str) -> list[dict[str, Any]]:
            return [
                {
                    "source_doc": "条例",
                    "source_article": "第四条",
                    "chunk_text": _LONG_TEXT,
                    "chunk_id": "c1",
                }
            ]

    searched: list[dict[str, Any]] = []
    tool = er.build_search_regulations_tool(
        _Searcher(), searched_entries=searched, seen_chunk_ids=set()
    )
    out = await tool("查询")
    assert out[0]["chunk_text"] != _LONG_TEXT  # LLM 视图被截断
    assert "……" in out[0]["chunk_text"]
    assert "全员安全生产责任制" in out[0]["chunk_text"]  # 引用句保留
    assert searched[0]["chunk_text"] == _LONG_TEXT  # 证据面全量
    assert out[0]["source_doc"] == "条例" and out[0]["chunk_id"] == "c1"  # 元数据不动


async def test_search_tool_zero_off_keeps_full_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0=off：LLM 视图原样全量（与①同键热回滚）。"""
    from app.modules.safety.service.hazard_direct import exception_reviewer as er

    _set_max_chars(monkeypatch, 0)

    class _Searcher:
        async def search(self, query: str) -> list[dict[str, Any]]:
            return [
                {
                    "source_doc": "条例",
                    "source_article": "第四条",
                    "chunk_text": _LONG_TEXT,
                    "chunk_id": "c1",
                }
            ]

    searched: list[dict[str, Any]] = []
    tool = er.build_search_regulations_tool(
        _Searcher(), searched_entries=searched, seen_chunk_ids=set()
    )
    out = await tool("查询")
    assert out[0]["chunk_text"] == _LONG_TEXT


async def test_search_tool_dedup_across_calls() -> None:
    """既有去重语义保留：同 chunk_id 跨调用不重复入证据。"""
    from app.modules.safety.service.hazard_direct import exception_reviewer as er

    calls: list[str] = []

    class _Searcher:
        async def search(self, query: str) -> list[dict[str, Any]]:
            calls.append(query)
            return [
                {
                    "source_doc": "条例",
                    "source_article": "第四条",
                    "chunk_text": "短文本。",
                    "chunk_id": "c1",
                }
            ]

    searched: list[dict[str, Any]] = []
    tool = er.build_search_regulations_tool(
        _Searcher(), searched_entries=searched, seen_chunk_ids=set()
    )
    await tool("第一次")
    await tool("第二次")
    assert len(calls) == 2  # 工具照常调用（模型可见两次结果）
    assert len(searched) == 1  # 证据只累积一次
