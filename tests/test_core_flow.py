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
from oasyce_plugin.crypto import generate_keypair


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

    priv_hex, pub_hex = generate_keypair()
    cert_res = CertificateEngine.create_popc_certificate(metadata, priv_hex, "test-key-id")
    assert cert_res.ok
    signed = cert_res.data
    assert "popc_signature" in signed

    post_val = validate_metadata(signed, require_signature=True)
    assert post_val.ok

    verify_res = CertificateEngine.verify_popc_certificate(signed, pub_hex)
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


def test_discover_and_buy_skill():
    """Test the one-shot discover → quote → buy → watermark flow."""
    import os, tempfile
    from oasyce_plugin.config import Config
    from oasyce_plugin.skills.agent_skills import OasyceSkills

    config = Config.from_env()
    skills = OasyceSkills(config)

    # Register a test asset first
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This is valuable financial data for AI training.\n" * 10)
        test_path = f.name

    try:
        file_info = skills.scan_data_skill(test_path, skip_privacy_check=True)
        metadata = skills.generate_metadata_skill(file_info, ["financial", "test"], "Alice")
        signed = skills.create_certificate_skill(metadata)
        skills.register_data_asset_skill(signed)

        # Now discover and buy
        result = skills.discover_and_buy_skill(
            query="financial",
            buyer="agent_007",
            max_price=100.0,
            amount=10.0,
            with_watermark=True,
        )

        assert "error" not in result, f"Unexpected error: {result}"
        assert result["tokens_received"] > 0
        assert result["receipt_id"]
        assert result["price_paid"] == 10.0
        assert result["effective_price"] > 0
        assert result["fee_burned"] > 0

    finally:
        os.unlink(test_path)


def test_discover_and_buy_too_expensive():
    """Test that discover_and_buy respects max_price."""
    import os, tempfile
    from oasyce_plugin.config import Config
    from oasyce_plugin.skills.agent_skills import OasyceSkills

    config = Config.from_env()
    skills = OasyceSkills(config)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Expensive data\n")
        test_path = f.name

    try:
        file_info = skills.scan_data_skill(test_path, skip_privacy_check=True)
        metadata = skills.generate_metadata_skill(file_info, ["expensive"], "Bob")
        signed = skills.create_certificate_skill(metadata)
        skills.register_data_asset_skill(signed)

        result = skills.discover_and_buy_skill(
            query="expensive",
            buyer="agent_008",
            max_price=0.001,  # impossibly low
            amount=10.0,
        )
        assert "error" in result
        assert "expensive" in result["error"].lower() or "Too" in result["error"]
    finally:
        os.unlink(test_path)


def test_discover_and_buy_no_results():
    """Test discover_and_buy with no matching data."""
    from oasyce_plugin.config import Config
    from oasyce_plugin.skills.agent_skills import OasyceSkills

    config = Config.from_env()
    skills = OasyceSkills(config)

    result = skills.discover_and_buy_skill(
        query="nonexistent_data_category_xyz_999",
        buyer="agent_009",
    )
    assert "error" in result
    assert "No data found" in result["error"]
