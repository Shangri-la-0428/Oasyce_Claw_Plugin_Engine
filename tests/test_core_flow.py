from __future__ import annotations

import json
import os
from pathlib import Path

from oasyce_plugin.engines.core_engines import (
    CertificateEngine,
    DataEngine,
    MetadataEngine,
    SearchEngine,
    UploadEngine,
)
from oasyce_plugin.engines.schema import validate_metadata


def test_end_to_end_registration(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello oasyce", encoding="utf-8")

    scan_res = DataEngine.scan_data(str(file_path))
    assert scan_res.ok
    file_info = scan_res.data
    assert file_info["file_hash"]

    meta_res = MetadataEngine.generate_metadata(file_info, ["Core"], "Tester")
    assert meta_res.ok
    metadata = meta_res.data
    assert metadata["asset_id"].startswith("OAS_")

    pre_val = validate_metadata(metadata, require_signature=False)
    assert pre_val.ok

    cert_res = CertificateEngine.create_popc_certificate(metadata, "test-key", "test-key-id")
    assert cert_res.ok
    signed = cert_res.data
    assert "popc_signature" in signed

    post_val = validate_metadata(signed, require_signature=True)
    assert post_val.ok

    verify_res = CertificateEngine.verify_popc_certificate(signed, "test-key")
    assert verify_res.ok
    assert verify_res.data is True

    vault_dir = tmp_path / "vault"
    reg_res = UploadEngine.register_asset(signed, str(vault_dir))
    assert reg_res.ok

    saved_path = Path(reg_res.data["vault_path"])
    assert saved_path.exists()
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    assert loaded["asset_id"] == signed["asset_id"]

    search_res = SearchEngine.search_assets(str(vault_dir), "Core")
    assert search_res.ok
    assert len(search_res.data) == 1
