"""Built-in schema definitions for all asset types."""

from __future__ import annotations

from .types import AssetType, FieldSpec, SchemaVersion

HASH_RE = r"^[0-9a-f]{64}$"
SIG_RE = r"^[0-9a-f]{128}$"
ASSET_RE = r"^OAS_[0-9A-F]{8}$"

# ── data/v1 ───────────────────────────────────────────────────────
DATA_V1 = SchemaVersion(
    asset_type=AssetType.DATA,
    version=1,
    fields=(
        FieldSpec(name="schema_version", type=int),
        FieldSpec(name="engine_version", type=str),
        FieldSpec(name="asset_id", type=str, regex=ASSET_RE),
        FieldSpec(name="filename", type=str, regex=r".+"),  # non-empty
        FieldSpec(name="owner", type=str, regex=r".+"),  # non-empty
        FieldSpec(name="tags", type=list, item_type=str),
        FieldSpec(name="timestamp", type=int),
        FieldSpec(name="file_size_bytes", type=int),
        FieldSpec(name="file_hash", type=str, regex=HASH_RE),
        FieldSpec(name="hash_algo", type=str, regex=r"^sha256$"),
        # Optional fields
        FieldSpec(name="rights_type", type=str, required=False, default="original"),
        FieldSpec(name="co_creators", type=list, required=False, default=None),
        FieldSpec(name="disputed", type=bool, required=False, default=False),
        FieldSpec(name="classification", type=dict, required=False, default=None),
        FieldSpec(name="popc_signature", type=str, required=False, regex=SIG_RE),
        FieldSpec(name="certificate_issuer", type=str, required=False),
        FieldSpec(name="signature_alg", type=str, required=False),
        FieldSpec(name="signature_key_id", type=str, required=False),
        FieldSpec(name="risk_level", type=str, required=False, default="public"),
        FieldSpec(name="max_access_level", type=str, required=False, default="L3"),
    ),
)

# ── capability/v1 ────────────────────────────────────────────────
CAPABILITY_V1 = SchemaVersion(
    asset_type=AssetType.CAPABILITY,
    version=1,
    fields=(
        FieldSpec(name="capability_id", type=str),
        FieldSpec(name="name", type=str, regex=r".+"),
        FieldSpec(name="provider", type=str, regex=r".+"),
        FieldSpec(name="tags", type=list, item_type=str),
        FieldSpec(name="intents", type=list, item_type=str, required=False, default=None),
        FieldSpec(name="base_price", type=float, required=False, default=0.0),
        FieldSpec(name="semantic_vector", type=list, required=False, default=None),
    ),
)

# ── oracle/v1 ────────────────────────────────────────────────────
ORACLE_V1 = SchemaVersion(
    asset_type=AssetType.ORACLE,
    version=1,
    fields=(
        FieldSpec(name="oracle_id", type=str),
        FieldSpec(name="feed_type", type=str),
        FieldSpec(name="provider", type=str, regex=r".+"),
        FieldSpec(name="freshness_tier", type=str, required=False, default="standard"),
        FieldSpec(name="bond_amount", type=float, required=False, default=0.0),
    ),
)

# ── identity/v1 ──────────────────────────────────────────────────
IDENTITY_V1 = SchemaVersion(
    asset_type=AssetType.IDENTITY,
    version=1,
    fields=(
        FieldSpec(name="identity_id", type=str),
        FieldSpec(name="identity_type", type=str),
        FieldSpec(name="trust_tier", type=str, required=False, default="newcomer"),
        FieldSpec(name="credentials", type=list, required=False, default=None),
    ),
)

# ── Schema catalog ───────────────────────────────────────────────
# (asset_type, version) → SchemaVersion
_CATALOG: dict = {
    (AssetType.DATA, 1): DATA_V1,
    (AssetType.CAPABILITY, 1): CAPABILITY_V1,
    (AssetType.ORACLE, 1): ORACLE_V1,
    (AssetType.IDENTITY, 1): IDENTITY_V1,
}


def get_schema(asset_type: AssetType, version: int = 1) -> SchemaVersion | None:
    """Look up a schema by type and version."""
    return _CATALOG.get((asset_type, version))


def latest_version(asset_type: AssetType) -> int:
    """Return the latest version number for an asset type."""
    versions = [v for (t, v) in _CATALOG if t == asset_type]
    return max(versions) if versions else 0
