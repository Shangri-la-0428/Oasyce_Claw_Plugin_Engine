"""
Tests for PrivacyFilter and IPFS Storage
"""

import pytest
import os
import tempfile
from pathlib import Path

from oasyce.engines.core_engines import PrivacyFilter, DataEngine
from oasyce.storage.ipfs_client import LocalStorage, IPFSClient


class TestPrivacyFilter:
    """隐私过滤器测试"""

    def test_sensitive_filename_patterns(self):
        """测试敏感文件名模式匹配"""
        # 身份证
        result = PrivacyFilter.is_sensitive_file("/path/to/身份证.jpg")
        assert result.ok
        assert result.data["is_sensitive"] is True
        assert result.data["sensitivity_type"] == "FILENAME_PATTERN"

        # 银行卡
        result = PrivacyFilter.is_sensitive_file("/path/to/银行卡_scan.png")
        assert result.ok
        assert result.data["is_sensitive"] is True

        # passport
        result = PrivacyFilter.is_sensitive_file("/Users/me/passport_copy.pdf")
        assert result.ok
        assert result.data["is_sensitive"] is True

    def test_sensitive_path_prefixes(self):
        """测试敏感路径前缀"""
        result = PrivacyFilter.is_sensitive_file("/etc/passwd")
        assert result.ok
        assert result.data["is_sensitive"] is True
        assert result.data["sensitivity_type"] == "PATH_PREFIX"

        result = PrivacyFilter.is_sensitive_file("~/.ssh/id_rsa")
        assert result.ok
        assert result.data["is_sensitive"] is True

    def test_non_sensitive_file(self):
        """测试非敏感文件"""
        result = PrivacyFilter.is_sensitive_file("/photos/vacation.jpg")
        assert result.ok
        assert result.data["is_sensitive"] is False

    def test_batch_filter(self):
        """测试批量过滤"""
        files = [
            "/photos/vacation.jpg",
            "/docs/身份证.png",
            "/notes/meeting.md",
            "/private/key.pem",
        ]

        result = PrivacyFilter.filter_batch(files)
        assert result.ok
        assert len(result.data["allowed"]) == 2
        assert len(result.data["blocked"]) == 2
        assert "/docs/身份证.png" in result.data["blocked"]
        assert "/private/key.pem" in result.data["blocked"]

    def test_custom_patterns(self):
        """测试自定义敏感模式"""
        custom_patterns = [r".*secret.*", r".*confidential.*"]

        result = PrivacyFilter.is_sensitive_file(
            "/docs/secret_plan.pdf", custom_patterns=custom_patterns
        )
        assert result.ok
        assert result.data["is_sensitive"] is True


class TestPrivacyFilterWithDataEngine:
    """隐私过滤器与 DataEngine 集成测试"""

    def test_scan_with_privacy_check_blocked(self):
        """测试扫描敏感文件被阻止"""
        # 创建一个临时敏感文件
        with tempfile.NamedTemporaryFile(suffix="身份证.jpg", delete=False) as f:
            f.write(b"test content")
            temp_path = f.name

        try:
            result = DataEngine.scan_data_with_privacy_check(temp_path)
            assert not result.ok
            assert result.code == "PRIVACY_BLOCKED"
            assert "privacy filter" in result.error.lower()
        finally:
            os.unlink(temp_path)

    def test_scan_with_privacy_check_allowed(self):
        """测试扫描非敏感文件通过"""
        with tempfile.NamedTemporaryFile(suffix="normal_photo.jpg", delete=False) as f:
            f.write(b"test content")
            temp_path = f.name

        try:
            result = DataEngine.scan_data_with_privacy_check(temp_path)
            assert result.ok
            assert "file_hash" in result.data
        finally:
            os.unlink(temp_path)


class TestLocalStorage:
    """本地存储后端测试"""

    def test_upload_and_download(self):
        """测试上传和下载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = LocalStorage(tmpdir)

            # 创建测试文件
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write("test content")
                src_path = f.name

            try:
                # 上传
                result = storage.upload(src_path)
                assert result["success"] is True
                assert "cid" in result
                assert result["backend"] == "local"

                cid = result["cid"]

                # 下载
                dest_path = os.path.join(tmpdir, "downloaded.txt")
                download_result = storage.download(cid, dest_path)
                assert download_result["success"] is True

                # 验证内容
                with open(dest_path, "r") as f:
                    content = f.read()
                assert content == "test content"
            finally:
                os.unlink(src_path)

    def test_pin_noop(self):
        """测试 LocalStorage 的 pin 操作（空操作）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = LocalStorage(tmpdir)
            result = storage.pin("some_cid")
            assert result["success"] is True


class TestIPFSClient:
    """IPFS 客户端测试"""

    def test_init_local_backend(self):
        """测试初始化本地后端"""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = IPFSClient(storage_type="local", storage_dir=tmpdir)
            assert client.storage_type == "local"
            assert isinstance(client.backend, LocalStorage)

    def test_register_asset_with_storage(self):
        """测试注册资产并存储"""
        with tempfile.TemporaryDirectory() as tmpdir:
            client = IPFSClient(storage_type="local", storage_dir=tmpdir)

            # 创建测试文件
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write("test asset content")
                src_path = f.name

            vault_path = os.path.join(tmpdir, "vault")
            metadata = {
                "asset_id": "OAS_TEST123",
                "filename": "test.txt",
                "owner": "Alice",
                "tags": ["test", "demo"],
            }

            try:
                result = client.register_asset_with_storage(
                    file_path=src_path,
                    metadata=metadata,
                    vault_path=vault_path,
                )

                assert result["success"] is True
                assert result["asset_id"] == "OAS_TEST123"
                assert "cid" in result
                assert result["storage_backend"] == "local"

                # 验证 vault 文件存在
                vault_file = os.path.join(vault_path, "OAS_TEST123.json")
                assert os.path.exists(vault_file)
            finally:
                os.unlink(src_path)


class TestIntegration:
    """集成测试：完整流程"""

    def test_full_registration_with_privacy_check(self):
        """测试完整的注册流程（包含隐私检查）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试文件
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                f.write("# Test Document\n\nThis is a test.")
                src_path = f.name

            try:
                # 1. 扫描 + 隐私检查
                scan_result = DataEngine.scan_data_with_privacy_check(src_path)
                assert scan_result.ok

                # 2. 分类
                classify_result = DataEngine.classify_data(scan_result.data)
                assert classify_result.ok

                # 3. 生成元数据
                meta_result = MetadataEngine.generate_metadata(
                    scan_result.data,
                    tags=["test", "integration"],
                    owner="Alice",
                    classification=classify_result.data,
                )
                assert meta_result.ok

                # 4. 创建证书
                priv_hex, pub_hex = generate_keypair()
                cert_result = CertificateEngine.create_popc_certificate(
                    meta_result.data, signing_key=priv_hex, key_id="test_key_001"
                )
                assert cert_result.ok

                # 5. 注册资产（带存储）
                from oasyce.storage.ipfs_client import IPFSClient

                client = IPFSClient(storage_type="local", storage_dir=tmpdir)
                vault_path = os.path.join(tmpdir, "vault")

                reg_result = client.register_asset_with_storage(
                    file_path=src_path,
                    metadata=cert_result.data,
                    vault_path=vault_path,
                )
                assert reg_result["success"] is True

            finally:
                os.unlink(src_path)


# Import for integration test
from oasyce.engines.core_engines import MetadataEngine, CertificateEngine
from oasyce.crypto import generate_keypair
