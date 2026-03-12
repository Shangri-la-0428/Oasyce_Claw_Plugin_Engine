import os
import sys

# Mini test runner since pytest isn't available
from oasyce_plugin.engines.core_engines import DataEngine, MetadataEngine, CertificateEngine, UploadEngine
from oasyce_plugin.models import AssetMetadata, EngineResult

def run_tests():
    print("Running tests...")
    test_file = "test_dummy.txt"
    with open(test_file, "w") as f:
        f.write("hello Oasyce world")

    # Test 1
    res = DataEngine.scan_data(test_file)
    assert res.success is True
    assert res.data["hash"] is not None
    print("✅ test_scan_data passed")

    # Test 2
    res_meta = MetadataEngine.generate_metadata(res.data, ["Test"], "Alice")
    assert res_meta.success is True
    assert res_meta.data.owner == "Alice"
    print("✅ test_generate_metadata passed")

    # Test 3
    res_cert = CertificateEngine.create_popc_certificate(res_meta.data)
    assert res_cert.success is True
    assert len(res_cert.data.popc_signature) == 64
    print("✅ test_create_certificate passed")

    os.remove(test_file)
    print("All tests passed!")

if __name__ == "__main__":
    run_tests()
