"""BM25 text scorer for Chinese regulatory document retrieval.

Replaces simple n-gram overlap counting with proper TF-IDF weighted
scoring (BM25 formula). Uses numpy for efficient computation.

BM25 formula:
  score(D, Q) = sum(IDF(qi) * (fi * (k1 + 1)) / (fi + k1 * (1 - b + b * dl/avgdl)))
  where:
    fi = term frequency in document
    dl = document length
    avgdl = average document length
    k1 = 1.5 (term frequency saturation)
    b = 0.75 (length normalization)

Usage:
    bm25 = BM25Scorer()
    bm25.index(corpus: list[str])  # pre-compute term stats
    scores = bm25.score_batch(query: str, doc_indices: list[int] | None = None)
    # -> list[float]
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)


class BM25Scorer:
    """BM25 text scorer optimized for Chinese regulatory text.

    Uses character bigrams + words as tokens. Pre-computes IDF values
    at index time and scores via numpy vectorized operations.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        # Index state
        self._corpus: list[str] = []
        self._tokenized: list[list[str]] = []
        self._doc_lens: np.ndarray | None = None
        self._avgdl: float = 1.0
        self._idf: dict[str, float] = {}
        self._indexed: bool = False

    def index(self, corpus: list[str]) -> None:
        """Build BM25 index from corpus of document texts.

        Args:
            corpus: List of text strings to index
        """
        if not corpus:
            return

        self._corpus = list(corpus)
        self._tokenized = [self._tokenize(doc) for doc in corpus]
        self._doc_lens = np.array([len(t) for t in self._tokenized], dtype=np.float32)
        self._avgdl = float(np.mean(self._doc_lens)) if len(self._doc_lens) > 0 else 1.0

        # Compute IDF
        n = len(corpus)
        df: Counter[str] = Counter()
        for tokens in self._tokenized:
            df.update(set(tokens))

        self._idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        self._indexed = True

        logger.debug(
            "BM25 indexed %d docs, avg_len=%.0f chars, vocab=%d terms",
            n, self._avgdl, len(self._idf),
        )

    def score(self, query: str, doc_index: int) -> float:
        """Score a single document against a query.

        Returns BM25 score (higher = more relevant).
        """
        if not self._indexed or doc_index >= len(self._tokenized):
            return 0.0

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return 0.0

        doc_tokens = self._tokenized[doc_index]
        dl = float(self._doc_lens[doc_index]) if self._doc_lens is not None else 1.0
        tf = Counter(doc_tokens)

        score = 0.0
        for qt in query_tokens:
            idf = self._idf.get(qt, 0.0)
            if idf == 0.0:
                continue
            fi = tf.get(qt, 0)
            if fi == 0:
                continue
            numerator = fi * (self.k1 + 1)
            denominator = fi + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
            score += idf * numerator / denominator

        return score

    def score_batch(self, query: str) -> list[float]:
        """Score all indexed documents against a query.

        Returns list of scores, one per document (same order as index).
        """
        if not self._indexed:
            return []

        return [self.score(query, i) for i in range(len(self._tokenized))]

    def score_top_k(
        self, query: str, top_k: int = 30, min_score: float = 0.0,
    ) -> list[tuple[int, float]]:
        """Score all documents and return top-k indices with scores.

        Returns:
            List of (doc_index, score) sorted by score descending
        """
        if not self._indexed:
            return []

        scores = self.score_batch(query)
        indices = np.argsort(scores)[::-1]  # descending

        results = []
        for idx in indices:
            s = scores[idx]
            if s <= min_score or len(results) >= top_k:
                break
            results.append((int(idx), float(s)))

        return results

    # ── Tokenization ──

    @staticmethod
    @lru_cache(maxsize=1024)
    def _tokenize(text: str) -> tuple[str, ...]:
        """Tokenize Chinese text into character bigrams + individual chars.

        Uses tuple for hashability (LRU cache).
        Example: '防爆堵头' -> ('防爆', '爆堵', '堵头', '防', '爆', '堵', '头')
        """
        if not text:
            return ()

        tokens: list[str] = []

        # Remove punctuation/whitespace for token extraction
        import re
        cn = re.sub(r'[^一-鿿]', '', text)
        if not cn:
            # Non-Chinese: use whitespace-split words
            words = text.lower().split()
            return tuple(words)

        # Character bigrams
        for i in range(len(cn) - 1):
            tokens.append(cn[i:i + 2])

        # Individual characters (for single-char queries)
        tokens.extend(cn)

        return tuple(tokens)


# ═══════════════════════════════════════════════════════════════
# Singleton for reuse across queries
# ═══════════════════════════════════════════════════════════════

_bm25_scorer: BM25Scorer | None = None


def get_bm25_scorer() -> BM25Scorer:
    """Get or create the singleton BM25Scorer instance."""
    global _bm25_scorer
    if _bm25_scorer is None:
        _bm25_scorer = BM25Scorer()
    return _bm25_scorer
