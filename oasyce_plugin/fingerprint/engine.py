"""Fingerprint distribution watermarking engine.

Generates unique fingerprints per caller and embeds them into text or binary
assets using steganography, enabling leak tracing without altering the
functional content.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
from typing import Optional


# Magic bytes for binary watermark trailer
_MAGIC = b"\x0a\x5a\xce\xf0"
_TRAILER_VERSION = 1


class FingerprintEngine:
    """Generate and embed distribution fingerprints into assets."""

    def __init__(self, signing_key_hex: str) -> None:
        self._key = bytes.fromhex(signing_key_hex)

    # ── Fingerprint generation ────────────────────────────────────────

    def generate_fingerprint(
        self, asset_id: str, caller_id: str, timestamp: int
    ) -> str:
        """Deterministic HMAC-SHA256 fingerprint from caller+asset+time."""
        msg = f"{caller_id}:{asset_id}:{timestamp}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    # ── Text steganography (whitespace encoding) ─────────────────────

    @staticmethod
    def embed_text(content: str, fingerprint: str) -> str:
        """Embed *fingerprint* into text via trailing whitespace steganography.

        Each bit is encoded as a space (0) or tab (1) appended after the
        existing line content.  The fingerprint is redundantly embedded
        starting every 256 lines so that partial content still carries the
        watermark.
        """
        fp_bits = _hex_to_bits(fingerprint)
        lines = content.split("\n")
        out: list[str] = []

        for idx, line in enumerate(lines):
            # Strip any existing trailing whitespace to avoid confusion
            stripped = line.rstrip()
            bit_idx = idx % len(fp_bits)
            marker = " " if fp_bits[bit_idx] == "0" else "\t"
            out.append(stripped + marker)

        return "\n".join(out)

    @staticmethod
    def extract_text(watermarked: str) -> Optional[str]:
        """Extract fingerprint from whitespace-watermarked text.

        Uses majority vote across redundant copies for robustness.
        """
        lines = watermarked.split("\n")
        if not lines:
            return None

        # We need at least 256*4 = 1024 bits → 1024 lines for one full
        # fingerprint (256-bit / 64 hex chars).  But we also support
        # shorter content by using however many bits we can read.
        fp_len_bits = 64 * 4  # 64 hex chars * 4 bits each = 256 bits

        # Collect votes for each bit position
        votes: dict[int, list[int]] = {}
        for idx, line in enumerate(lines):
            if not line:
                continue
            last_char = line[-1]
            if last_char == " ":
                bit = 0
            elif last_char == "\t":
                bit = 1
            else:
                continue
            bit_pos = idx % fp_len_bits
            votes.setdefault(bit_pos, []).append(bit)

        if not votes:
            return None

        # Need enough bits for at least a full fingerprint
        max_bit = max(votes.keys())
        if max_bit < fp_len_bits - 1:
            # Check if we have enough for a shorter fingerprint — but our
            # fingerprints are always 64 hex chars (256 bits → 1024 bits),
            # so if we don't have all positions, the content was too short
            # or not watermarked.  Try with what we have.
            pass

        # Majority vote
        bits: list[str] = []
        for i in range(fp_len_bits):
            v = votes.get(i)
            if v is None:
                return None
            ones = sum(v)
            zeros = len(v) - ones
            bits.append("1" if ones >= zeros else "0")

        return _bits_to_hex(bits)

    # ── Binary watermarking (trailer block) ──────────────────────────

    @staticmethod
    def embed_binary(data: bytes, fingerprint: str) -> bytes:
        """Append a fingerprint trailer to binary data.

        Format: MAGIC(4) + VERSION(1) + FINGERPRINT(64 bytes ascii) + CRC32(4)
        """
        fp_bytes = fingerprint.encode("ascii")
        payload = _MAGIC + struct.pack("B", _TRAILER_VERSION) + fp_bytes
        crc = struct.pack(">I", _crc32(payload))
        return data + payload + crc

    @staticmethod
    def extract_binary(data: bytes) -> Optional[str]:
        """Extract fingerprint from binary trailer, if present."""
        # Trailer: MAGIC(4) + VER(1) + FP(64) + CRC(4) = 73 bytes
        trailer_len = 4 + 1 + 64 + 4
        if len(data) < trailer_len:
            return None

        trailer = data[-trailer_len:]
        magic = trailer[:4]
        if magic != _MAGIC:
            return None

        version = trailer[4]
        if version != _TRAILER_VERSION:
            return None

        fp_bytes = trailer[5:69]
        crc_stored = struct.unpack(">I", trailer[69:73])[0]

        # Verify CRC
        payload = trailer[:69]
        if _crc32(payload) != crc_stored:
            return None

        try:
            fp = fp_bytes.decode("ascii")
            # Validate it looks like a hex string
            int(fp, 16)
            return fp
        except (UnicodeDecodeError, ValueError):
            return None


# ── Helpers ──────────────────────────────────────────────────────────

def _hex_to_bits(hex_str: str) -> str:
    """Convert a hex string to a binary string of '0' and '1'."""
    return bin(int(hex_str, 16))[2:].zfill(len(hex_str) * 4)


def _bits_to_hex(bits: list[str]) -> str:
    """Convert a list of bit characters back to a hex string."""
    val = int("".join(bits), 2)
    hex_len = len(bits) // 4
    return format(val, f"0{hex_len}x")


def _crc32(data: bytes) -> int:
    """CRC32 checksum (unsigned)."""
    import binascii
    return binascii.crc32(data) & 0xFFFFFFFF
