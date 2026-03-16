"""Tests for Scanner and Inbox."""
import os
import tempfile
import pytest

from oasyce_plugin.services.scanner import AssetScanner, ScanResult
from oasyce_plugin.services.inbox import (
    ConfirmationInbox,
    TRUST_MANUAL,
    TRUST_SEMI_AUTO,
    TRUST_FULL_AUTO,
)


# ── Scanner ───────────────────────────────────────────────────────────

class TestAssetScanner:

    def test_scan_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            scanner = AssetScanner()
            results = scanner.scan_directory(d)
            assert results == []

    def test_scan_finds_csv(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "data.csv")
            with open(f, "w") as fp:
                fp.write("a,b,c\n1,2,3\n")
            scanner = AssetScanner()
            results = scanner.scan_directory(d)
            assert len(results) == 1
            assert results[0].file_type == "csv"

    def test_scan_skips_unsupported(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "binary.exe")
            with open(f, "w") as fp:
                fp.write("binary")
            scanner = AssetScanner()
            results = scanner.scan_directory(d)
            assert results == []

    def test_classify_sensitive(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/home/user/.env") == "sensitive"
        assert scanner.classify_sensitivity("/keys/private_key.pem") == "sensitive"
        assert scanner.classify_sensitivity("/data/api_key.txt") == "sensitive"

    def test_classify_internal(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/project/draft_v2.md") == "internal"
        assert scanner.classify_sensitivity("/temp/notes.txt") == "internal"

    def test_classify_public(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/data/photos/beach.jpg") == "public"
        assert scanner.classify_sensitivity("/reports/sales_q1.csv") == "public"

    def test_scan_skips_sensitive_files(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "api_key.json")
            with open(f, "w") as fp:
                fp.write('{"key": "secret"}')
            scanner = AssetScanner()
            results = scanner.scan_directory(d)
            assert results == []

    def test_generate_description(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "sales_report.csv")
            with open(f, "w") as fp:
                fp.write("a,b\n1,2\n")
            scanner = AssetScanner()
            desc = scanner.generate_description(f)
            assert "Sales Report" in desc["name"]
            assert "csv" in desc["tags"]
            assert "data" in desc["tags"]

    def test_scan_single_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "readme.md")
            with open(f, "w") as fp:
                fp.write("# Hello\n")
            scanner = AssetScanner()
            result = scanner.scan_file(f)
            assert result is not None
            assert result.file_type == "md"

    def test_scan_nonexistent(self):
        scanner = AssetScanner()
        assert scanner.scan_file("/nonexistent/file.csv") is None
        assert scanner.scan_directory("/nonexistent/dir") == []


# ── Inbox ─────────────────────────────────────────────────────────────

class TestConfirmationInbox:

    def _make_inbox(self, tmpdir: str) -> ConfirmationInbox:
        return ConfirmationInbox(data_dir=tmpdir)

    def test_add_pending_register(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            item = inbox.add_pending_register("/data/file.csv", "Test File", ["csv"])
            assert item.status == "pending"
            assert item.item_type == "register"

    def test_add_pending_purchase(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            item = inbox.add_pending_purchase("asset_001", 50.0, "recommended")
            assert item.status == "pending"
            assert item.item_type == "purchase"

    def test_approve(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            item = inbox.add_pending_register("/f.csv", "F")
            approved = inbox.approve(item.item_id)
            assert approved.status == "approved"

    def test_reject(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            item = inbox.add_pending_register("/f.csv", "F")
            rejected = inbox.reject(item.item_id)
            assert rejected.status == "rejected"

    def test_edit_and_approve(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            item = inbox.add_pending_register("/f.csv", "Old Name", ["old"])
            edited = inbox.edit(item.item_id, {"suggested_name": "New Name", "suggested_tags": ["new"]})
            assert edited.status == "approved"
            assert edited.suggested_name == "New Name"
            assert edited.suggested_tags == ["new"]

    def test_double_approve_fails(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            item = inbox.add_pending_register("/f.csv", "F")
            inbox.approve(item.item_id)
            with pytest.raises(ValueError):
                inbox.approve(item.item_id)

    def test_list_pending(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            inbox.add_pending_register("/a.csv", "A")
            inbox.add_pending_register("/b.csv", "B")
            inbox.add_pending_purchase("asset_1", 10.0)
            pending = inbox.list_pending()
            assert len(pending) == 3
            reg_only = inbox.list_pending("register")
            assert len(reg_only) == 2
            buy_only = inbox.list_pending("purchase")
            assert len(buy_only) == 1

    def test_trust_level_default(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            assert inbox.get_trust_level() == TRUST_MANUAL

    def test_trust_level_set(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            inbox.set_trust_level(TRUST_SEMI_AUTO)
            assert inbox.get_trust_level() == TRUST_SEMI_AUTO

    def test_trust_level_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            with pytest.raises(ValueError):
                inbox.set_trust_level(99)

    def test_semi_auto_approves_low_value_purchase(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            inbox.set_trust_level(TRUST_SEMI_AUTO)
            item = inbox.add_pending_purchase("asset_1", 5.0)
            assert item.status == "approved"  # below threshold

    def test_semi_auto_holds_high_value_purchase(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            inbox.set_trust_level(TRUST_SEMI_AUTO)
            item = inbox.add_pending_purchase("asset_1", 500.0)
            assert item.status == "pending"  # above threshold

    def test_full_auto_approves_everything(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            inbox.set_trust_level(TRUST_FULL_AUTO)
            r = inbox.add_pending_register("/f.csv", "F")
            p = inbox.add_pending_purchase("a1", 9999.0)
            assert r.status == "approved"
            assert p.status == "approved"

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            inbox1 = self._make_inbox(d)
            inbox1.add_pending_register("/f.csv", "F", ["csv"])
            inbox1.set_trust_level(TRUST_SEMI_AUTO)
            # Reload
            inbox2 = self._make_inbox(d)
            assert len(inbox2.list_pending()) == 1
            assert inbox2.get_trust_level() == TRUST_SEMI_AUTO

    def test_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            with pytest.raises(KeyError):
                inbox.approve("nonexistent")

    def test_auto_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            inbox = self._make_inbox(d)
            inbox.set_trust_level(TRUST_SEMI_AUTO)
            inbox.set_auto_threshold(100.0)
            item = inbox.add_pending_purchase("a1", 50.0)
            assert item.status == "approved"
            item2 = inbox.add_pending_purchase("a2", 200.0)
            assert item2.status == "pending"
