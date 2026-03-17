"""Tests for the Schema Registry (Item 1)."""
import pytest
from oasyce_plugin.schema_registry import AssetType, validate, register, get_schema
from oasyce_plugin.engines.schema import validate_metadata


# ── Helpers ───────────────────────────────────────────────────────

def _valid_data_payload():
    return {
        "schema_version": 1,
        "engine_version": "0.3.0",
        "asset_id": "OAS_AABBCCDD",
        "filename": "test.pdf",
        "owner": "Alice",
        "tags": ["test", "doc"],
        "timestamp": 1700000000,
        "file_size_bytes": 1024,
        "file_hash": "a" * 64,
        "hash_algo": "sha256",
    }


def _valid_capability_payload():
    return {
        "capability_id": "cap_001",
        "name": "Translator",
        "provider": "ProviderA",
        "tags": ["nlp", "translate"],
    }


def _valid_oracle_payload():
    return {
        "oracle_id": "oracle_001",
        "feed_type": "price",
        "provider": "OracleProviderA",
    }


def _valid_identity_payload():
    return {
        "identity_id": "id_001",
        "identity_type": "individual",
    }


# ── AssetType enum ────────────────────────────────────────────────

class TestAssetType:
    def test_values(self):
        assert AssetType.DATA == "data"
        assert AssetType.CAPABILITY == "capability"
        assert AssetType.ORACLE == "oracle"
        assert AssetType.IDENTITY == "identity"

    def test_string_coercion(self):
        assert AssetType("data") is AssetType.DATA
        assert AssetType("capability") is AssetType.CAPABILITY

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            AssetType("nonexistent")


# ── get_schema ────────────────────────────────────────────────────

class TestGetSchema:
    def test_find_data_v1(self):
        schema = get_schema(AssetType.DATA, 1)
        assert schema is not None
        assert schema.asset_type == AssetType.DATA
        assert schema.version == 1

    def test_find_all_types(self):
        for at in AssetType:
            schema = get_schema(at, 1)
            assert schema is not None, f"Missing schema for {at}"

    def test_missing_version_returns_none(self):
        assert get_schema(AssetType.DATA, 99) is None


# ── data/v1 validation ───────────────────────────────────────────

class TestDataV1Validation:
    def test_valid_payload(self):
        result = validate("data", _valid_data_payload())
        assert result.ok is True

    def test_missing_required_field(self):
        payload = _valid_data_payload()
        del payload["file_hash"]
        result = validate("data", payload)
        assert result.ok is False
        assert "file_hash" in result.error

    def test_wrong_type(self):
        payload = _valid_data_payload()
        payload["schema_version"] = "1"  # should be int
        result = validate("data", payload)
        assert result.ok is False
        assert "schema_version" in result.error

    def test_regex_mismatch(self):
        payload = _valid_data_payload()
        payload["asset_id"] = "INVALID"
        result = validate("data", payload)
        assert result.ok is False
        assert "asset_id" in result.error

    def test_hash_algo_must_be_sha256(self):
        payload = _valid_data_payload()
        payload["hash_algo"] = "md5"
        result = validate("data", payload)
        assert result.ok is False

    def test_tags_must_be_str_list(self):
        payload = _valid_data_payload()
        payload["tags"] = [1, 2, 3]
        result = validate("data", payload)
        assert result.ok is False
        assert "tags" in result.error

    def test_empty_filename_rejected(self):
        payload = _valid_data_payload()
        payload["filename"] = ""
        result = validate("data", payload)
        assert result.ok is False

    def test_not_a_dict(self):
        result = validate("data", "not a dict")
        assert result.ok is False
        assert result.code == "INVALID_PAYLOAD"

    def test_unknown_asset_type(self):
        result = validate("unknown_type", {})
        assert result.ok is False
        assert result.code == "UNKNOWN_ASSET_TYPE"

    def test_string_asset_type_accepted(self):
        result = validate("data", _valid_data_payload())
        assert result.ok is True


# ── capability/v1, oracle/v1, identity/v1 ────────────────────────

class TestOtherSchemas:
    def test_capability_valid(self):
        result = validate("capability", _valid_capability_payload())
        assert result.ok is True

    def test_capability_missing_name(self):
        payload = _valid_capability_payload()
        del payload["name"]
        result = validate("capability", payload)
        assert result.ok is False

    def test_oracle_valid(self):
        result = validate("oracle", _valid_oracle_payload())
        assert result.ok is True

    def test_identity_valid(self):
        result = validate("identity", _valid_identity_payload())
        assert result.ok is True


# ── register() ────────────────────────────────────────────────────

class TestRegister:
    def test_stamps_asset_type(self):
        result = register("data", _valid_data_payload())
        assert result.ok is True
        assert result.data["asset_type"] == "data"

    def test_register_capability(self):
        result = register("capability", _valid_capability_payload())
        assert result.ok is True
        assert result.data["asset_type"] == "capability"

    def test_register_invalid_fails(self):
        result = register("data", {"bad": "payload"})
        assert result.ok is False


# ── Backward compatibility: validate_metadata ─────────────────────

class TestBackwardCompat:
    def test_validate_metadata_passes(self):
        result = validate_metadata(_valid_data_payload())
        assert result.ok is True

    def test_validate_metadata_missing_field(self):
        payload = _valid_data_payload()
        del payload["owner"]
        result = validate_metadata(payload)
        assert result.ok is False

    def test_validate_metadata_with_signature(self):
        payload = _valid_data_payload()
        payload["popc_signature"] = "a" * 128
        result = validate_metadata(payload, require_signature=True)
        assert result.ok is True

    def test_validate_metadata_missing_signature(self):
        payload = _valid_data_payload()
        result = validate_metadata(payload, require_signature=True)
        assert result.ok is False

    def test_validate_metadata_not_dict(self):
        result = validate_metadata("not a dict")
        assert result.ok is False
