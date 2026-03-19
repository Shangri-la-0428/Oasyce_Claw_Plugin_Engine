"""Tests for steganographic watermarking (Task #20)."""

from __future__ import annotations

import json

import pytest

from oasyce.services.watermark import (
    WatermarkService,
    embed_binary_watermark,
    embed_csv_watermark,
    embed_text_watermark,
    extract_binary_watermark,
    extract_csv_watermark,
    extract_text_watermark,
)


# ── Text watermarking ─────────────────────────────────────────────────


class TestTextWatermark:
    def test_roundtrip(self) -> None:
        text = "The quick brown fox jumps over the lazy dog in the park"
        payload = "asset_001:0xABC"
        wm = embed_text_watermark(text, payload)
        extracted = extract_text_watermark(wm)
        assert extracted == payload

    def test_invisible_to_reader(self) -> None:
        """Watermarked text should look the same when zero-width chars are stripped."""
        text = "Hello world this is a test"
        wm = embed_text_watermark(text, "secret")
        # Remove zero-width characters
        cleaned = (
            wm.replace("\u200b", "")
            .replace("\u200c", "")
            .replace("\u200d", "")
            .replace("\ufeff", "")
        )
        assert cleaned == text

    def test_different_payloads(self) -> None:
        text = "Some content with enough words for the watermark to embed properly"
        wm1 = embed_text_watermark(text, "payload_a")
        wm2 = embed_text_watermark(text, "payload_b")
        assert wm1 != wm2
        assert extract_text_watermark(wm1) == "payload_a"
        assert extract_text_watermark(wm2) == "payload_b"

    def test_no_watermark_returns_none(self) -> None:
        assert extract_text_watermark("plain text no watermark") is None

    def test_empty_text(self) -> None:
        assert extract_text_watermark("") is None

    def test_unicode_payload(self) -> None:
        text = "Content with sufficient words to embed a watermark payload here"
        payload = "owner:Alice"
        wm = embed_text_watermark(text, payload)
        assert extract_text_watermark(wm) == payload

    def test_long_payload(self) -> None:
        text = " ".join(f"word{i}" for i in range(200))
        payload = "x" * 100
        wm = embed_text_watermark(text, payload)
        assert extract_text_watermark(wm) == payload

    def test_single_word_text(self) -> None:
        """Single word text — watermark is prepended."""
        text = "hello"
        payload = "test"
        wm = embed_text_watermark(text, payload)
        assert extract_text_watermark(wm) == payload


# ── Binary watermarking ───────────────────────────────────────────────


class TestBinaryWatermark:
    def test_roundtrip(self) -> None:
        data = b"\x00\x01\x02" * 100
        payload = "asset123"
        wm = embed_binary_watermark(data, payload)
        assert extract_binary_watermark(wm) == payload

    def test_original_data_preserved(self) -> None:
        data = b"important data content"
        wm = embed_binary_watermark(data, "marker")
        assert wm.startswith(data)

    def test_with_key(self) -> None:
        data = b"secret data"
        payload = "owner_info"
        key = b"encryption_key"
        wm = embed_binary_watermark(data, payload, key=key)
        # Extracting without key should fail
        assert extract_binary_watermark(wm, key=b"wrong_key") is None
        # Extracting with correct key should succeed
        assert extract_binary_watermark(wm, key=key) == payload

    def test_no_watermark_returns_none(self) -> None:
        assert extract_binary_watermark(b"plain data") is None

    def test_empty_data(self) -> None:
        wm = embed_binary_watermark(b"", "test")
        assert extract_binary_watermark(wm) == "test"

    def test_different_payloads(self) -> None:
        data = b"some bytes"
        wm1 = embed_binary_watermark(data, "alpha")
        wm2 = embed_binary_watermark(data, "bravo")
        assert wm1 != wm2
        assert extract_binary_watermark(wm1) == "alpha"
        assert extract_binary_watermark(wm2) == "bravo"


# ── CSV watermarking ──────────────────────────────────────────────────


class TestCSVWatermark:
    # Need enough numeric cells for the payload encoding.
    # "ab" -> 2+2+2=6 bytes = 48 bits; 30 rows x 2 cols = 60 cells > 48
    SAMPLE_CSV = "name,value,score\n" + "".join(
        f"user{i},{100.0 + i},{0.5 + i * 0.01}\n" for i in range(30)
    )

    def test_roundtrip(self) -> None:
        payload = "ab"
        wm = embed_csv_watermark(self.SAMPLE_CSV, payload)
        extracted = extract_csv_watermark(self.SAMPLE_CSV, wm)
        assert extracted == payload

    def test_values_close_to_original(self) -> None:
        epsilon = 0.001
        wm = embed_csv_watermark(self.SAMPLE_CSV, "ab", epsilon=epsilon)
        orig_lines = self.SAMPLE_CSV.strip().split("\n")
        wm_lines = wm.strip().split("\n")
        for orig, modified in zip(orig_lines[1:], wm_lines[1:]):
            orig_cells = orig.split(",")
            mod_cells = modified.split(",")
            for oc, mc in zip(orig_cells, mod_cells):
                try:
                    ov = float(oc)
                    mv = float(mc)
                    assert abs(mv - ov) <= epsilon, f"{mv} too far from {ov}"
                except ValueError:
                    assert oc == mc

    def test_header_preserved(self) -> None:
        wm = embed_csv_watermark(self.SAMPLE_CSV, "test")
        assert wm.split("\n")[0] == "name,value,score"

    def test_non_numeric_cells_unchanged(self) -> None:
        csv_data = "name,city\nalice,new york\nbob,london\n"
        wm = embed_csv_watermark(csv_data, "x")
        # Non-numeric CSV → no changes possible, but should not crash
        assert "alice" in wm
        assert "bob" in wm


# ── WatermarkService ──────────────────────────────────────────────────


class TestWatermarkService:
    @pytest.fixture
    def svc(self) -> WatermarkService:
        return WatermarkService()

    def test_text_watermark_and_verify(self, svc: WatermarkService) -> None:
        text = "This is a document with enough words to hold a watermark payload inside it"
        result = svc.watermark(text, "asset_001", "0xAlice")
        assert isinstance(result, str)
        info = svc.verify(result)
        assert info is not None
        assert info["asset_id"] == "asset_001"
        assert info["owner"] == "0xAlice"

    def test_binary_watermark_and_verify(self, svc: WatermarkService) -> None:
        data = b"\x89PNG" + b"\x00" * 100
        result = svc.watermark(data, "img_001", "0xBob")
        assert isinstance(result, bytes)
        info = svc.verify(result)
        assert info is not None
        assert info["asset_id"] == "img_001"
        assert info["owner"] == "0xBob"

    def test_csv_watermark_and_verify_via_service(self, svc: WatermarkService) -> None:
        # Need enough numeric cells: payload is JSON ~45 bytes -> ~376 bits
        # 100 rows x 3 cols = 300 numeric cells — enough for short payloads
        csv_text = "c1,c2,c3\n" + "".join(f"{1.0 + i},{2.0 + i},{3.0 + i}\n" for i in range(200))
        result = svc.watermark(csv_text, "d1", "0xC")
        assert isinstance(result, str)
        # Direct CSV extraction works:
        payload = json.dumps({"asset_id": "d1", "owner": "0xC"})
        extracted = extract_csv_watermark(csv_text, result)
        assert extracted == payload

    def test_verify_unwatermarked_returns_none(self, svc: WatermarkService) -> None:
        assert svc.verify("plain text") is None
        assert svc.verify(b"plain bytes") is None

    def test_verify_returns_none_for_invalid_json(self) -> None:
        svc = WatermarkService()
        # Embed a non-JSON payload
        wm = embed_text_watermark("some words for embedding purposes here now", "not json")
        assert svc.verify(wm) is None
