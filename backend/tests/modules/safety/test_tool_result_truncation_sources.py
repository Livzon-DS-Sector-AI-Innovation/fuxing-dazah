"""工具结果截断的 sources 保命测试（2026-11-06 阻火器引用事故）。

事故：knowledge_search 返回超 4KB，截断中间件把 sources 整个丢掉
（answer 自身超限走整体预览路径）或从 6 条截剩 1 条（列表路径）——
而卡片「参考法规」栏的唯一数据源（executor._extract_knowledge_sources）
读的正是截断产物，导致参考栏缺失、无原文链接。
"""

from __future__ import annotations

import json

from app.modules.safety.business_agent.core.pipeline import (
    _TOOL_RESULT_MAX_BYTES,
    _slim_sources,
    _truncate_tool_result,
)


def _mk_sources(n: int, chunk_len: int = 3000) -> list[dict]:
    return [
        {
            "doc_title": f"法规{i}",
            "feishu_url": f"https://x/{i}",
            "article_ref": "5.1.1",
            "chunk_text": "字" * chunk_len,
        }
        for i in range(1, n + 1)
    ]


def test_small_result_untouched() -> None:
    data = {"answer": "ok", "sources": _mk_sources(2, chunk_len=100)}
    assert _truncate_tool_result(data) is data


def test_slim_sources_trims_chunk_text_only() -> None:
    slim = _slim_sources(_mk_sources(1, chunk_len=5000))
    assert len(slim[0]["chunk_text"]) == 121  # 120 字 + 省略号
    assert slim[0]["doc_title"] == "法规1"
    assert slim[0]["feishu_url"] == "https://x/1"


def test_slim_fits_returns_all_sources() -> None:
    """瘦身后总量进预算：直接放行全部 sources，不走截断路径。"""
    data = {"answer": "x" * 800, "sources": _mk_sources(6)}
    out = _truncate_tool_result(data)
    assert "truncation_notice" not in out and "truncated" not in out
    assert len(out["sources"]) == 6
    assert all(len(s["chunk_text"]) <= 121 for s in out["sources"])
    assert out["sources"][0]["feishu_url"] == "https://x/1"


def test_preview_path_keeps_sources() -> None:
    """answer 自身超限（事故 call_00 形态）：整体预览路径必须附带瘦 sources。"""
    data = {
        "answer": "字" * (_TOOL_RESULT_MAX_BYTES * 2),
        "kb_empty": False,
        "sources": _mk_sources(6, chunk_len=500),
    }
    out = _truncate_tool_result(data)
    assert out["truncated"] is True
    # sources 全部幸存且关键键完整（参考栏数据源）
    assert len(out.get("sources", [])) == 6
    assert out["sources"][2]["doc_title"] == "法规3"
    assert out["sources"][5]["feishu_url"] == "https://x/6"
    # 总体积仍守在预算+余量内
    total = len(json.dumps(out, ensure_ascii=False).encode())
    assert total <= _TOOL_RESULT_MAX_BYTES + 1024


def test_many_sources_list_path_trim_with_notice() -> None:
    """条目已瘦仍超限（50 条）：走列表截断，保留部分条数 + 截断提示。"""
    data = {
        "answer": "x" * 500,
        "sources": [
            {"doc_title": f"法规{i}", "feishu_url": f"https://x/{i}", "chunk_text": "y" * 100}
            for i in range(1, 51)
        ],
    }
    out = _truncate_tool_result(data)
    assert "truncation_notice" in out
    assert 1 <= len(out["sources"]) < 50
