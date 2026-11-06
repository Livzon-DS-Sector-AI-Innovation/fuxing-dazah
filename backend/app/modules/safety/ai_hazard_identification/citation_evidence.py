"""C2 引用来源强约束 —— 「引用 ⊆ 本轮检索 chunks」的本地可验证唯一事实源。

本模块只做纯文本判定，**无任何 IO / 网络 / 数据库依赖**，供三处共用：
- ① 插件规则校验（``ai_hazard_identification.rules``）：严格模式下把「零条可验证
  引用」判为 error → 带错误反馈重试一次；
- ① 写回前质量闸门（``service.hazard_direct.quality_gate``）：``invalid_citation``
  不写回；
- 离线评测脚本（``backend/scripts/hazard_ai_quality_replay.py``）：从审计
  ``input_text`` 还原本轮知识库证据后重放判定。

口径（spec §C2「匹配算法」）：
1. 证据 = ``CitationEvidence``（``EvidenceEntry``：法规名 / 条号 / chunk 正文 /
   chunk_id），来源可以是 ``KnowledgeContext.chunks``（运行时）或已渲染的
  知识库 markdown（离线重放/测试）；
2. 引用单元 = 依据文本按 ``；;`` 与换行切分后，抽取书名号《…》、方括号内含数字的
   法规名、标准号、``第X条/第X.X条/X.X条``、引号内条款原文；
3. 单元可验证 = 法规名命中 **或** 标准号命中 **或** 条号命中 **或** 条款文本命中
   （全部归一化后；条款文本允许 LCS ≥ 0.7 容忍 OCR/断行/省略号）；
4. 记录级硬约束 = **至少一个单元可验证**（条目级口径，见 2026-11-05 历史 140 条
   成功样本实测：逐条严格会误拒 52/140，条目级仅误拒 0 条合法样本）。

设计边界：不做引用裁剪/改写、不访问 AI、不判断语义正确性——只回答「这段引用能
不能在本轮检索证据里找到出处」。
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.modules.safety.ai_hazard_identification.citations import (
    DOC_NUMBER_PATTERN,
    STANDARD_NO_PATTERN,
    is_placeholder_variant,
)

__all__ = [
    "CitationEvidence",
    "CitationReport",
    "CitationUnit",
    "EvidenceEntry",
    "extract_citation_units",
    # 占位判定唯一事实源在 citations；此处 re-export 仅为调用方导入便利
    "is_placeholder_variant",
    "verify_citations",
]

# ═══════════════════════════════════════════════════════════════════════════
# 证据结构
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EvidenceEntry:
    """单条检索证据（对应一个 chunk 的可匹配元数据 + 正文）。"""

    doc_name: str = ""
    source_article: str = ""
    chunk_text: str = ""
    chunk_id: str = ""


@dataclass(frozen=True)
class CitationEvidence:
    """本轮检索证据集合（本地匹配用；空集合表示无可验证来源）。"""

    entries: tuple[EvidenceEntry, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.entries

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        return tuple(entry.chunk_id for entry in self.entries if entry.chunk_id)

    @classmethod
    def from_chunks(cls, chunks: Iterable[object]) -> CitationEvidence:
        """从检索 chunks 构造（读 ``source_doc/source_article/chunk_text/chunk_id``）。

        属性缺失/空文本的 chunk 跳过（兼容测试里的 fake chunk 对象）。
        """
        entries: list[EvidenceEntry] = []
        for chunk in chunks:
            entry = EvidenceEntry(
                doc_name=str(getattr(chunk, "source_doc", "") or ""),
                source_article=str(getattr(chunk, "source_article", "") or ""),
                chunk_text=str(getattr(chunk, "chunk_text", "") or ""),
                chunk_id=str(getattr(chunk, "chunk_id", "") or ""),
            )
            if entry.doc_name or entry.source_article or entry.chunk_text:
                entries.append(entry)
        return cls(entries=tuple(entries))

    @classmethod
    def from_markdown(cls, markdown: str) -> CitationEvidence:
        """从已渲染的知识库 markdown 构造（离线重放用）。

        渲染格式（``knowledge.retriever._build_markdown``）::

            ## 相关法规条款

            [1] 《法规名》 条号
            正文……

            ---

            [2] 《法规名2》
            正文……
        """
        if not markdown:
            return cls()
        marker = "## 相关法规条款"
        if marker in markdown:
            text = markdown.split(marker, 1)[1]
        elif re.search(r"^\s*\[\d+\]", markdown, re.M):
            text = markdown
        else:
            # 「（知识库中暂无与查询相关的法规条款）」等无分块文本 → 空证据
            return cls()
        entries: list[EvidenceEntry] = []
        for section in re.split(r"\n\s*---\s*\n", text):
            section = section.strip()
            if not section:
                continue
            match = re.match(r"\[(\d+)\]\s*(.*)", section, re.S)
            body = match.group(2) if match else section
            lines = body.split("\n", 1)
            title = lines[0].strip()
            chunk_text = lines[1].strip() if len(lines) > 1 else ""
            doc_match = re.search(r"《([^》\n]{1,80})》", title)
            doc_name = doc_match.group(1).strip() if doc_match else title
            source_article = title[doc_match.end():].strip() if doc_match else ""
            if doc_name or chunk_text:
                entries.append(
                    EvidenceEntry(
                        doc_name=doc_name,
                        source_article=source_article,
                        chunk_text=chunk_text,
                    )
                )
        return cls(entries=tuple(entries))


@dataclass(frozen=True)
class CitationUnit:
    """一个引用单元（依据文本按分隔符切出的一段）。"""

    text: str
    docs: tuple[str, ...] = ()
    standards: tuple[str, ...] = ()
    articles: tuple[str, ...] = ()
    quotes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CitationReport:
    """一次依据文本的可验证报告（单元级命中明细 + 占位注记标记）。"""

    units: tuple[CitationUnit, ...] = ()
    unit_hits: tuple[bool, ...] = ()
    placeholder_note: bool = False

    @property
    def total_units(self) -> int:
        return len(self.units)

    @property
    def verified_units(self) -> int:
        return sum(self.unit_hits)

    @property
    def has_verified(self) -> bool:
        return self.verified_units > 0

    @property
    def all_verified(self) -> bool:
        return self.total_units > 0 and self.verified_units == self.total_units

    @property
    def verified_rate(self) -> float:
        if self.total_units == 0:
            return 0.0
        return round(self.verified_units / self.total_units, 4)

    @property
    def unverified_texts(self) -> tuple[str, ...]:
        return tuple(
            unit.text[:80]
            for unit, hit in zip(self.units, self.unit_hits)
            if not hit
        )[:5]


# ═══════════════════════════════════════════════════════════════════════════
# 归一化（全角/变体字符、空白、书名号）
# ═══════════════════════════════════════════════════════════════════════════

_NORMALIZE_MAP = str.maketrans(
    {
        "／": "/",
        "∕": "/",
        "⁄": "/",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "（": "(",
        "）": ")",
        "﹙": "(",
        "﹚": ")",
        "：": ":",
        "，": ",",
        "；": ";",
        "。": ".",
        "、": ",",
        "—": "-",
        "－": "-",
        "–": "-",
        "～": "-",
        "~": "-",
    }
)
_WHITESPACE_RE = re.compile(r"[\s\u3000]+")
_BOOK_MARK_RE = re.compile(r"[《》]")
# 标准号键：只保留字母/数字/点/连字符（去空格、斜杠、星号等写法噪声）
_STANDARD_KEY_RE = re.compile(r"[^0-9A-Z.\-]")


def _normalize(text: str) -> str:
    """匹配用归一化：全角→半角、去所有空白、去书名号。"""
    if not text:
        return ""
    return _BOOK_MARK_RE.sub("", _WHITESPACE_RE.sub("", text.translate(_NORMALIZE_MAP)))


def _standard_key(text: str) -> str:
    """标准号归一化键（``GB/T 30000.31-2023`` → ``GBT30000.31-2023``）。"""
    if not text:
        return ""
    mapped = _normalize(text).upper()
    return _STANDARD_KEY_RE.sub("", mapped)


_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def _cn_number_to_int(text: str) -> int | None:
    """中文数字 → 整数（支持 十/百/千、十五、二十、一百零二 等常见写法）。"""
    if not text:
        return None
    if all(ch in _CN_DIGITS for ch in text):
        value = 0
        for ch in text:
            value = value * 10 + _CN_DIGITS[ch]
        return value
    total = 0
    current = 0
    for ch in text:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            total += (current or 1) * unit
            current = 0
        else:
            return None
    return total + current


def _article_number(article: str) -> str | None:
    """条号 → 数字串（``第5.1条``→``5.1``、``第十条``→``10``）。"""
    if not article:
        return None
    body = _normalize(article)
    body = body.replace("第", "").replace("章", "").replace("节", "").replace("条", "")
    body = body.rstrip(".")
    if re.fullmatch(r"\d+(?:\.\d+)*", body):
        return body
    value = _cn_number_to_int(body)
    return str(value) if value is not None else None


# ═══════════════════════════════════════════════════════════════════════════
# 引用单元抽取
# ═══════════════════════════════════════════════════════════════════════════

_QUOTE_REGEXES = (
    re.compile(r"'([^'\n]{6,})'"),
    re.compile(r'"([^"\n]{6,})"'),
    re.compile(r"“([^”\n]{6,})”"),
    re.compile(r"‘([^’\n]{6,})’"),
)

_DOC_REGEX = re.compile(r"《[^》\n]{1,80}》")
_BRACKET_DOC_REGEX = re.compile(r"\[([^\]\n]{2,80})\]")
# 引用语法片段与 citations.CITATION_RE 共用（单一事实源，避免两套正则漂移）
_STANDARD_REGEX = re.compile(f"(?:{STANDARD_NO_PATTERN})")
_DOC_NUMBER_REGEX = re.compile(DOC_NUMBER_PATTERN)
_ARTICLE_REGEX = re.compile(r"第[一二三四五六七八九十百千零〇两\d]+(?:\.\d+)*\s*[条章节]")
_SHORT_ARTICLE_REGEX = re.compile(r"(?<![\d.])\d+\.\d+(?:\.\d+)*\s*[条章节]")
_UNIT_SPLIT_RE = re.compile(r"[；;\n]")


def _extract_quotes(segment: str) -> tuple[str, ...]:
    quotes: list[str] = []
    for regex in _QUOTE_REGEXES:
        for match in regex.finditer(segment):
            quote = match.group(1).strip()
            if quote and quote not in quotes:
                quotes.append(quote)
    return tuple(quotes)


def _extract_unit(segment: str) -> CitationUnit:
    # 方括号法规名：`[AQ 3047-2013 …]`（含标准号）与 `[可燃粉尘工艺系统防爆技术规范]`
    # （纯名称，无数字）都是历史真实写法，全部纳入 doc 维度；跳过纯数字/过短括号。
    bracket_docs = tuple(
        content
        for content in (match.group(1).strip() for match in _BRACKET_DOC_REGEX.finditer(segment))
        if len(content) >= 4 and not re.fullmatch(r"[\d\s,;.\-]+", content)
    )
    docs = tuple(
        dict.fromkeys(
            (
                *_DOC_REGEX.findall(segment),
                *_DOC_NUMBER_REGEX.findall(segment),
                *bracket_docs,
            )
        )
    )
    standards = tuple(dict.fromkeys(_STANDARD_REGEX.findall(segment)))
    articles = tuple(
        dict.fromkeys(
            (
                *_ARTICLE_REGEX.findall(segment),
                *_SHORT_ARTICLE_REGEX.findall(segment),
            )
        )
    )
    return CitationUnit(
        text=segment,
        docs=docs,
        standards=standards,
        articles=articles,
        quotes=_extract_quotes(segment),
    )


def extract_citation_units(text: str) -> tuple[CitationUnit, ...]:
    """从判定依据文本切出引用单元（无引用返回空元组）。"""
    if not text or not text.strip():
        return ()
    units: list[CitationUnit] = []
    for raw_segment in _UNIT_SPLIT_RE.split(text):
        segment = raw_segment.strip()
        if not segment:
            continue
        unit = _extract_unit(segment)
        if unit.docs or unit.standards or unit.articles or unit.quotes:
            units.append(unit)
    return tuple(units)


# ═══════════════════════════════════════════════════════════════════════════
# 三级匹配
# ═══════════════════════════════════════════════════════════════════════════

_QUOTE_SIMILARITY_THRESHOLD = 0.7


def _evidence_blobs(evidence: CitationEvidence) -> tuple[tuple[str, str], ...]:
    """（归一化全文, 标准号键文本）二元组列表。"""
    blobs: list[tuple[str, str]] = []
    for entry in evidence.entries:
        # 标题行里书名号可能再套书名号（历史真实样本），归一化时统一去除
        raw = f"{entry.doc_name} {entry.source_article} {entry.chunk_text}"
        blobs.append((_normalize(raw), _standard_key(raw)))
    return tuple(blobs)


def _doc_hit(reference: str, blobs: tuple[tuple[str, str], ...]) -> bool:
    normalized = _normalize(reference)
    if not normalized:
        return False
    key = _standard_key(reference)
    for blob_text, blob_key in blobs:
        if normalized in blob_text:
            return True
        # 标准号键：≥6 字符避免 "GB1" 之类短键误命中
        if len(key) >= 6 and key in blob_key:
            return True
    return False


def _article_hit(article: str, blobs: tuple[tuple[str, str], ...]) -> bool:
    number = _article_number(article)
    if not number:
        return False
    pattern = re.compile(rf"(?<![\d.]){re.escape(number)}(?![\d.])")
    return any(pattern.search(blob_text) for blob_text, _ in blobs)


def _quote_hit(quote: str, blobs: tuple[tuple[str, str], ...]) -> bool:
    normalized = _normalize(quote)
    if len(normalized) < 4:
        return False
    for blob_text, _ in blobs:
        if normalized in blob_text:
            return True
    # 容许 OCR 断行/省略号/标点差异：最长公共子串占引文长度 ≥ 阈值
    for blob_text, _ in blobs:
        matcher = difflib.SequenceMatcher(None, normalized, blob_text, autojunk=False)
        longest = max(
            (block.size for block in matcher.get_matching_blocks()),
            default=0,
        )
        if longest / len(normalized) >= _QUOTE_SIMILARITY_THRESHOLD:
            return True
    return False


def _unit_hit(unit: CitationUnit, blobs: tuple[tuple[str, str], ...]) -> bool:
    for reference in (*unit.docs, *unit.standards):
        if _doc_hit(reference, blobs):
            return True
    for article in unit.articles:
        if _article_hit(article, blobs):
            return True
    for quote in unit.quotes:
        if _quote_hit(quote, blobs):
            return True
    return False


def verify_citations(text: str, evidence: CitationEvidence) -> CitationReport:
    """校验判定依据的引用能否在本轮检索证据中找到出处。

    Args:
        text: AI 输出的 ``major_hazard_basis`` 原文
        evidence: 本轮检索证据（空集合 = 无处可验 → 全部不可验证）

    Returns:
        ``CitationReport``：单元级命中明细、可验证数/占比、不可验证原文、
        占位注记标记。**是否阻断写回由调用方按「零可验证」判定**。
    """
    units = extract_citation_units(text)
    blobs = _evidence_blobs(evidence)
    hits = tuple(_unit_hit(unit, blobs) for unit in units)
    return CitationReport(
        units=units,
        unit_hits=hits,
        placeholder_note=is_placeholder_variant(text),
    )
