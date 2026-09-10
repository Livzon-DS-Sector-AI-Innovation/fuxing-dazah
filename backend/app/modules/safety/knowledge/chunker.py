"""Article-level chunker for regulatory documents.

Splits regulatory documents into clause/paragraph chunks using structure-aware
boundary detection. Falls back to semantic paragraph splitting for unstructured text.

Usage:
    from app.modules.safety.knowledge.chunker import ArticleChunker

    chunks = ArticleChunker.chunk(full_text, title="GB 30871-2022", category="standards")
    # -> list[ChunkSpec]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Clause boundary patterns (Chinese regulatory documents) ──
CHAPTER_PATTERN = re.compile(
    r"^[  \t]*(第[一二三四五六七八九十百千\d]+章)[  \t]*(.*?)$",
    re.MULTILINE,
)
SECTION_PATTERN = re.compile(
    r"^[  \t]*(第[一二三四五六七八九十百千\d]+节)[  \t]*(.*?)$",
    re.MULTILINE,
)
ARTICLE_PATTERNS = [
    re.compile(r"^[  \t]*(第[一二三四五六七八九十百千\d]+条)[  \t]+(.*?)$", re.MULTILINE),
    re.compile(r"^[  \t]*(\d+\.\d+(?:\.\d+)?)\s+(.*?)$", re.MULTILINE),
    re.compile(r"^[  \t]*(§\d+(?:\.\d+)?)\s+(.*?)$", re.MULTILINE),
    re.compile(r"^[  \t]*（([一二三四五六七八九十百千]+)）\s*(.*?)$", re.MULTILINE),
]

# Minimum chars for a chunk (merge with previous if below this)
MIN_CHUNK_CHARS = 80
# Maximum chars for a chunk (split if exceeds this)
MAX_CHUNK_CHARS = 1500


@dataclass
class ChunkSpec:
    """A single clause chunk ready for embedding and storage."""

    text: str
    index: int
    chapter_title: str = ""
    article_ref: str = ""
    priority: str = "P2"


class ArticleChunker:
    """Structure-aware clause-level chunker for Chinese regulatory documents.

    Detection priority:
    1. Chapter boundaries (第X章)
    2. Article boundaries (第X条 / X.X / §X)
    3. Paragraph boundaries (double newline)
    4. Length-based fallback split
    """

    @classmethod
    def chunk(
        cls,
        text: str,
        title: str = "",
        category: str = "",
        priority: str = "P2",
        min_chars: int = MIN_CHUNK_CHARS,
        max_chars: int = MAX_CHUNK_CHARS,
        validate_input: bool = True,
    ) -> list[ChunkSpec]:
        """Chunk a regulatory document into clause-level chunks.

        Args:
            text: Full text of the document
            title: Document title
            category: Document category (laws_regulations/standards/etc.)
            priority: Priority level (P0/P1/P2)
            min_chars: Minimum chunk character count
            max_chars: Maximum chunk character count
            validate_input: If True (default), reject garbled input text
                           using is_text_garbled() before chunking

        Returns:
            List of ChunkSpec, ordered by position in document

        Raises:
            ValueError: If validate_input=True and text is garbled
        """
        if not text or not text.strip():
            return []

        # ── Layer 1 自查：拒绝垃圾文本进入分块 ──
        if validate_input:
            from app.modules.safety.knowledge.document_parser import is_text_garbled
            if is_text_garbled(text):
                raise ValueError(
                    f"ArticleChunker rejected garbled input: title='{title}' "
                    f"len={len(text)} — text failed is_text_garbled() check. "
                    f"The source document may be a scanned PDF or has corrupted content."
                )

        text = cls._normalize_whitespace(text)

        # Step 1: Try structure-aware splitting
        segments = cls._split_by_structure(text)

        # Step 2: Merge short segments with neighbors
        segments = cls._merge_short(segments, min_chars)

        # Step 3: Split oversized segments
        segments = cls._split_oversized(segments, max_chars)

        # Step 4: Build ChunkSpec with metadata
        chunks: list[ChunkSpec] = []
        current_chapter = ""
        current_article = ""

        for i, seg in enumerate(segments):
            # Try to extract chapter/article refs from the segment
            chapter_match = CHAPTER_PATTERN.search(seg)
            if chapter_match:
                current_chapter = chapter_match.group(0).strip()[:200]
                current_article = ""

            article_match = None
            for pat in ARTICLE_PATTERNS:
                article_match = pat.search(seg)
                if article_match:
                    break
            if article_match:
                current_article = article_match.group(0).strip()[:100]

            chunks.append(ChunkSpec(
                text=seg.strip(),
                index=i,
                chapter_title=current_chapter,
                article_ref=current_article,
                priority=priority,
            ))

        logger.info(
            "Chunked '%s': %d chars → %d chunks (avg %d chars/chunk)",
            title, len(text), len(chunks),
            sum(len(c.text) for c in chunks) // max(len(chunks), 1),
        )
        return chunks

    # ── Internal ──

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Normalize whitespace without destroying structure."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Collapse multiple blank lines to at most 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _split_by_structure(cls, text: str) -> list[str]:
        """Split text by article boundaries. Falls back to paragraph split."""
        segments: list[tuple[int, int]] = []

        # Find all article boundary positions
        for pat in ARTICLE_PATTERNS:
            for m in pat.finditer(text):
                pos = m.start()
                # Only use if not inside another match's range
                if not any(s <= pos < e for s, e in segments):
                    segments.append((pos, pos))

        # Also add chapter boundaries
        for m in CHAPTER_PATTERN.finditer(text):
            pos = m.start()
            if not any(s <= pos < e for s, e in segments):
                segments.append((pos, pos))

        # Sort by position
        segments.sort(key=lambda x: x[0])

        if len(segments) <= 1:
            # No clear structure — fall back to paragraph split
            return cls._split_by_paragraph(text)

        # Build chunks between boundaries
        result: list[str] = []
        for i, (start, _) in enumerate(segments):
            if i + 1 < len(segments):
                end = segments[i + 1][0]
            else:
                end = len(text)
            chunk = text[start:end].strip()
            if chunk:
                result.append(chunk)

        # Include text before first boundary
        if segments and segments[0][0] > 0:
            prefix = text[:segments[0][0]].strip()
            if prefix:
                result.insert(0, prefix)

        return result if result else cls._split_by_paragraph(text)

    @staticmethod
    def _split_by_paragraph(text: str) -> list[str]:
        """Fallback: split by paragraph breaks."""
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        return paras

    @classmethod
    def _merge_short(cls, segments: list[str], min_chars: int) -> list[str]:
        """Merge segments shorter than min_chars with neighbors."""
        if not segments:
            return segments

        result: list[str] = []
        buffer = ""

        for seg in segments:
            if len(seg) < min_chars and result:
                # Prepend to last result entry
                result[-1] = result[-1] + "\n" + seg
            elif buffer and len(buffer + seg) < min_chars:
                buffer = buffer + "\n" + seg
            else:
                if buffer:
                    result.append(buffer)
                buffer = seg

        if buffer:
            # If last buffer is short, merge with previous
            if result and len(buffer) < min_chars:
                result[-1] = result[-1] + "\n" + buffer
            else:
                result.append(buffer)

        return result

    @classmethod
    def _split_oversized(cls, segments: list[str], max_chars: int) -> list[str]:
        """Split segments exceeding max_chars at paragraph boundaries."""
        result: list[str] = []
        for seg in segments:
            if len(seg) <= max_chars:
                result.append(seg)
                continue

            # Split at double newlines within the segment
            sub_paras = [s.strip() for s in seg.split("\n\n") if s.strip()]
            current = ""
            for para in sub_paras:
                if len(current) + len(para) + 2 <= max_chars:
                    current = (current + "\n\n" + para) if current else para
                else:
                    if current:
                        result.append(current)
                    # If a single paragraph exceeds max_chars, split at sentence boundaries
                    if len(para) > max_chars:
                        sentences = cls._split_sentences(para, max_chars)
                        result.extend(sentences)
                    else:
                        current = para
            if current:
                result.append(current)

        return result

    @staticmethod
    def _split_sentences(text: str, max_chars: int) -> list[str]:
        """Split a long paragraph at sentence boundaries."""
        # Chinese sentence endings
        sentence_breaks = re.split(r"(?<=[。；;！!？?])", text)
        result: list[str] = []
        current = ""
        for s in sentence_breaks:
            if len(current) + len(s) <= max_chars:
                current += s
            else:
                if current:
                    result.append(current.strip())
                # If a single sentence is still too long, hard cut
                if len(s) > max_chars:
                    for i in range(0, len(s), max_chars):
                        result.append(s[i:i + max_chars].strip())
                else:
                    current = s
        if current.strip():
            result.append(current.strip())
        return result
