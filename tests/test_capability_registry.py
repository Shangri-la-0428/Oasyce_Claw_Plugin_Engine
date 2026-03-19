"""
Tests for Capability Registry + Manifest + OAS Unified Standard.

Covers:
  - CapabilityManifest creation, validation, serialization
  - CapabilityRegistry CRUD, search, version management, status lifecycle
  - OAS unified standard backward compatibility with OasDasAsset
  - CapabilityInterfaceLayer validation
"""

from __future__ import annotations

import hashlib
import math
import time

import pytest

from oasyce.capabilities.manifest import (
    CapabilityManifest,
    PricingConfig,
    StakingConfig,
    QualityPolicy,
    ExecutionLimits,
    compute_capability_id,
    VALID_STATUSES,
)
from oasyce.capabilities.registry import (
    CapabilityRegistry,
    RegistryError,
)
from oasyce.standards.oas import (
    AssetType,
    CapabilityInterfaceLayer,
    OasAsset,
)
from oasyce.standards.oas_das import (
    OasDasAsset,
    IdentityLayer,
    MetadataLayer,
    AccessPolicyLayer,
    ComputeInterfaceLayer,
    ProvenanceLayer,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_manifest(**overrides) -> CapabilityManifest:
    """Create a valid manifest with sensible defaults."""
    defaults = dict(
        name="text-summarizer",
        description="Summarizes text documents",
        version="1.0.0",
        provider="abc123provider",
        tags=["nlp", "summarization"],
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
    )
    defaults.update(overrides)
    return CapabilityManifest(**defaults)


def _make_vector(vals: list) -> list:
    """Normalize a vector for cosine tests."""
    norm = math.sqrt(sum(v * v for v in vals))
    return [v / norm for v in vals] if norm else vals


# ═════════════════════════════════════════════════════════════════════════════
# 1. compute_capability_id
# ═════════════════════════════════════════════════════════════════════════════


class TestCapabilityId:
    def test_deterministic(self):
        cid = compute_capability_id("provA", "svc", "1.0.0")
        assert cid == compute_capability_id("provA", "svc", "1.0.0")

    def test_different_version_different_id(self):
        id1 = compute_capability_id("p", "svc", "1.0.0")
        id2 = compute_capability_id("p", "svc", "2.0.0")
        assert id1 != id2

    def test_different_provider_different_id(self):
        id1 = compute_capability_id("provA", "svc", "1.0.0")
        id2 = compute_capability_id("provB", "svc", "1.0.0")
        assert id1 != id2

    def test_length_32(self):
        cid = compute_capability_id("p", "n", "v")
        assert len(cid) == 32

    def test_matches_sha256_prefix(self):
        raw = "p:n:v"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:32]
        assert compute_capability_id("p", "n", "v") == expected


# ═════════════════════════════════════════════════════════════════════════════
# 2. CapabilityManifest
# ═════════════════════════════════════════════════════════════════════════════


class TestCapabilityManifest:

    def test_create_valid(self):
        m = _make_manifest()
        assert m.name == "text-summarizer"
        assert m.capability_id  # auto-computed
        assert m.status == "active"
        assert m.created_at > 0

    def test_auto_capability_id(self):
        m = _make_manifest()
        expected = compute_capability_id(m.provider, m.name, m.version)
        assert m.capability_id == expected

    def test_validate_valid(self):
        m = _make_manifest()
        assert m.validate() == []

    def test_validate_missing_name(self):
        m = _make_manifest(name="")
        errors = m.validate()
        assert any("name" in e for e in errors)

    def test_validate_missing_provider(self):
        m = _make_manifest(provider="")
        errors = m.validate()
        assert any("provider" in e for e in errors)

    def test_validate_missing_version(self):
        m = _make_manifest(version="")
        errors = m.validate()
        assert any("version" in e for e in errors)

    def test_validate_missing_input_schema(self):
        m = _make_manifest(input_schema={})
        errors = m.validate()
        assert any("input_schema" in e for e in errors)

    def test_validate_missing_output_schema(self):
        m = _make_manifest(output_schema={})
        errors = m.validate()
        assert any("output_schema" in e for e in errors)

    def test_validate_schema_no_type_key(self):
        m = _make_manifest(input_schema={"properties": {}})
        errors = m.validate()
        assert any("input_schema" in e and "type" in e for e in errors)

    def test_validate_invalid_status(self):
        m = _make_manifest(status="deleted")
        errors = m.validate()
        assert any("status" in e for e in errors)

    def test_validate_bad_pricing(self):
        m = _make_manifest(pricing=PricingConfig(base_price=-1))
        errors = m.validate()
        assert any("base_price" in e for e in errors)

    def test_validate_bad_reserve_ratio(self):
        m = _make_manifest(pricing=PricingConfig(reserve_ratio=0))
        errors = m.validate()
        assert any("reserve_ratio" in e for e in errors)

    def test_validate_bad_staking(self):
        m = _make_manifest(staking=StakingConfig(min_bond=-5))
        errors = m.validate()
        assert any("min_bond" in e for e in errors)

    def test_validate_bad_quality_type(self):
        m = _make_manifest(quality=QualityPolicy(verification_type="magic"))
        errors = m.validate()
        assert any("verification_type" in e for e in errors)

    def test_validate_bad_limits(self):
        m = _make_manifest(limits=ExecutionLimits(timeout_seconds=0))
        errors = m.validate()
        assert any("timeout_seconds" in e for e in errors)

    def test_to_dict_roundtrip(self):
        m = _make_manifest()
        d = m.to_dict()
        m2 = CapabilityManifest.from_dict(d)
        assert m2.name == m.name
        assert m2.capability_id == m.capability_id
        assert m2.pricing.base_price == m.pricing.base_price

    def test_from_dict_nested_configs(self):
        d = _make_manifest().to_dict()
        d["pricing"]["base_price"] = 5.0
        m = CapabilityManifest.from_dict(d)
        assert m.pricing.base_price == 5.0

    def test_timestamps_auto_set(self):
        before = int(time.time())
        m = _make_manifest()
        after = int(time.time())
        assert before <= m.created_at <= after
        assert m.updated_at == m.created_at


# ═════════════════════════════════════════════════════════════════════════════
# 3. CapabilityRegistry — CRUD
# ═════════════════════════════════════════════════════════════════════════════


class TestRegistryCRUD:

    def test_register_and_get(self):
        reg = CapabilityRegistry()
        m = _make_manifest()
        cid = reg.register(m)
        assert cid == m.capability_id
        assert reg.get(cid) is m

    def test_register_invalid_raises(self):
        reg = CapabilityRegistry()
        m = _make_manifest(name="")
        with pytest.raises(RegistryError, match="Invalid manifest"):
            reg.register(m)

    def test_register_duplicate_raises(self):
        reg = CapabilityRegistry()
        m = _make_manifest()
        reg.register(m)
        with pytest.raises(RegistryError, match="already registered"):
            reg.register(_make_manifest())

    def test_register_different_version_ok(self):
        reg = CapabilityRegistry()
        reg.register(_make_manifest(version="1.0.0"))
        reg.register(_make_manifest(version="2.0.0"))
        assert reg.count == 2

    def test_get_not_found(self):
        reg = CapabilityRegistry()
        assert reg.get("nonexistent") is None

    def test_count(self):
        reg = CapabilityRegistry()
        assert reg.count == 0
        reg.register(_make_manifest(version="1.0.0"))
        assert reg.count == 1
        reg.register(_make_manifest(version="2.0.0"))
        assert reg.count == 2


# ═════════════════════════════════════════════════════════════════════════════
# 4. CapabilityRegistry — Status lifecycle
# ═════════════════════════════════════════════════════════════════════════════


class TestRegistryStatus:

    def test_update_status(self):
        reg = CapabilityRegistry()
        m = _make_manifest()
        cid = reg.register(m)
        reg.update_status(cid, "paused")
        assert reg.get(cid).status == "paused"

    def test_update_status_invalid(self):
        reg = CapabilityRegistry()
        m = _make_manifest()
        cid = reg.register(m)
        with pytest.raises(RegistryError, match="Invalid status"):
            reg.update_status(cid, "deleted")

    def test_update_status_not_found(self):
        reg = CapabilityRegistry()
        with pytest.raises(RegistryError, match="not found"):
            reg.update_status("nope", "active")

    def test_unregister_marks_deprecated(self):
        reg = CapabilityRegistry()
        m = _make_manifest()
        cid = reg.register(m)
        reg.unregister(cid)
        assert reg.get(cid).status == "deprecated"

    def test_updated_at_changes(self):
        reg = CapabilityRegistry()
        m = _make_manifest()
        cid = reg.register(m)
        old_ts = m.updated_at
        reg.update_status(cid, "paused")
        assert reg.get(cid).updated_at >= old_ts

    def test_reregister_deprecated(self):
        """Can re-register a deprecated capability."""
        reg = CapabilityRegistry()
        m = _make_manifest()
        cid = reg.register(m)
        reg.unregister(cid)
        m2 = _make_manifest()
        cid2 = reg.register(m2)
        assert cid2 == cid
        assert reg.get(cid).status == "active"


# ═════════════════════════════════════════════════════════════════════════════
# 5. CapabilityRegistry — Provider queries
# ═════════════════════════════════════════════════════════════════════════════


class TestRegistryProviderQueries:

    def test_list_by_provider(self):
        reg = CapabilityRegistry()
        reg.register(_make_manifest(provider="alice", version="1.0.0"))
        reg.register(_make_manifest(provider="alice", version="2.0.0"))
        reg.register(_make_manifest(provider="bob", version="1.0.0"))
        assert len(reg.list_by_provider("alice")) == 2
        assert len(reg.list_by_provider("bob")) == 1
        assert len(reg.list_by_provider("charlie")) == 0

    def test_list_all(self):
        reg = CapabilityRegistry()
        reg.register(_make_manifest(version="1.0.0"))
        reg.register(_make_manifest(version="2.0.0"))
        m3 = _make_manifest(version="3.0.0")
        reg.register(m3)
        reg.unregister(m3.capability_id)

        assert len(reg.list_all()) == 2  # excludes deprecated
        assert len(reg.list_all(include_deprecated=True)) == 3


# ═════════════════════════════════════════════════════════════════════════════
# 6. CapabilityRegistry — Search
# ═════════════════════════════════════════════════════════════════════════════


class TestRegistrySearch:

    def test_search_by_tags(self):
        reg = CapabilityRegistry()
        reg.register(_make_manifest(name="nlp-svc", version="1.0.0", tags=["nlp", "text"]))
        reg.register(_make_manifest(name="img-svc", version="1.0.0", tags=["vision", "image"]))
        results = reg.search(query_tags=["nlp"])
        assert len(results) >= 1
        assert results[0][0].name == "nlp-svc"
        assert results[0][1] > 0

    def test_search_by_semantic_vector(self):
        reg = CapabilityRegistry()
        v1 = _make_vector([1.0, 0.0, 0.0])
        v2 = _make_vector([0.0, 1.0, 0.0])
        reg.register(_make_manifest(name="svc-a", version="1.0.0", semantic_vector=v1, tags=[]))
        reg.register(_make_manifest(name="svc-b", version="1.0.0", semantic_vector=v2, tags=[]))
        results = reg.search(semantic_vector=v1)
        assert results[0][0].name == "svc-a"

    def test_search_combined(self):
        reg = CapabilityRegistry()
        v1 = _make_vector([1.0, 0.0])
        reg.register(
            _make_manifest(
                name="best-match",
                version="1.0.0",
                tags=["nlp"],
                semantic_vector=v1,
            )
        )
        reg.register(
            _make_manifest(
                name="tag-only",
                version="1.0.0",
                tags=["nlp"],
                semantic_vector=None,
            )
        )
        results = reg.search(query_tags=["nlp"], semantic_vector=v1)
        assert results[0][0].name == "best-match"

    def test_search_excludes_deprecated(self):
        reg = CapabilityRegistry()
        m = _make_manifest(tags=["test"])
        cid = reg.register(m)
        reg.unregister(cid)
        results = reg.search(query_tags=["test"])
        assert len(results) == 0

    def test_search_include_deprecated(self):
        reg = CapabilityRegistry()
        m = _make_manifest(tags=["test"])
        cid = reg.register(m)
        reg.unregister(cid)
        results = reg.search(query_tags=["test"], include_deprecated=True)
        assert len(results) == 1

    def test_search_limit(self):
        reg = CapabilityRegistry()
        for i in range(20):
            reg.register(
                _make_manifest(
                    name=f"svc-{i}",
                    version="1.0.0",
                    provider=f"prov-{i}",
                    tags=["common"],
                )
            )
        results = reg.search(query_tags=["common"], limit=5)
        assert len(results) == 5

    def test_search_no_criteria_returns_empty(self):
        reg = CapabilityRegistry()
        reg.register(_make_manifest())
        results = reg.search()
        assert len(results) == 0

    def test_search_scores_ordered(self):
        reg = CapabilityRegistry()
        reg.register(
            _make_manifest(
                name="partial",
                version="1.0.0",
                tags=["nlp", "other"],
            )
        )
        reg.register(
            _make_manifest(
                name="exact",
                version="1.0.0",
                tags=["nlp"],
                provider="prov2",
            )
        )
        results = reg.search(query_tags=["nlp"])
        # "exact" has higher Jaccard (1/1 = 1.0) than "partial" (1/2 = 0.5)
        assert results[0][0].name == "exact"


# ═════════════════════════════════════════════════════════════════════════════
# 7. Version Management
# ═════════════════════════════════════════════════════════════════════════════


class TestVersionManagement:

    def test_same_name_different_version(self):
        reg = CapabilityRegistry()
        m1 = _make_manifest(version="1.0.0")
        m2 = _make_manifest(version="2.0.0")
        cid1 = reg.register(m1)
        cid2 = reg.register(m2)
        assert cid1 != cid2
        assert reg.get(cid1).version == "1.0.0"
        assert reg.get(cid2).version == "2.0.0"

    def test_deprecate_old_version(self):
        reg = CapabilityRegistry()
        m1 = _make_manifest(version="1.0.0")
        cid1 = reg.register(m1)
        reg.register(_make_manifest(version="2.0.0"))
        reg.unregister(cid1)
        assert reg.get(cid1).status == "deprecated"

    def test_provider_versions_list(self):
        reg = CapabilityRegistry()
        reg.register(_make_manifest(version="1.0.0"))
        reg.register(_make_manifest(version="2.0.0"))
        reg.register(_make_manifest(version="3.0.0"))
        caps = reg.list_by_provider("abc123provider")
        versions = sorted(m.version for m in caps)
        assert versions == ["1.0.0", "2.0.0", "3.0.0"]


# ═════════════════════════════════════════════════════════════════════════════
# 8. OAS Unified Standard
# ═════════════════════════════════════════════════════════════════════════════


class TestOasUnifiedStandard:

    def test_asset_type_enum(self):
        assert AssetType.DATA.value == "data"
        assert AssetType.CAPABILITY.value == "capability"

    def test_oas_asset_default_is_data(self):
        asset = OasAsset()
        assert asset.asset_type == "data"

    def test_oas_asset_capability_type(self):
        asset = OasAsset(
            asset_type="capability",
            capability_interface=CapabilityInterfaceLayer(
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
        )
        assert asset.asset_type == "capability"
        assert asset.validate() == []

    def test_capability_requires_interface(self):
        asset = OasAsset(asset_type="capability")
        errors = asset.validate()
        assert any("capability_interface" in e for e in errors)

    def test_invalid_asset_type(self):
        asset = OasAsset(asset_type="unknown")
        errors = asset.validate()
        assert any("asset_type" in e for e in errors)

    def test_from_das_roundtrip(self):
        das = OasDasAsset(
            identity=IdentityLayer(asset_id="a1", creator="c1", created_at=100),
            metadata=MetadataLayer(title="Test Data"),
            access_policy=AccessPolicyLayer(),
        )
        unified = OasAsset.from_das(das)
        assert unified.asset_type == "data"
        assert unified.identity.asset_id == "a1"

        back = unified.to_das()
        assert back.identity.asset_id == "a1"
        assert back.metadata.title == "Test Data"

    def test_to_das_fails_for_capability(self):
        asset = OasAsset(asset_type="capability")
        with pytest.raises(ValueError, match="Cannot convert"):
            asset.to_das()

    def test_to_dict(self):
        asset = OasAsset(
            asset_type="capability",
            identity=IdentityLayer(asset_id="cap1", creator="p1", created_at=1),
            capability_interface=CapabilityInterfaceLayer(
                input_schema={"type": "object"},
            ),
        )
        d = asset.to_dict()
        assert d["asset_type"] == "capability"
        assert "capability_interface" in d
        assert d["capability_interface"]["input_schema"]["type"] == "object"


# ═════════════════════════════════════════════════════════════════════════════
# 9. CapabilityInterfaceLayer validation
# ═════════════════════════════════════════════════════════════════════════════


class TestCapabilityInterfaceLayer:

    def test_valid(self):
        layer = CapabilityInterfaceLayer(
            input_schema={"type": "object"},
            output_schema={"type": "string"},
        )
        assert layer.validate() == []

    def test_empty_schemas_ok(self):
        layer = CapabilityInterfaceLayer()
        assert layer.validate() == []

    def test_schema_missing_type_key(self):
        layer = CapabilityInterfaceLayer(
            input_schema={"properties": {}},
        )
        errors = layer.validate()
        assert any("input_schema" in e and "type" in e for e in errors)

    def test_output_schema_missing_type(self):
        layer = CapabilityInterfaceLayer(
            output_schema={"properties": {}},
        )
        errors = layer.validate()
        assert any("output_schema" in e for e in errors)


# ═════════════════════════════════════════════════════════════════════════════
# 10. Backward Compatibility — imports still work
# ═════════════════════════════════════════════════════════════════════════════


class TestBackwardCompat:

    def test_oas_das_import_from_standards(self):
        """Old import path still works."""
        from oasyce.standards import OasDasAsset as FromPkg
        from oasyce.standards.oas_das import OasDasAsset as Direct

        assert FromPkg is Direct

    def test_oas_das_asset_unchanged(self):
        """OasDasAsset creation unchanged from Phase 1."""
        das = OasDasAsset(
            identity=IdentityLayer(asset_id="test", creator="me", created_at=1),
            metadata=MetadataLayer(title="Test"),
            access_policy=AccessPolicyLayer(),
        )
        assert das.identity.asset_id == "test"
        errors = das.validate()
        assert errors == []

    def test_new_classes_available_from_standards(self):
        """New classes available via standards package."""
        from oasyce.standards import AssetType, OasAsset, CapabilityInterfaceLayer

        assert AssetType.CAPABILITY.value == "capability"


# ═════════════════════════════════════════════════════════════════════════════
# 11. Sub-config validation
# ═════════════════════════════════════════════════════════════════════════════


class TestSubConfigs:

    def test_pricing_valid(self):
        assert PricingConfig().validate() == []

    def test_pricing_invalid_fee(self):
        p = PricingConfig(protocol_fee_pct=1.5)
        assert any("protocol_fee_pct" in e for e in p.validate())

    def test_staking_valid(self):
        assert StakingConfig().validate() == []

    def test_quality_valid(self):
        assert QualityPolicy().validate() == []

    def test_quality_bad_window(self):
        q = QualityPolicy(dispute_window_seconds=0)
        assert any("dispute_window" in e for e in q.validate())

    def test_execution_limits_valid(self):
        assert ExecutionLimits().validate() == []

    def test_execution_limits_bad_concurrent(self):
        el = ExecutionLimits(max_concurrent_calls=0)
        assert any("max_concurrent" in e for e in el.validate())
