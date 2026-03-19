"""
Steganographic watermarking for data assets.
Embeds invisible ownership proof into content.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import struct
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Zero-width Unicode characters used for text watermarking
_ZW_CHARS = [
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE (BOM)
]

# Binary watermark magic markers
_MAGIC_START = b"\x00OAS_WM\x01"
_MAGIC_END = b"\x01WM_OAS\x00"


# ---------------------------------------------------------------------------
# Text watermarking — zero-width characters
# ---------------------------------------------------------------------------


def _bits_from_bytes(data: bytes) -> List[int]:
    """Convert bytes to a list of bits (MSB first)."""
    bits: List[int] = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _bytes_from_bits(bits: List[int]) -> bytes:
    """Convert a list of bits back to bytes."""
    result = bytearray()
    for i in range(0, len(bits) - 7, 8):
        val = 0
        for j in range(8):
            val = (val << 1) | bits[i + j]
        result.append(val)
    return bytes(result)


def _encode_payload(payload: str) -> bytes:
    """Encode a payload string with a length prefix for unambiguous extraction."""
    raw = payload.encode("utf-8")
    # 2-byte big-endian length + payload + 2-byte CRC16
    length = struct.pack(">H", len(raw))
    body = length + raw
    crc = _crc16(body)
    return body + struct.pack(">H", crc)


def _decode_payload(data: bytes) -> Optional[str]:
    """Decode a length-prefixed payload. Returns None on CRC mismatch."""
    if len(data) < 4:
        return None
    length = struct.unpack(">H", data[:2])[0]
    if len(data) < 2 + length + 2:
        return None
    body = data[: 2 + length]
    expected_crc = struct.unpack(">H", data[2 + length : 2 + length + 2])[0]
    if _crc16(body) != expected_crc:
        return None
    try:
        return body[2:].decode("utf-8")
    except UnicodeDecodeError:
        return None


def _crc16(data: bytes) -> int:
    """Simple CRC-16/CCITT."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def embed_text_watermark(text: str, payload: str) -> str:
    """Embed *payload* into *text* using zero-width Unicode characters.

    Each pair of bits is encoded as one of four zero-width chars and inserted
    between words at evenly-spaced positions throughout the text.
    """
    encoded = _encode_payload(payload)
    bits = _bits_from_bytes(encoded)

    # Pad bits to even length (we encode 2 bits per ZW char)
    if len(bits) % 2:
        bits.append(0)

    zw_chars: List[str] = []
    for i in range(0, len(bits), 2):
        idx = bits[i] * 2 + bits[i + 1]
        zw_chars.append(_ZW_CHARS[idx])

    # Split text into words and distribute ZW chars between them
    words = text.split(" ")
    if len(words) < 2:
        # Not enough words — prepend the whole ZW sequence
        return "".join(zw_chars) + text

    # Distribute ZW chars evenly across word gaps
    n_gaps = len(words) - 1
    result_parts: List[str] = [words[0]]
    for gap_idx in range(n_gaps):
        # Which ZW chars go into this gap?
        start = gap_idx * len(zw_chars) // n_gaps
        end = (gap_idx + 1) * len(zw_chars) // n_gaps
        zw_segment = "".join(zw_chars[start:end])
        result_parts.append(" " + zw_segment + words[gap_idx + 1])

    return "".join(result_parts)


def extract_text_watermark(watermarked_text: str) -> Optional[str]:
    """Extract the watermark payload from *watermarked_text*.

    Returns None if no valid watermark is found.
    """
    # Collect all zero-width characters in order
    zw_set = set(_ZW_CHARS)
    zw_lookup = {ch: idx for idx, ch in enumerate(_ZW_CHARS)}

    collected: List[int] = []
    for ch in watermarked_text:
        if ch in zw_set:
            collected.append(zw_lookup[ch])

    if not collected:
        return None

    # Convert ZW indices back to bits
    bits: List[int] = []
    for idx in collected:
        bits.append((idx >> 1) & 1)
        bits.append(idx & 1)

    data = _bytes_from_bits(bits)
    return _decode_payload(data)


# ---------------------------------------------------------------------------
# Binary watermarking — magic marker + payload trailer
# ---------------------------------------------------------------------------


def embed_binary_watermark(data: bytes, payload: str, key: bytes = b"") -> bytes:
    """Embed *payload* into binary *data* as an appended trailer.

    The trailer format:
        MAGIC_START + encrypted_payload + MAGIC_END

    If *key* is provided, the payload is XOR-encrypted with a key-derived
    stream.  Otherwise it is stored as-is.
    """
    raw = _encode_payload(payload)
    if key:
        raw = _xor_crypt(raw, key)
    return data + _MAGIC_START + raw + _MAGIC_END


def extract_binary_watermark(data: bytes, key: bytes = b"") -> Optional[str]:
    """Extract the watermark payload from binary *data*.

    Returns None if no valid watermark is found.
    """
    start = data.rfind(_MAGIC_START)
    if start < 0:
        return None
    payload_start = start + len(_MAGIC_START)
    end = data.find(_MAGIC_END, payload_start)
    if end < 0:
        return None
    raw = data[payload_start:end]
    if key:
        raw = _xor_crypt(raw, key)
    return _decode_payload(raw)


def _xor_crypt(data: bytes, key: bytes) -> bytes:
    """XOR *data* with a repeating key-derived stream (SHA-256 based)."""
    stream = b""
    counter = 0
    while len(stream) < len(data):
        block = hashlib.sha256(key + struct.pack(">I", counter)).digest()
        stream += block
        counter += 1
    return bytes(a ^ b for a, b in zip(data, stream[: len(data)]))


# ---------------------------------------------------------------------------
# CSV / tabular data watermarking
# ---------------------------------------------------------------------------


def embed_csv_watermark(
    csv_content: str,
    payload: str,
    epsilon: float = 0.001,
) -> str:
    """Watermark CSV data by adding tiny noise to numerical values.

    The noise pattern encodes *payload*.  Only values that parse as float
    are modified; non-numeric cells are left untouched.

    Args:
        csv_content: Raw CSV text.
        payload: String to embed.
        epsilon: Maximum noise magnitude added to each value.

    Returns:
        Watermarked CSV text.
    """
    encoded = _encode_payload(payload)
    bits = _bits_from_bytes(encoded)

    lines = csv_content.split("\n")
    result_lines: List[str] = []
    bit_idx = 0

    for line_no, line in enumerate(lines):
        if not line.strip() or line_no == 0:
            # Skip empty lines and header row
            result_lines.append(line)
            continue
        cells = line.split(",")
        new_cells: List[str] = []
        for cell in cells:
            stripped = cell.strip()
            if bit_idx < len(bits):
                try:
                    val = float(stripped)
                    # Encode one bit: 0 → subtract epsilon/2, 1 → add epsilon/2
                    if bits[bit_idx] == 1:
                        val += epsilon / 2
                    else:
                        val -= epsilon / 2
                    bit_idx += 1
                    new_cells.append(str(val))
                    continue
                except ValueError:
                    pass
            new_cells.append(cell)
        result_lines.append(",".join(new_cells))

    return "\n".join(result_lines)


def extract_csv_watermark(
    original: str,
    watermarked: str,
    key: str = "",
) -> Optional[str]:
    """Extract the watermark from a watermarked CSV by comparing with original.

    Args:
        original: The original (un-watermarked) CSV content.
        watermarked: The watermarked CSV content.
        key: Unused (reserved for future keyed extraction).

    Returns:
        Extracted payload string, or None on failure.
    """
    orig_lines = original.split("\n")
    wm_lines = watermarked.split("\n")

    bits: List[int] = []

    for line_no in range(min(len(orig_lines), len(wm_lines))):
        if not orig_lines[line_no].strip() or line_no == 0:
            continue
        orig_cells = orig_lines[line_no].split(",")
        wm_cells = wm_lines[line_no].split(",")
        for oc, wc in zip(orig_cells, wm_cells):
            try:
                ov = float(oc.strip())
                wv = float(wc.strip())
                diff = wv - ov
                if diff > 0:
                    bits.append(1)
                else:
                    bits.append(0)
            except ValueError:
                continue

    data = _bytes_from_bits(bits)
    return _decode_payload(data)


# ---------------------------------------------------------------------------
# WatermarkService — auto-detect content type and apply watermark
# ---------------------------------------------------------------------------


class WatermarkService:
    """High-level watermarking service that auto-detects content type.

    Usage::

        svc = WatermarkService()
        wm = svc.watermark("Hello world", "asset123", "0xOwner")
        info = svc.verify(wm)
        # info == {"asset_id": "asset123", "owner": "0xOwner"}
    """

    def watermark(
        self,
        content: str | bytes,
        asset_id: str,
        owner: str,
    ) -> str | bytes:
        """Watermark *content* with ownership information.

        Auto-detects content type:
          - ``bytes`` → binary watermark
          - CSV-like ``str`` → CSV watermark (with text watermark in header)
          - Plain ``str`` → text watermark
        """
        payload = json.dumps({"asset_id": asset_id, "owner": owner})

        if isinstance(content, bytes):
            return embed_binary_watermark(content, payload)

        if self._looks_like_csv(content):
            return embed_csv_watermark(content, payload)

        return embed_text_watermark(content, payload)

    def verify(self, content: str | bytes) -> Optional[dict]:
        """Extract and return ownership info from watermarked content.

        Returns dict with ``asset_id`` and ``owner``, or None.
        """
        if isinstance(content, bytes):
            raw = extract_binary_watermark(content)
        else:
            raw = extract_text_watermark(content)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if "asset_id" in data and "owner" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    @staticmethod
    def _looks_like_csv(text: str) -> bool:
        """Heuristic: text looks like CSV if the first 3 lines have commas."""
        lines = [l for l in text.split("\n") if l.strip()][:3]
        if len(lines) < 2:
            return False
        return all("," in l for l in lines)
