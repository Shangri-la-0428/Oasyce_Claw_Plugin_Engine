"""Tests for risk auto-classification (Item 4)."""

import pytest
from oasyce.engines.risk import auto_classify_risk, RISK_TO_ACCESS
from oasyce.engines.core_engines import DataEngine, MetadataEngine


class TestAutoClassifyRisk:
    def test_default_public(self):
        assert auto_classify_risk("report.pdf", "original", 1024) == "public"

    def test_sensitive_via_privacy_filter(self):
        # PrivacyFilter matches paths containing .ssh/
        assert auto_classify_risk("/home/user/.ssh/id_rsa", "original", 256) == "sensitive"

    def test_sensitive_via_extension_key(self):
        assert auto_classify_risk("server.key", "original", 512) == "sensitive"

    def test_sensitive_via_extension_pem(self):
        assert auto_classify_risk("cert.pem", "original", 1024) == "sensitive"

    def test_sensitive_via_extension_env(self):
        assert auto_classify_risk("app.env", "original", 64) == "sensitive"

    def test_internal_collection(self):
        assert auto_classify_risk("data.csv", "collection", 2048) == "internal"

    def test_internal_log_extension(self):
        assert auto_classify_risk("server.log", "original", 4096) == "internal"

    def test_internal_bak_extension(self):
        assert auto_classify_risk("db.bak", "original", 8192) == "internal"

    def test_internal_tmp_extension(self):
        assert auto_classify_risk("temp.tmp", "original", 100) == "internal"

    def test_empty_path_default_public(self):
        assert auto_classify_risk("", "original", 0) == "public"


class TestRiskToAccess:
    def test_mapping(self):
        assert RISK_TO_ACCESS["public"] == "L3"
        assert RISK_TO_ACCESS["internal"] == "L3"
        assert RISK_TO_ACCESS["sensitive"] == "L2"


class TestGenerateMetadataRiskInjection:
    def test_metadata_has_risk_fields(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("Hello Oasyce")
        scan = DataEngine.scan_data(str(f))
        assert scan.ok
        # Override path to avoid macOS /private/ prefix triggering PrivacyFilter
        scan.data["path"] = "hello.txt"
        meta = MetadataEngine.generate_metadata(scan.data, ["test"], "Alice")
        assert meta.ok
        assert "risk_level" in meta.data
        assert "max_access_level" in meta.data
        assert meta.data["risk_level"] == "public"
        assert meta.data["max_access_level"] == "L3"

    def test_sensitive_file_auto_classified(self, tmp_path):
        f = tmp_path / "secret.key"
        f.write_text("private key content")
        scan = DataEngine.scan_data(str(f))
        assert scan.ok
        meta = MetadataEngine.generate_metadata(scan.data, ["test"], "Alice")
        assert meta.ok
        assert meta.data["risk_level"] == "sensitive"
        assert meta.data["max_access_level"] == "L2"

    def test_collection_rights_internal(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c")
        scan = DataEngine.scan_data(str(f))
        assert scan.ok
        # Override path to avoid macOS /private/ prefix triggering PrivacyFilter
        scan.data["path"] = "data.csv"
        meta = MetadataEngine.generate_metadata(
            scan.data,
            ["test"],
            "Alice",
            rights_type="collection",
        )
        assert meta.ok
        assert meta.data["risk_level"] == "internal"
