"""Lightweight deterministic text scoring utilities.

No LLM and no external index is involved: lexical overlap (BM25-style
saturation over query terms) plus exponential recency decay. This keeps
hosted cost predictable and results fully reproducible.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")

_STOPWORDS = {
    "the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "his",
    "her", "its", "our", "their", "me", "him", "us", "them",
    "and", "or", "but", "if", "then", "else", "when", "at", "by", "for",
    "with", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "to", "from", "up", "down", "in",
    "out", "on", "off", "over", "under", "again", "further", "once", "here",
    "there", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "can", "will", "just", "should", "now", "of", "do",
    "does", "did", "have", "has", "had", "having", "would", "could",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    "how", "why", "where", "am", "are", "was", "were", "say", "said",
    "tell", "told", "ask", "asked", "know", "knew", "want", "wanted",
}


def _stem(token: str) -> str:
    """Naive suffix normalization: plural / third-person-s collapses so
    `lives`~`live`, `likes`~`like` match. Keep short words and -ss/-us
    endings untouched."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(tok) for tok in _TOKEN_RE.findall(text.lower()) if tok not in _STOPWORDS]


def term_counts(text: str) -> Counter:
    return Counter(tokenize(text))


def lexical_score(query_counts: Counter, doc_counts: Counter) -> float:
    """Saturated BM25-style overlap, summed over distinct query terms.

    Each distinct query term contributes up to ~0.25 points (saturating at
    2 occurrences in the document, k1 = 1), so single-term hits stay well
    above the abstention threshold while zero-overlap documents score 0.
    """
    if not query_counts or not doc_counts:
        return 0.0
    total = 0.0
    for term, qtf in query_counts.items():
        dtf = doc_counts.get(term, 0)
        if dtf == 0:
            continue
        sat = dtf * (1 + 1) / (dtf + 1)  # k1 = 1 saturation curve
        total += min(qtf, 2) / 2 * min(sat, 2) / 2
    return total


def recency_factor(created_at_ms: float, half_life_ms: float, now_ms: float | None = None) -> float:
    """Exponential decay in (0, 1]; fresh records near 1."""
    if now_ms is None:
        now_ms = time.time() * 1000
    age = max(0.0, now_ms - created_at_ms)
    return math.pow(0.5, age / half_life_ms)


def iso_from_ms(ms: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))
