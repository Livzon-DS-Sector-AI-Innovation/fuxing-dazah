"""同一实体跨 chunk 去重的证据位置合并行为测试。

observation 的 run 级去重发生在 `process_analysis_run` 主循环（需重型
数据库 fake，见提案测试的说明），这里聚焦可独立验证的合并策略：按证据
哈希去重、超出上限截断。表头会复制进每个派生 chunk、PDF 页眉页脚逐页
保留，同一 raw block 被多个 chunk 引用时哈希相同，不应重复计入。
"""

from __future__ import annotations

from typing import Any

from app.modules.qa.ai_analysis import _merge_evidence_locations


def _entry(hash_value: str, locator: str) -> dict[str, Any]:
    return {"evidence_hash": hash_value, "locator": locator, "location": {}}


def test_merge_into_empty_list_appends_first_location() -> None:
    """首次出现：空列表初始化为单条位置。"""
    entry = _entry("h1", "page:1/block:2")
    assert _merge_evidence_locations([], entry) == [entry]


def test_merge_ignores_duplicate_evidence_hash() -> None:
    """同一 raw block 被多个 chunk 引用（哈希相同）时不重复计入。"""
    first = _entry("h1", "page:1/block:2")
    assert _merge_evidence_locations([first], _entry("h1", "page:1/block:2")) == [first]


def test_merge_appends_distinct_locations_in_order() -> None:
    """不同位置按出现顺序追加。"""
    first = _entry("h1", "page:1/block:2")
    second = _entry("h2", "page:3/block:7")
    third = _entry("h3", "page:5/block:1")
    merged = _merge_evidence_locations(
        _merge_evidence_locations([first], second), third
    )
    assert merged == [first, second, third]


def test_merge_truncates_beyond_cap() -> None:
    """页眉页脚逐页保留时同一实体可能出现几十次：只保留前 cap 条。"""
    entries = [_entry(f"h{i}", f"page:{i}") for i in range(12)]
    merged: list[dict[str, Any]] = []
    for entry in entries:
        merged = _merge_evidence_locations(merged, entry)
    assert len(merged) == 10
    assert [item["evidence_hash"] for item in merged] == [f"h{i}" for i in range(10)]
