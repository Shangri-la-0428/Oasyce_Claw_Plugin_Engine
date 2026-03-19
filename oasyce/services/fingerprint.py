"""
Content fingerprinting using SimHash (text) and perceptual hashing (images).
Used for near-duplicate detection and infringement identification.
"""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# SimHash
# ---------------------------------------------------------------------------


def _shingle(text: str, n: int = 3) -> List[str]:
    """Tokenize text into character-level n-grams (shingles)."""
    text = text.lower().strip()
    if len(text) < n:
        return [text] if text else []
    return [text[i : i + n] for i in range(len(text) - n + 1)]


def _hash64(token: str) -> int:
    """Hash a token to a 64-bit integer using MD5 (deterministic, fast)."""
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return struct.unpack("<Q", digest[:8])[0]


def simhash(text: str, shingle_size: int = 3) -> int:
    """Compute a 64-bit SimHash fingerprint for *text*.

    Steps:
      1. Break text into shingles (character n-grams).
      2. Hash each shingle to a 64-bit value.
      3. For each bit position, sum +1 (if bit=1) or -1 (if bit=0).
      4. Final fingerprint: bit i is 1 if the sum for that position > 0.
    """
    tokens = _shingle(text, shingle_size)
    if not tokens:
        return 0

    # Accumulator for 64 bit positions
    v = [0] * 64

    for token in tokens:
        h = _hash64(token)
        for i in range(64):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1

    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def simhash_distance(a: int, b: int) -> int:
    """Hamming distance between two 64-bit SimHash values."""
    x = a ^ b
    # Count set bits (Kernighan's method)
    count = 0
    while x:
        x &= x - 1
        count += 1
    return count


# ---------------------------------------------------------------------------
# MinHash
# ---------------------------------------------------------------------------


def _make_hash_funcs(k: int = 128, seed: int = 42) -> List[Tuple[int, int]]:
    """Generate *k* hash function coefficients (a, b) for universal hashing.

    Each function is h(x) = (a*x + b) mod p, where p is a large prime.
    """
    import random

    rng = random.Random(seed)
    # Mersenne prime larger than any 64-bit hash
    _PRIME = (1 << 61) - 1
    funcs: List[Tuple[int, int]] = []
    for _ in range(k):
        a = rng.randint(1, _PRIME - 1)
        b = rng.randint(0, _PRIME - 1)
        funcs.append((a, b))
    return funcs


# Module-level default hash functions (reused across calls for consistency)
_DEFAULT_K = 128
_HASH_FUNCS = _make_hash_funcs(_DEFAULT_K)
_PRIME = (1 << 61) - 1


def minhash_signature(tokens: set, k: int = _DEFAULT_K) -> List[int]:
    """Compute a MinHash signature of length *k* for a set of tokens.

    Each element of the signature is the minimum hash value under one of
    *k* independent hash functions.
    """
    funcs = _HASH_FUNCS[:k]
    if not tokens:
        return [0] * k

    # Pre-hash tokens to integers
    hashed = [_hash64(t) if isinstance(t, str) else t for t in tokens]

    sig: List[int] = []
    for a, b in funcs:
        min_val = float("inf")
        for h in hashed:
            val = (a * h + b) % _PRIME
            if val < min_val:
                min_val = val
        sig.append(min_val)
    return sig


def minhash_similarity(sig_a: List[int], sig_b: List[int]) -> float:
    """Estimated Jaccard similarity from two MinHash signatures."""
    if not sig_a or not sig_b:
        return 0.0
    k = min(len(sig_a), len(sig_b))
    matches = sum(1 for i in range(k) if sig_a[i] == sig_b[i])
    return matches / k


# ---------------------------------------------------------------------------
# FingerprintStore — SQLite-backed persistence
# ---------------------------------------------------------------------------


class FingerprintStore:
    """Persistent store for SimHash fingerprints, backed by SQLite.

    Supports adding fingerprints and finding near-duplicates efficiently.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fingerprints (
                asset_id   TEXT PRIMARY KEY,
                simhash    TEXT NOT NULL,
                minhash    BLOB,
                created_at REAL NOT NULL DEFAULT (julianday('now'))
            )
            """
        )
        self._conn.commit()

    # -- public API --

    def add(self, asset_id: str, content: str) -> int:
        """Fingerprint *content* and store it under *asset_id*.

        Returns the 64-bit SimHash value.
        """
        sh = simhash(content)
        tokens = set(_shingle(content))
        mh = minhash_signature(tokens)
        mh_blob = _pack_minhash(mh)
        # Store simhash as hex string to avoid SQLite signed-int overflow
        self._conn.execute(
            "INSERT OR REPLACE INTO fingerprints (asset_id, simhash, minhash) VALUES (?, ?, ?)",
            (asset_id, format(sh, "016x"), mh_blob),
        )
        self._conn.commit()
        return sh

    def find_similar(self, content: str, threshold: int = 3) -> List[str]:
        """Find asset IDs whose SimHash distance to *content* is <= *threshold*.

        Args:
            content: The text to compare against.
            threshold: Maximum Hamming distance (default 3).

        Returns:
            List of matching asset IDs, sorted by distance (closest first).
        """
        sh = simhash(content)
        rows = self._conn.execute("SELECT asset_id, simhash FROM fingerprints").fetchall()
        matches: List[Tuple[int, str]] = []
        for asset_id, stored_sh_hex in rows:
            stored_sh = int(stored_sh_hex, 16)
            dist = simhash_distance(sh, stored_sh)
            if dist <= threshold:
                matches.append((dist, asset_id))
        matches.sort(key=lambda t: t[0])
        return [aid for _, aid in matches]

    def find_similar_minhash(self, content: str, threshold: float = 0.8) -> List[str]:
        """Find asset IDs whose MinHash (Jaccard) similarity >= *threshold*.

        Returns:
            List of matching asset IDs, sorted by similarity (highest first).
        """
        tokens = set(_shingle(content))
        sig = minhash_signature(tokens)
        rows = self._conn.execute(
            "SELECT asset_id, minhash FROM fingerprints WHERE minhash IS NOT NULL"
        ).fetchall()
        matches: List[Tuple[float, str]] = []
        for asset_id, mh_blob in rows:
            stored_sig = _unpack_minhash(mh_blob)
            sim = minhash_similarity(sig, stored_sig)
            if sim >= threshold:
                matches.append((sim, asset_id))
        matches.sort(key=lambda t: -t[0])
        return [aid for _, aid in matches]

    def get(self, asset_id: str) -> Optional[int]:
        """Retrieve the SimHash for *asset_id*, or ``None``."""
        row = self._conn.execute(
            "SELECT simhash FROM fingerprints WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        return int(row[0], 16) if row else None

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _pack_minhash(sig: List[int]) -> bytes:
    """Serialize a MinHash signature to bytes (big-endian uint64 array)."""
    return b"".join(struct.pack(">Q", v) for v in sig)


def _unpack_minhash(blob: bytes) -> List[int]:
    """Deserialize a MinHash signature from bytes."""
    count = len(blob) // 8
    return [struct.unpack(">Q", blob[i * 8 : (i + 1) * 8])[0] for i in range(count)]
