"""地点文本 → 分区分区映射匹配（pins 端点消费，纯函数）。

匹配规则（.scratch/f2-facility-map/spec.md 拍板）：
1. 归一化（去首尾空白 + 全角→半角 + 小写）后精确等值；
2. 未精确命中 → 票面文本包含映射词，映射词按长度降序取最长命中。
不做反向包含（映射词长于票面文本的包含无意义且易误配）。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "MatchIndex",
    "build_match_index",
    "match_location",
    "normalize_location_text",
]

# 全角 ASCII（！＂＃…～）→ 半角；全角空格单独处理
_FW_TABLE = {i: i - 0xFEE0 for i in range(0xFF01, 0xFF5F)}


def normalize_location_text(text: str | None) -> str:
    """归一化地点文本：全角→半角、去首尾空白（含全角空格）、小写。"""
    if not text:
        return ""
    half = text.replace("\u3000", " ").translate(_FW_TABLE)
    return half.strip().lower()


@dataclass(frozen=True)
class MatchIndex:
    """映射匹配索引：精确表 + 包含候选（按词长降序，长词优先命中）。"""

    exact: dict[str, str]
    contains: tuple[tuple[str, str], ...]  # (normalized 词, dist_id)，词长降序


def build_match_index(rows: list[dict]) -> MatchIndex:
    """location_district_map 行（{location_text, dist_id}）→ 匹配索引。"""
    exact: dict[str, str] = {}
    for row in rows:
        word = normalize_location_text(row.get("location_text"))
        dist_id = str(row.get("dist_id") or "")
        if word and dist_id:
            exact.setdefault(word, dist_id)
    contains = tuple(sorted(exact.items(), key=lambda kv: len(kv[0]), reverse=True))
    return MatchIndex(exact=exact, contains=contains)


def match_location(text: str | None, index: MatchIndex) -> str | None:
    """地点文本 → dist_id；两级匹配均未命中返回 None。"""
    normalized = normalize_location_text(text)
    if not normalized:
        return None
    hit = index.exact.get(normalized)
    if hit is not None:
        return hit
    for word, dist_id in index.contains:
        if word in normalized:
            return dist_id
    return None
