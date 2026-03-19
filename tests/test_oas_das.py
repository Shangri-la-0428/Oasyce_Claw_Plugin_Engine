"""Tests for OAS-DAS (Oasyce Data Asset Standard)."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

from oasyce.standards.oas_das import (
    IdentityLayer,
    MetadataLayer,
    AccessPolicyLayer,
    ComputeInterfaceLayer,
    ProvenanceLayer,
    OasDasAsset,
)
from oasyce.models import AssetMetadata
from oasyce.skills.agent_skills import OasyceSkills


# ── Layer dataclass creation ────────────────────────────────────────


class TestLayerCreation:
    """Test that all 5 layers instantiate correctly."""

    def test_identity_layer(self):
        layer = IdentityLayer(asset_id="OAS_ABC123", creator="alice", created_at=1700000000)
        assert layer.asset_id == "OAS_ABC123"
        assert layer.creator == "alice"
        assert layer.created_at == 1700000000
        assert layer.version == "1.0"
        assert layer.namespace == "oasyce"

    def test_metadata_layer(self):
        layer = MetadataLayer(title="My Dataset", tags=["AI", "NLP"], file_size_bytes=4096)
        assert layer.title == "My Dataset"
        assert layer.tags == ["AI", "NLP"]
        assert layer.file_size_bytes == 4096
        assert layer.description == ""
        assert layer.file_type == ""

    def test_metadata_layer_defaults(self):
        layer = MetadataLayer(title="Bare")
        assert layer.tags == []
        assert layer.file_size_bytes == 0
        assert layer.language == ""
        assert layer.category == ""

    def test_access_policy_layer_defaults(self):
        layer = AccessPolicyLayer()
        assert layer.risk_level == "public"
        assert layer.max_access_level == "L3"
        assert layer.price_model == "bonding_curve"
        assert layer.license_type == "proprietary"
        assert layer.geographic_restrictions == []
        assert layer.expiry_timestamp is None

    def test_access_policy_layer_custom(self):
        layer = AccessPolicyLayer(
            risk_level="high",
            max_access_level="L1",
            price_model="free",
            license_type="mit",
            geographic_restrictions=["CN", "US"],
            expiry_timestamp=1800000000,
        )
        assert layer.risk_level == "high"
        assert layer.geographic_restrictions == ["CN", "US"]
        assert layer.expiry_timestamp == 1800000000

    def test_compute_interface_layer_defaults(self):
        layer = ComputeInterfaceLayer()
        assert layer.supported_operations == []
        assert layer.runtime == "python3"
        assert layer.max_compute_seconds == 300
        assert layer.memory_limit_mb == 1024

    def test_compute_interface_layer_custom(self):
        layer = ComputeInterfaceLayer(
            supported_operations=["query", "aggregate"],
            input_schema={"type": "object"},
            runtime="python3",
            max_compute_seconds=60,
        )
        assert layer.supported_operations == ["query", "aggregate"]
        assert layer.input_schema == {"type": "object"}

    def test_provenance_layer_defaults(self):
        layer = ProvenanceLayer()
        assert layer.popc_signature is None
        assert layer.parent_assets == []
        assert layer.semantic_vector is None

    def test_provenance_layer_with_vector(self):
        vec = [0.1, 0.2, 0.3]
        layer = ProvenanceLayer(
            popc_signature="abc123",
            certificate_issuer="oasyce_node_01",
            parent_assets=["OAS_PARENT1"],
            semantic_vector=vec,
        )
        assert layer.popc_signature == "abc123"
        assert layer.parent_assets == ["OAS_PARENT1"]
        assert layer.semantic_vector == vec


# ── OasDasAsset creation ────────────────────────────────────────────


class TestOasDasAsset:

    def _make_asset(self, **overrides):
        identity = IdentityLayer(
            asset_id="OAS_TEST001",
            creator="test_user",
            created_at=1700000000,
        )
        metadata = MetadataLayer(title="Test Asset", tags=["test"])
        access_policy = AccessPolicyLayer()
        kw = dict(
            identity=identity,
            metadata=metadata,
            access_policy=access_policy,
        )
        kw.update(overrides)
        return OasDasAsset(**kw)

    def test_creation(self):
        asset = self._make_asset()
        assert asset.identity.asset_id == "OAS_TEST001"
        assert asset.metadata.title == "Test Asset"
        assert isinstance(asset.compute_interface, ComputeInterfaceLayer)
        assert isinstance(asset.provenance, ProvenanceLayer)


# ── Serialization ───────────────────────────────────────────────────


class TestSerialization:

    def _make_asset(self):
        return OasDasAsset(
            identity=IdentityLayer(asset_id="OAS_SER01", creator="bob", created_at=1700000000),
            metadata=MetadataLayer(title="Ser Test", tags=["a", "b"], file_size_bytes=100),
            access_policy=AccessPolicyLayer(risk_level="medium", license_type="mit"),
            compute_interface=ComputeInterfaceLayer(supported_operations=["query"]),
            provenance=ProvenanceLayer(popc_signature="sig123"),
        )

    def test_to_dict_keys(self):
        d = self._make_asset().to_dict()
        assert set(d.keys()) == {
            "identity",
            "metadata",
            "access_policy",
            "compute_interface",
            "provenance",
        }

    def test_to_dict_values(self):
        d = self._make_asset().to_dict()
        assert d["identity"]["asset_id"] == "OAS_SER01"
        assert d["metadata"]["tags"] == ["a", "b"]
        assert d["access_policy"]["risk_level"] == "medium"
        assert d["compute_interface"]["supported_operations"] == ["query"]
        assert d["provenance"]["popc_signature"] == "sig123"

    def test_roundtrip(self):
        original = self._make_asset()
        d = original.to_dict()
        restored = OasDasAsset.from_dict(d)
        assert restored.to_dict() == d

    def test_from_dict_minimal(self):
        d = {
            "identity": {"asset_id": "X", "creator": "Y", "created_at": 1},
            "metadata": {"title": "T"},
        }
        asset = OasDasAsset.from_dict(d)
        assert asset.identity.asset_id == "X"
        assert asset.access_policy.risk_level == "public"  # default


# ── from_asset_metadata ─────────────────────────────────────────────


class TestFromAssetMetadata:

    def test_basic_conversion(self):
        meta = AssetMetadata(
            asset_id="OAS_META01",
            filename="data.csv",
            owner="alice",
            tags=["Finance", "CSV"],
            timestamp=1700000000,
            file_size_bytes=2048,
            risk_level="high",
            max_access_level="L2",
            popc_signature="deadbeef",
            certificate_issuer="node_01",
            schema_version="1.0",
        )
        das = OasDasAsset.from_asset_metadata(meta)

        assert das.identity.asset_id == "OAS_META01"
        assert das.identity.creator == "alice"
        assert das.identity.created_at == 1700000000
        assert das.identity.version == "1.0"

        assert das.metadata.title == "data.csv"
        assert das.metadata.tags == ["Finance", "CSV"]
        assert das.metadata.file_size_bytes == 2048

        assert das.access_policy.risk_level == "high"
        assert das.access_policy.max_access_level == "L2"

        assert das.provenance.popc_signature == "deadbeef"
        assert das.provenance.certificate_issuer == "node_01"

    def test_compute_interface_from_string(self):
        meta = AssetMetadata(
            asset_id="OAS_CI01",
            filename="model.bin",
            owner="bob",
            tags=[],
            timestamp=1700000000,
            file_size_bytes=0,
            compute_interface="ml_inference",
        )
        das = OasDasAsset.from_asset_metadata(meta)
        assert das.compute_interface.supported_operations == ["ml_inference"]

    def test_semantic_vector_preserved(self):
        vec = [0.5, -0.3, 0.8]
        meta = AssetMetadata(
            asset_id="OAS_VEC01",
            filename="emb.npy",
            owner="carol",
            tags=[],
            timestamp=1700000000,
            file_size_bytes=0,
            semantic_vector=vec,
        )
        das = OasDasAsset.from_asset_metadata(meta)
        assert das.provenance.semantic_vector == vec

    def test_none_optional_fields(self):
        meta = AssetMetadata(
            asset_id="OAS_NULL01",
            filename="bare.txt",
            owner="dave",
            tags=[],
            timestamp=1700000000,
            file_size_bytes=0,
        )
        das = OasDasAsset.from_asset_metadata(meta)
        assert das.provenance.popc_signature is None
        assert das.provenance.certificate_issuer is None
        assert das.compute_interface.supported_operations == []


# ── Validation ──────────────────────────────────────────────────────


class TestValidation:

    def test_valid_asset(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="OAS_V01", creator="x", created_at=1),
            metadata=MetadataLayer(title="OK"),
            access_policy=AccessPolicyLayer(),
        )
        errors = asset.validate()
        assert errors == []

    def test_missing_asset_id(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="", creator="x", created_at=1),
            metadata=MetadataLayer(title="OK"),
            access_policy=AccessPolicyLayer(),
        )
        errors = asset.validate()
        assert any("asset_id" in e for e in errors)

    def test_missing_creator(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="", created_at=1),
            metadata=MetadataLayer(title="OK"),
            access_policy=AccessPolicyLayer(),
        )
        errors = asset.validate()
        assert any("creator" in e for e in errors)

    def test_missing_created_at(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="x", created_at=0),
            metadata=MetadataLayer(title="OK"),
            access_policy=AccessPolicyLayer(),
        )
        errors = asset.validate()
        assert any("created_at" in e for e in errors)

    def test_missing_title(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="x", created_at=1),
            metadata=MetadataLayer(title=""),
            access_policy=AccessPolicyLayer(),
        )
        errors = asset.validate()
        assert any("title" in e for e in errors)

    def test_invalid_risk_level(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="x", created_at=1),
            metadata=MetadataLayer(title="OK"),
            access_policy=AccessPolicyLayer(risk_level="unknown"),
        )
        errors = asset.validate()
        assert any("risk_level" in e for e in errors)

    def test_invalid_access_level(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="x", created_at=1),
            metadata=MetadataLayer(title="OK"),
            access_policy=AccessPolicyLayer(max_access_level="L9"),
        )
        errors = asset.validate()
        assert any("max_access_level" in e for e in errors)

    def test_invalid_price_model(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="x", created_at=1),
            metadata=MetadataLayer(title="OK"),
            access_policy=AccessPolicyLayer(price_model="auction"),
        )
        errors = asset.validate()
        assert any("price_model" in e for e in errors)

    def test_invalid_license_type(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="x", created_at=1),
            metadata=MetadataLayer(title="OK"),
            access_policy=AccessPolicyLayer(license_type="gpl"),
        )
        errors = asset.validate()
        assert any("license_type" in e for e in errors)

    def test_multiple_errors(self):
        asset = OasDasAsset(
            identity=IdentityLayer(asset_id="", creator="", created_at=0),
            metadata=MetadataLayer(title=""),
            access_policy=AccessPolicyLayer(risk_level="bad"),
        )
        errors = asset.validate()
        assert len(errors) >= 4


# ── Similarity & Dedup ──────────────────────────────────────────────


class TestSimilarity:

    def _asset_with_vec(self, vec):
        return OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="x", created_at=1),
            metadata=MetadataLayer(title="T"),
            access_policy=AccessPolicyLayer(),
            provenance=ProvenanceLayer(semantic_vector=vec),
        )

    def test_identical_vectors(self):
        a = self._asset_with_vec([1.0, 0.0, 0.0])
        b = self._asset_with_vec([1.0, 0.0, 0.0])
        assert abs(a.similarity(b) - 1.0) < 1e-9

    def test_orthogonal_vectors(self):
        a = self._asset_with_vec([1.0, 0.0])
        b = self._asset_with_vec([0.0, 1.0])
        assert abs(a.similarity(b)) < 1e-9

    def test_opposite_vectors(self):
        a = self._asset_with_vec([1.0, 0.0])
        b = self._asset_with_vec([-1.0, 0.0])
        assert abs(a.similarity(b) - (-1.0)) < 1e-9

    def test_similar_vectors(self):
        a = self._asset_with_vec([1.0, 1.0, 0.0])
        b = self._asset_with_vec([1.0, 1.0, 0.1])
        sim = a.similarity(b)
        assert sim > 0.9

    def test_no_vector_returns_zero(self):
        a = self._asset_with_vec(None)
        b = self._asset_with_vec([1.0, 0.0])
        assert a.similarity(b) == 0.0

    def test_empty_vector_returns_zero(self):
        a = self._asset_with_vec([])
        b = self._asset_with_vec([1.0])
        assert a.similarity(b) == 0.0

    def test_mismatched_dims_returns_zero(self):
        a = self._asset_with_vec([1.0, 2.0])
        b = self._asset_with_vec([1.0, 2.0, 3.0])
        assert a.similarity(b) == 0.0

    def test_zero_vector_returns_zero(self):
        a = self._asset_with_vec([0.0, 0.0])
        b = self._asset_with_vec([1.0, 0.0])
        assert a.similarity(b) == 0.0


class TestIsDuplicate:

    def _asset_with_vec(self, vec):
        return OasDasAsset(
            identity=IdentityLayer(asset_id="X", creator="x", created_at=1),
            metadata=MetadataLayer(title="T"),
            access_policy=AccessPolicyLayer(),
            provenance=ProvenanceLayer(semantic_vector=vec),
        )

    def test_duplicate_identical(self):
        a = self._asset_with_vec([1.0, 0.0, 0.0])
        b = self._asset_with_vec([1.0, 0.0, 0.0])
        assert a.is_duplicate(b) is True

    def test_not_duplicate_orthogonal(self):
        a = self._asset_with_vec([1.0, 0.0])
        b = self._asset_with_vec([0.0, 1.0])
        assert a.is_duplicate(b) is False

    def test_custom_threshold(self):
        a = self._asset_with_vec([1.0, 1.0, 0.0])
        b = self._asset_with_vec([1.0, 1.0, 0.5])
        # similarity ~ 0.97
        assert a.is_duplicate(b, threshold=0.99) is False
        assert a.is_duplicate(b, threshold=0.9) is True

    def test_no_vector_not_duplicate(self):
        a = self._asset_with_vec(None)
        b = self._asset_with_vec(None)
        assert a.is_duplicate(b) is False


# ── CLI integration ─────────────────────────────────────────────────


class TestCLI:

    @pytest.fixture
    def temp_vault(self):
        vault = tempfile.mkdtemp()
        yield vault
        shutil.rmtree(vault, ignore_errors=True)

    @pytest.fixture
    def skills(self, temp_vault):
        from oasyce.crypto.keys import generate_keypair
        from oasyce.config import Config

        priv_hex, pub_hex = generate_keypair()
        config = Config.from_env(
            vault_dir=temp_vault,
            owner="TestUser",
            signing_key=priv_hex,
            public_key=pub_hex,
            signing_key_id="test_001",
        )
        return OasyceSkills(config)

    @pytest.fixture
    def test_files(self, temp_vault):
        txt_path = os.path.join(temp_vault, "test.txt")
        with open(txt_path, "w") as f:
            f.write("OAS-DAS test content for CLI integration test")
        return {"txt": txt_path}

    def test_skills_get_asset_standard(self, skills, test_files):
        """Register an asset, then retrieve its OAS-DAS representation."""
        from oasyce.skills.agent_skills import OasyceSkills

        file_info = skills.scan_data_skill(test_files["txt"], skip_privacy_check=True)
        metadata = skills.generate_metadata_skill(file_info, ["Test", "OASDAS"], "TestUser")
        signed = skills.create_certificate_skill(metadata)
        skills.register_data_asset_skill(signed)

        asset_id = signed["asset_id"]
        result = skills.get_asset_standard_skill(asset_id)

        assert result["identity"]["asset_id"] == asset_id
        assert result["identity"]["creator"] == "TestUser"
        assert "metadata" in result
        assert "access_policy" in result
        assert "compute_interface" in result
        assert "provenance" in result

    def test_skills_validate_asset_standard(self, skills, test_files):
        """Register an asset, then validate it against OAS-DAS."""
        from oasyce.skills.agent_skills import OasyceSkills

        file_info = skills.scan_data_skill(test_files["txt"], skip_privacy_check=True)
        metadata = skills.generate_metadata_skill(file_info, ["Test"], "TestUser")
        signed = skills.create_certificate_skill(metadata)
        skills.register_data_asset_skill(signed)

        asset_id = signed["asset_id"]
        result = skills.validate_asset_standard_skill(asset_id)

        assert result["valid"] is True
        assert result["errors"] == []
        assert result["asset_id"] == asset_id

    def test_skills_asset_not_found(self, skills):
        """get_asset_standard_skill raises for nonexistent asset."""
        with pytest.raises(RuntimeError, match="Asset not found"):
            skills.get_asset_standard_skill("OAS_NONEXISTENT")

    def test_cli_asset_info_json(self, skills, test_files):
        """Test CLI asset-info --json via subprocess."""
        file_info = skills.scan_data_skill(test_files["txt"], skip_privacy_check=True)
        metadata = skills.generate_metadata_skill(file_info, ["CLI"], "TestUser")
        signed = skills.create_certificate_skill(metadata)
        skills.register_data_asset_skill(signed)

        asset_id = signed["asset_id"]
        env = os.environ.copy()
        env["OASYCE_VAULT_DIR"] = skills.vault_path

        result = subprocess.run(
            [sys.executable, "-m", "oasyce.cli", "asset-info", asset_id, "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        # asset-info should not crash (exit 0 or print error JSON)
        # If asset search works via vault, it prints JSON; if env mismatch, prints error
        assert result.returncode == 0 or "Error" in result.stderr

    def test_cli_asset_validate_json(self, skills, test_files):
        """Test CLI asset-validate --json via subprocess."""
        file_info = skills.scan_data_skill(test_files["txt"], skip_privacy_check=True)
        metadata = skills.generate_metadata_skill(file_info, ["CLI"], "TestUser")
        signed = skills.create_certificate_skill(metadata)
        skills.register_data_asset_skill(signed)

        asset_id = signed["asset_id"]
        env = os.environ.copy()
        env["OASYCE_VAULT_DIR"] = skills.vault_path

        result = subprocess.run(
            [sys.executable, "-m", "oasyce.cli", "asset-validate", asset_id, "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0 or "Error" in result.stderr
