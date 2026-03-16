"""Tests for scanner and inbox services."""
import os
import json
import tempfile
import pytest

from oasyce_plugin.services.scanner import AssetScanner, ScanResult
from oasyce_plugin.services.inbox import (
    ConfirmationInbox,
    InboxError,
    TRUST_MANUAL,
    TRUST_SEMI_AUTO,
    TRUST_FULL_AUTO,
)


# ── Scanner ───────────────────────────────────────────────────────────

class TestAssetScanner:

    def test_scan_empty_dir(self, tmp_path):
        scanner = AssetScanner()
        results = scanner.scan_directory(str(tmp_path))
        assert results == []

    def test_scan_finds_csv(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3\n")
        scanner = AssetScanner()
        results = scanner.scan_directory(str(tmp_path))
        assert len(results) == 1
        assert results[0].file_type == "csv"

    def test_scan_skips_unsupported_ext(self, tmp_path):
        f = tmp_path / "file.xyz"
        f.write_text("hello")
        scanner = AssetScanner()
        results = scanner.scan_directory(str(tmp_path))
        assert len(results) == 0

    def test_scan_skips_sensitive(self, tmp_path):
        f = tmp_path / "api_key.txt"
        f.write_text("sk-12345")
        scanner = AssetScanner()
        results = scanner.scan_directory(str(tmp_path))
        assert len(results) == 0

    def test_classify_public(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/data/photos/cat.jpg") == "public"

    def test_classify_sensitive(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/home/.env") == "sensitive"

    def test_classify_internal(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/project/draft_plan.md") == "internal"

    def test_generate_description(self, tmp_path):
        f = tmp_path / "medical_scan.csv"
        f.write_text("a,b\n1,2\n")
        scanner = AssetScanner()
        desc = scanner.generate_description(str(f))
        assert "name" in desc
        assert "tags" in desc
        assert "csv" in desc["tags"]

    def test_scan_file_single(self, tmp_path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 fake content here padding" * 10)
        scanner = AssetScanner()
        result = scanner.scan_file(str(f))
        assert result is not None
        assert result.file_type == "pdf"

    def test_scan_file_nonexistent(self):
        scanner = AssetScanner()
        result = scanner.scan_file("/nonexistent/file.csv")
        assert result is None

    def test_scan_recursive(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.json").write_text('{"key": "value"}')
        scanner = AssetScanner()
        results = scanner.scan_directory(str(tmp_path), recursive=True)
        assert len(results) == 1

    def test_scan_non_recursive(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.json").write_text('{"key": "value"}')
        (tmp_path / "top.csv").write_text("a,b\n1,2\n")
        scanner = AssetScanner()
        results = scanner.scan_directory(str(tmp_path), recursive=False)
        assert len(results) == 1
        assert results[0].file_type == "csv"


# ── Inbox ─────────────────────────────────────────────────────────────

class TestConfirmationInbox:

    def _make_inbox(self, tmp_path):
        return ConfirmationInbox(data_dir=str(tmp_path))

    def test_add_pending_register(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "My Data")
        assert item.status == "pending"
        assert item.item_type == "register"

    def test_add_pending_purchase(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_purchase("asset_001", 50.0, "AI needs this")
        assert item.status == "pending"
        assert item.price == 50.0

    def test_approve(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "Test")
        approved = inbox.approve(item.item_id)
        assert approved.status == "approved"

    def test_reject(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "Test")
        rejected = inbox.reject(item.item_id)
        assert rejected.status == "rejected"

    def test_edit_and_approve(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "Old Name", ["old"])
        edited = inbox.edit(item.item_id, {"suggested_name": "New Name", "suggested_tags": ["new"]})
        assert edited.status == "approved"
        assert edited.suggested_name == "New Name"
        assert edited.suggested_tags == ["new"]

    def test_approve_already_approved_raises(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "Test")
        inbox.approve(item.item_id)
        with pytest.raises(InboxError):
            inbox.approve(item.item_id)

    def test_list_pending(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.add_pending_register("/a.csv", "A")
        inbox.add_pending_purchase("asset_1", 10.0)
        inbox.add_pending_register("/b.csv", "B")
        assert len(inbox.list_pending()) == 3
        assert len(inbox.list_pending("register")) == 2
        assert len(inbox.list_pending("purchase")) == 1

    def test_trust_level_default(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        assert inbox.get_trust_level() == TRUST_MANUAL

    def test_set_trust_level(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        assert inbox.get_trust_level() == TRUST_SEMI_AUTO

    def test_invalid_trust_level(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        with pytest.raises(InboxError):
            inbox.set_trust_level(99)

    def test_semi_auto_register_public(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        item = inbox.add_pending_register("/data/file.csv", "Test", sensitivity="public", confidence=0.8)
        assert item.status == "approved"

    def test_semi_auto_register_internal_stays_pending(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        item = inbox.add_pending_register("/data/file.csv", "Test", sensitivity="internal", confidence=0.8)
        assert item.status == "pending"

    def test_semi_auto_purchase_below_threshold(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        item = inbox.add_pending_purchase("asset_1", 5.0)
        assert item.status == "approved"

    def test_semi_auto_purchase_above_threshold(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        item = inbox.add_pending_purchase("asset_1", 50.0)
        assert item.status == "pending"

    def test_full_auto(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_FULL_AUTO)
        item = inbox.add_pending_register("/data/file.csv", "Test")
        assert item.status == "approved"

    def test_persistence(self, tmp_path):
        inbox1 = self._make_inbox(tmp_path)
        inbox1.set_trust_level(TRUST_SEMI_AUTO)
        inbox1.add_pending_register("/data/file.csv", "Test")
        # Reload from disk
        inbox2 = self._make_inbox(tmp_path)
        assert inbox2.get_trust_level() == TRUST_SEMI_AUTO
        assert len(inbox2.list_pending()) == 1

    def test_item_not_found(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        with pytest.raises(InboxError):
            inbox.approve("nonexistent")

    def test_auto_threshold(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        inbox.set_auto_threshold(20.0)
        item_low = inbox.add_pending_purchase("a1", 15.0)
        item_high = inbox.add_pending_purchase("a2", 25.0)
        assert item_low.status == "approved"
        assert item_high.status == "pending"
