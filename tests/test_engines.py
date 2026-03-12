import os
import pytest
from oasyce_plugin.engines.core_engines import DataEngine, MetadataEngine, CertificateEngine, UploadEngine

@pytest.fixture
def dummy_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("Hello Oasyce")
    return str(f)

def test_scan_and_classify(dummy_file):
    res = DataEngine.scan_data(dummy_file)
    assert res.ok is True
    assert res.data["size"] == 12
    assert "file_hash" in res.data
    
    class_res = DataEngine.classify_data(res.data)
    assert class_res.ok is True
    assert class_res.data["category"] == "DOCUMENT"

def test_generate_metadata(dummy_file):
    res_scan = DataEngine.scan_data(dummy_file)
    res_meta = MetadataEngine.generate_metadata(res_scan.data, ["Test"], "Alice")
    assert res_meta.ok is True
    assert res_meta.data["owner"] == "Alice"
    assert res_meta.data["asset_id"].startswith("OAS_")

def test_create_certificate_and_upload(dummy_file, tmp_path):
    res_scan = DataEngine.scan_data(dummy_file)
    res_meta = MetadataEngine.generate_metadata(res_scan.data, ["Test"], "Alice")
    
    res_cert = CertificateEngine.create_popc_certificate(
        res_meta.data,
        signing_key="test_key",
        key_id="test_key_id"
    )
    assert res_cert.ok is True
    assert "popc_signature" in res_cert.data
    assert res_cert.data["certificate_issuer"] == "Oasyce_Hardware_Node_001"
    
    vault_path = str(tmp_path / "vault")
    res_upload = UploadEngine.register_asset(res_cert.data, vault_path)
    assert res_upload.ok is True
    assert os.path.exists(res_upload.data["vault_path"])
