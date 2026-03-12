import pytest
from oasyce_plugin.models import AssetMetadata
from oasyce_plugin.engines.l3_tee import TEEComputeEngine


@pytest.fixture
def sample_asset():
    """Create a sample AssetMetadata for testing."""
    return AssetMetadata(
        asset_id="OAS_TEST_001",
        filename="test_document.pdf",
        owner="Alice",
        tags=["test", "document"],
        timestamp=1710000000,
        file_size_bytes=1024,
        classification={"category": "DOCUMENT", "sensitivity": "private"}
    )


@pytest.fixture
def sample_ai_prompt():
    """Sample AI prompt for compute testing."""
    return "Extract key insights about data ownership"


class TestTEEComputeEngine:
    """Test suite for L3 TEE Compute Engine."""

    def test_execute_blind_compute_success(self, sample_asset, sample_ai_prompt):
        """Test that TEE compute executes successfully."""
        result = TEEComputeEngine.execute_blind_compute(sample_asset, sample_ai_prompt)
        
        assert result.success is True
        assert result.data is not None
        assert "result" in result.data
        assert "zk_proof" in result.data
        assert "attestation" in result.data

    def test_execute_blind_compute_returns_insight(self, sample_asset, sample_ai_prompt):
        """Test that compute result contains expected insight."""
        result = TEEComputeEngine.execute_blind_compute(sample_asset, sample_ai_prompt)
        
        compute_result = result.data["result"]
        assert "insight" in compute_result
        assert "compute_time_ms" in compute_result
        assert sample_asset.filename in compute_result["insight"]
        assert sample_ai_prompt in compute_result["insight"]

    def test_zk_proof_generation(self, sample_asset, sample_ai_prompt):
        """Test that zk-PoE proof is generated correctly."""
        result = TEEComputeEngine.execute_blind_compute(sample_asset, sample_ai_prompt)
        
        zk_proof = result.data["zk_proof"]
        assert zk_proof.startswith("zkPoE_0x")
        # SHA3-256 produces 64 hex characters
        assert len(zk_proof) == len("zkPoE_0x") + 64

    def test_attestation_present(self, sample_asset, sample_ai_prompt):
        """Test that attestation is included in result."""
        result = TEEComputeEngine.execute_blind_compute(sample_asset, sample_ai_prompt)
        
        assert result.data["attestation"] == "Oasyce_Intel_SGX_Node_Verified"

    def test_compute_time_recorded(self, sample_asset, sample_ai_prompt):
        """Test that compute time is recorded in result."""
        result = TEEComputeEngine.execute_blind_compute(sample_asset, sample_ai_prompt)
        
        compute_time = result.data["result"]["compute_time_ms"]
        assert isinstance(compute_time, int)
        assert compute_time > 0
