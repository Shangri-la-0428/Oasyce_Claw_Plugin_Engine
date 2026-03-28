"""Tests for fingerprint distribution watermarking (Phase 9)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from typing import Optional

import pytest

from oasyce.crypto.keys import generate_keypair
from oasyce.fingerprint.engine import FingerprintEngine
from oasyce.fingerprint.registry import FingerprintRegistry
from oasyce.storage.ledger import Ledger


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def signing_key() -> str:
    priv, _ = generate_keypair()
    return priv


@pytest.fixture
def engine(signing_key: str) -> FingerprintEngine:
    return FingerprintEngine(signing_key)


@pytest.fixture
def ledger() -> Ledger:
    led = Ledger(":memory:")
    yield led
    led.close()


@pytest.fixture
def registry(ledger: Ledger) -> FingerprintRegistry:
    return FingerprintRegistry(ledger)


SAMPLE_TEXT = """\
def hello():
    print("Hello, World!")

def add(a, b):
    return a + b

class Greeter:
    def greet(self, name):
        return f"Hi, {name}!"

# End of file
"""

LONG_TEXT = "\n".join(f"line {i}: some content here" for i in range(2000))


# ── Fingerprint generation ───────────────────────────────────────────


class TestFingerprintGeneration:
    def test_deterministic(self, engine: FingerprintEngine) -> None:
        fp1 = engine.generate_fingerprint("asset1", "caller1", 1000)
        fp2 = engine.generate_fingerprint("asset1", "caller1", 1000)
        assert fp1 == fp2

    def test_hex_format(self, engine: FingerprintEngine) -> None:
        fp = engine.generate_fingerprint("asset1", "caller1", 1000)
        assert len(fp) == 64
        int(fp, 16)  # should not raise

    def test_different_callers_different_fp(self, engine: FingerprintEngine) -> None:
        fp1 = engine.generate_fingerprint("asset1", "alice", 1000)
        fp2 = engine.generate_fingerprint("asset1", "bob", 1000)
        assert fp1 != fp2

    def test_different_assets_different_fp(self, engine: FingerprintEngine) -> None:
        fp1 = engine.generate_fingerprint("asset1", "caller1", 1000)
        fp2 = engine.generate_fingerprint("asset2", "caller1", 1000)
        assert fp1 != fp2

    def test_different_timestamps_different_fp(self, engine: FingerprintEngine) -> None:
        fp1 = engine.generate_fingerprint("asset1", "caller1", 1000)
        fp2 = engine.generate_fingerprint("asset1", "caller1", 2000)
        assert fp1 != fp2

    def test_different_keys_different_fp(self) -> None:
        priv1, _ = generate_keypair()
        priv2, _ = generate_keypair()
        e1 = FingerprintEngine(priv1)
        e2 = FingerprintEngine(priv2)
        fp1 = e1.generate_fingerprint("a", "c", 1)
        fp2 = e2.generate_fingerprint("a", "c", 1)
        assert fp1 != fp2


# ── Text steganography ───────────────────────────────────────────────


class TestTextSteganography:
    def test_roundtrip(self, engine: FingerprintEngine) -> None:
        fp = engine.generate_fingerprint("asset1", "caller1", 1000)
        watermarked = FingerprintEngine.embed_text(LONG_TEXT, fp)
        extracted = FingerprintEngine.extract_text(watermarked)
        assert extracted == fp

    def test_content_functionally_identical(self, engine: FingerprintEngine) -> None:
        fp = engine.generate_fingerprint("asset1", "caller1", 1000)
        watermarked = FingerprintEngine.embed_text(SAMPLE_TEXT, fp)
        # Stripping trailing whitespace from each line should recover original
        original_stripped = [l.rstrip() for l in SAMPLE_TEXT.split("\n")]
        watermarked_stripped = [l.rstrip() for l in watermarked.split("\n")]
        assert original_stripped == watermarked_stripped

    def test_different_callers_different_watermarks(self, engine: FingerprintEngine) -> None:
        fp1 = engine.generate_fingerprint("asset1", "alice", 1000)
        fp2 = engine.generate_fingerprint("asset1", "bob", 1000)
        w1 = FingerprintEngine.embed_text(LONG_TEXT, fp1)
        w2 = FingerprintEngine.embed_text(LONG_TEXT, fp2)
        assert w1 != w2

    def test_extract_from_unwatermarked_returns_none(self) -> None:
        # Plain text with no trailing whitespace markers
        plain = "hello\nworld\nfoo\n"
        result = FingerprintEngine.extract_text(plain)
        # May return a garbage fingerprint or None; either way it shouldn't
        # match any real fingerprint.  The key guarantee is no crash.
        # With only 4 lines, extract should return None (not enough bits).
        assert result is None

    def test_empty_content(self) -> None:
        result = FingerprintEngine.extract_text("")
        assert result is None

    def test_survives_minor_edits(self, engine: FingerprintEngine) -> None:
        """Watermark survives if some lines are modified (redundancy)."""
        fp = engine.generate_fingerprint("asset1", "caller1", 1000)
        # Need enough lines for redundancy (>= 2 full copies = 2048 lines)
        big_text = "\n".join(f"line {i}" for i in range(3000))
        watermarked = FingerprintEngine.embed_text(big_text, fp)
        lines = watermarked.split("\n")
        # Corrupt ~5% of lines by stripping their trailing whitespace
        import random

        random.seed(42)
        for _ in range(150):
            idx = random.randint(0, len(lines) - 1)
            lines[idx] = lines[idx].rstrip()
        damaged = "\n".join(lines)
        extracted = FingerprintEngine.extract_text(damaged)
        assert extracted == fp

    def test_single_line_returns_none(self) -> None:
        result = FingerprintEngine.extract_text("single line")
        assert result is None


# ── Binary watermarking ──────────────────────────────────────────────


class TestBinarySteganography:
    def test_roundtrip(self, engine: FingerprintEngine) -> None:
        fp = engine.generate_fingerprint("asset1", "caller1", 1000)
        data = os.urandom(1024)
        watermarked = FingerprintEngine.embed_binary(data, fp)
        extracted = FingerprintEngine.extract_binary(watermarked)
        assert extracted == fp

    def test_original_data_preserved(self, engine: FingerprintEngine) -> None:
        fp = engine.generate_fingerprint("asset1", "caller1", 1000)
        data = os.urandom(1024)
        watermarked = FingerprintEngine.embed_binary(data, fp)
        # Original data is a prefix of watermarked
        assert watermarked[: len(data)] == data

    def test_extract_from_unwatermarked_returns_none(self) -> None:
        data = os.urandom(1024)
        assert FingerprintEngine.extract_binary(data) is None

    def test_extract_from_short_data_returns_none(self) -> None:
        assert FingerprintEngine.extract_binary(b"short") is None

    def test_corrupted_trailer_returns_none(self, engine: FingerprintEngine) -> None:
        fp = engine.generate_fingerprint("asset1", "caller1", 1000)
        data = os.urandom(256)
        watermarked = bytearray(FingerprintEngine.embed_binary(data, fp))
        # Corrupt the last byte (CRC)
        watermarked[-1] ^= 0xFF
        assert FingerprintEngine.extract_binary(bytes(watermarked)) is None

    def test_different_callers_different_binary(self, engine: FingerprintEngine) -> None:
        fp1 = engine.generate_fingerprint("asset1", "alice", 1000)
        fp2 = engine.generate_fingerprint("asset1", "bob", 1000)
        data = os.urandom(256)
        w1 = FingerprintEngine.embed_binary(data, fp1)
        w2 = FingerprintEngine.embed_binary(data, fp2)
        assert w1 != w2

    def test_empty_data(self, engine: FingerprintEngine) -> None:
        fp = engine.generate_fingerprint("asset1", "caller1", 1000)
        watermarked = FingerprintEngine.embed_binary(b"", fp)
        extracted = FingerprintEngine.extract_binary(watermarked)
        assert extracted == fp


# ── Registry ─────────────────────────────────────────────────────────


class TestFingerprintRegistry:
    def test_record_and_trace(self, registry: FingerprintRegistry) -> None:
        rid = registry.record_distribution("asset1", "alice", "aabb" * 16, 1000)
        assert isinstance(rid, int)
        record = registry.trace_fingerprint("aabb" * 16)
        assert record is not None
        assert record["caller_id"] == "alice"
        assert record["asset_id"] == "asset1"
        assert record["timestamp"] == 1000

    def test_trace_missing_returns_none(self, registry: FingerprintRegistry) -> None:
        assert registry.trace_fingerprint("nonexistent") is None

    def test_get_distributions(self, registry: FingerprintRegistry) -> None:
        registry.record_distribution("asset1", "alice", "aa" * 32, 1000)
        registry.record_distribution("asset1", "bob", "bb" * 32, 2000)
        registry.record_distribution("asset2", "carol", "cc" * 32, 3000)

        dists = registry.get_distributions("asset1")
        assert len(dists) == 2
        assert dists[0]["caller_id"] == "alice"
        assert dists[1]["caller_id"] == "bob"

    def test_get_distributions_empty(self, registry: FingerprintRegistry) -> None:
        assert registry.get_distributions("nonexistent") == []

    def test_duplicate_fingerprint_rejected(self, registry: FingerprintRegistry) -> None:
        fp = "dd" * 32
        registry.record_distribution("asset1", "alice", fp, 1000)
        with pytest.raises(Exception):
            registry.record_distribution("asset1", "bob", fp, 2000)

    def test_record_returns_incrementing_ids(self, registry: FingerprintRegistry) -> None:
        id1 = registry.record_distribution("a", "c1", "11" * 32, 1)
        id2 = registry.record_distribution("a", "c2", "22" * 32, 2)
        assert id2 > id1


# ── CLI integration ──────────────────────────────────────────────────


class TestFingerprintCLI:
    def _run_cli(self, *args: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory(prefix="oas-fingerprint-cli-") as temp_home:
            env = dict(os.environ)
            env["OASYCE_DATA_DIR"] = os.path.join(temp_home, ".oasyce-data")
            return subprocess.run(
                [sys.executable, "-m", "oasyce.cli", "--json", *args],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(os.path.dirname(__file__)),
                env=env,
            )

    def test_embed_and_extract_text(self, tmp_path) -> None:
        src = tmp_path / "test.txt"
        src.write_text(LONG_TEXT)
        out = tmp_path / "watermarked.txt"

        result = self._run_cli(
            "fingerprint",
            "embed",
            str(src),
            "--caller",
            "testuser",
            "--output",
            str(out),
        )
        assert result.returncode == 0, result.stderr

        result2 = self._run_cli("fingerprint", "extract", str(out))
        assert result2.returncode == 0, result2.stderr
        import json

        data = json.loads(result2.stdout)
        assert data["fingerprint"] is not None
        assert len(data["fingerprint"]) == 64

    def test_embed_binary(self, tmp_path) -> None:
        src = tmp_path / "test.bin"
        src.write_bytes(os.urandom(512))
        out = tmp_path / "watermarked.bin"

        result = self._run_cli(
            "fingerprint",
            "embed",
            str(src),
            "--caller",
            "binuser",
            "--output",
            str(out),
        )
        assert result.returncode == 0, result.stderr

        result2 = self._run_cli("fingerprint", "extract", str(out))
        assert result2.returncode == 0, result2.stderr

    def test_extract_no_watermark(self, tmp_path) -> None:
        src = tmp_path / "plain.txt"
        src.write_text("just plain text\n")
        result = self._run_cli("fingerprint", "extract", str(src))
        assert result.returncode != 0

    def test_fingerprint_help(self) -> None:
        result = self._run_cli("fingerprint")
        # Should print help and exit 0
        assert result.returncode == 0


# ── Fingerprint table in Ledger ──────────────────────────────────────


class TestLedgerFingerprintTable:
    def test_table_exists(self) -> None:
        ledger = Ledger(":memory:")
        cursor = ledger._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fingerprint_records'"
        )
        assert cursor.fetchone() is not None
        ledger.close()
