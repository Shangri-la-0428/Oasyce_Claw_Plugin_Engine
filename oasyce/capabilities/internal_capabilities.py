"""
Built-in protocol internal capabilities.

These are fallback implementations used when no external provider
has registered the corresponding capability on the network.
Pure Python, zero external dependencies.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List


# ── Stop words for tag generation ─────────────────────────────────────
_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "because",
        "but",
        "and",
        "or",
        "if",
        "while",
        "about",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "they",
        "them",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "up",
        "down",
        "also",
        "data",
        "file",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{2,}")


def _tokenize(text: str) -> List[str]:
    """Extract lowercase alpha tokens, removing stop words."""
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in _STOP_WORDS]


def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors (dicts)."""
    if not vec_a or not vec_b:
        return 0.0

    common_keys = set(vec_a) & set(vec_b)
    if not common_keys:
        return 0.0

    dot = sum(vec_a[k] * vec_b[k] for k in common_keys)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _tf_vector(tokens: List[str]) -> Dict[str, float]:
    """Term frequency vector from token list."""
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {t: c / total for t, c in counts.items()}


class AssetSimilarityChecker:
    """Check how similar a new asset is to existing registered assets.

    Uses TF-IDF-like cosine similarity on description + tags.
    Pure Python implementation, no external dependencies.
    """

    def check(
        self,
        description: str,
        tags: List[str],
        existing_assets: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Check similarity against existing assets.

        Args:
            description: Text description of the new asset
            tags: List of tags for the new asset
            existing_assets: List of dicts with 'id', 'description', 'tags'

        Returns:
            dict with:
                - max_score: highest similarity score (0.0 - 1.0)
                - is_duplicate: True if max_score > 0.85
                - top_matches: list of (id, score) for top 3 matches
        """
        if not description and not tags:
            return {"max_score": 0.0, "is_duplicate": False, "top_matches": []}

        if not existing_assets:
            return {"max_score": 0.0, "is_duplicate": False, "top_matches": []}

        # Build query vector from description + tags
        query_tokens = _tokenize(description) + [t.lower() for t in tags]
        query_vec = _tf_vector(query_tokens)

        scores = []
        for asset in existing_assets:
            asset_tokens = _tokenize(asset.get("description", ""))
            asset_tokens += [t.lower() for t in asset.get("tags", [])]
            asset_vec = _tf_vector(asset_tokens)

            sim = _cosine_similarity(query_vec, asset_vec)

            # Tag overlap bonus (up to 0.2)
            query_tags = set(t.lower() for t in tags)
            asset_tags = set(t.lower() for t in asset.get("tags", []))
            if query_tags and asset_tags:
                tag_overlap = len(query_tags & asset_tags) / max(len(query_tags | asset_tags), 1)
                sim = min(1.0, sim * 0.8 + tag_overlap * 0.2)

            scores.append((asset.get("id", "unknown"), sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[:3]
        max_score = top[0][1] if top else 0.0

        return {
            "max_score": round(max_score, 4),
            "is_duplicate": max_score > 0.85,
            "top_matches": [{"id": aid, "score": round(s, 4)} for aid, s in top],
        }


class AssetTagGenerator:
    """Generate suggested tags and description from content text.

    Uses keyword extraction (term frequency) — pure Python, no LLM.
    """

    def generate(self, content: str) -> Dict[str, Any]:
        """Generate tags and a summary description.

        Args:
            content: Text content to analyze

        Returns:
            dict with:
                - tags: list of suggested tags (up to 8)
                - description: one-line summary (first meaningful sentence)
        """
        if not content or not content.strip():
            return {"tags": [], "description": ""}

        tokens = _tokenize(content)
        if not tokens:
            return {"tags": [], "description": ""}

        # Top keywords by frequency
        counts = Counter(tokens)
        top_tags = [word for word, _ in counts.most_common(8)]

        # Description: first non-empty line, truncated
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        first_line = lines[0] if lines else ""
        if len(first_line) > 120:
            first_line = first_line[:117] + "..."

        return {
            "tags": top_tags,
            "description": first_line,
        }
