"""Merkle Tree implementation for block transaction hashing."""

from __future__ import annotations

import hashlib
from typing import List


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def merkle_root(tx_ids: List[str]) -> str:
    """Compute the Merkle Root of a list of transaction IDs.

    Standard binary Merkle Tree:
    - Leaf nodes = SHA-256(tx_id)
    - If the number of nodes at a level is odd, duplicate the last node
    - Returns the root hash as a hex string
    """
    if not tx_ids:
        return "0" * 64

    level = [_sha256(tx_id) for tx_id in tx_ids]

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        next_level = []
        for i in range(0, len(level), 2):
            combined = _sha256(level[i] + level[i + 1])
            next_level.append(combined)
        level = next_level

    return level[0]
