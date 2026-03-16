"""Tests for scanner and inbox."""
import pytest

from oasyce_plugin.services.scanner import AssetScanner, ScanResult
from oasyce_plugin.services.inbox import (
    ConfirmationInbox,
    InboxError,
    TRUST_MANUAL,
    TRUST_SEMI_AUTO,
    TRUST_FULL_AUTO,
)


# ── Scanner Tests ─────────────────────────────────────────────────────

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
        assert results[0].suggested_name is not None

    def test_scan_skips_sensitive(self, tmp_path):
        f = tmp_path / "password_list.csv"
        f.write_text("user,pass\na,b\n")
        scanner = AssetScanner()
        # Sensitive files should not appear in results
        sensitivity = scanner.classify_sensitivity(str(f))
        assert sensitivity == "sensitive"

    def test_classify_public(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/data/photos/cat.jpg") == "public"

    def test_classify_sensitive(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/home/user/.env") == "sensitive"
        assert scanner.classify_sensitivity("/keys/private_key.pem") == "sensitive"

    def test_classify_internal(self):
        scanner = AssetScanner()
        assert scanner.classify_sensitivity("/work/draft_plan.md") == "internal"

    def test_scan_single_file(self, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text("# My notes\nSome content here\n")
        scanner = AssetScanner()
        result = scanner.scan_file(str(f))
        assert result is not None

    def test_scan_file_nonexistent(self):
        scanner = AssetScanner()
        result = scanner.scan_file("/nonexistent/file.csv")
        assert result is None

    def test_generate_description(self, tmp_path):
        f = tmp_path / "medical_scan.csv"
        f.write_text("patient,result\na,b\n")
        scanner = AssetScanner()
        desc = scanner.generate_description(str(f))
        assert isinstance(desc, dict)
        assert "description" in desc

    def test_internal_low_confidence(self, tmp_path):
        f = tmp_path / "draft_notes.md"
        f.write_text("work in progress\n" * 10)
        scanner = AssetScanner()
        result = scanner.scan_file(str(f))
        if result is not None:
            assert result.confidence < 0.5


# ── Inbox Tests ───────────────────────────────────────────────────────

class TestConfirmationInbox:

    def _make_inbox(self, tmp_path) -> ConfirmationInbox:
        return ConfirmationInbox(data_dir=str(tmp_path))

    def test_add_pending_register(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/photo.jpg", "Photo")
        assert item.status == "pending"
        assert item.item_type == "register"

    def test_add_pending_purchase(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_purchase("asset_001", 5.0, "useful data")
        assert item.status == "pending"
        assert item.price == 5.0

    def test_approve(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "File")
        result = inbox.approve(item.item_id)
        assert result.status == "approved"
        assert result.resolved_at is not None

    def test_reject(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "File")
        result = inbox.reject(item.item_id)
        assert result.status == "rejected"

    def test_edit_and_approve(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "File", ["csv"])
        result = inbox.edit(item.item_id, {"suggested_name": "Better Name"})
        assert result.status == "approved"
        assert result.suggested_name == "Better Name"

    def test_double_approve_raises(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        item = inbox.add_pending_register("/data/file.csv", "File")
        inbox.approve(item.item_id)
        with pytest.raises(InboxError):
            inbox.approve(item.item_id)

    def test_list_pending(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.add_pending_register("/a.csv", "A")
        inbox.add_pending_purchase("asset_1", 10.0)
        item3 = inbox.add_pending_register("/b.csv", "B")
        inbox.approve(item3.item_id)
        pending = inbox.list_pending()
        assert len(pending) == 2

    def test_list_pending_by_type(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.add_pending_register("/a.csv", "A")
        inbox.add_pending_purchase("asset_1", 10.0)
        assert len(inbox.list_pending("register")) == 1
        assert len(inbox.list_pending("purchase")) == 1

    def test_trust_level_default(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        assert inbox.get_trust_level() == TRUST_MANUAL

    def test_trust_level_set(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        assert inbox.get_trust_level() == TRUST_SEMI_AUTO

    def test_trust_level_invalid(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        with pytest.raises(InboxError):
            inbox.set_trust_level(99)

    def test_full_auto_register(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_FULL_AUTO)
        item = inbox.add_pending_register("/a.csv", "A")
        assert item.status == "approved"

    def test_semi_auto_low_price_purchase(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        item = inbox.add_pending_purchase("asset_1", 5.0)
        assert item.status == "approved"

    def test_semi_auto_high_price_purchase(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        inbox.set_trust_level(TRUST_SEMI_AUTO)
        item = inbox.add_pending_purchase("asset_1", 50.0)
        assert item.status == "pending"

    def test_persistence(self, tmp_path):
        inbox1 = ConfirmationInbox(data_dir=str(tmp_path))
        inbox1.set_trust_level(TRUST_SEMI_AUTO)
        inbox1.add_pending_register("/a.csv", "A")

        inbox2 = ConfirmationInbox(data_dir=str(tmp_path))
        assert inbox2.get_trust_level() == TRUST_SEMI_AUTO
        assert inbox2.count_pending() == 1

    def test_not_found(self, tmp_path):
        inbox = self._make_inbox(tmp_path)
        with pytest.raises(InboxError):
            inbox.approve("nonexistent")
