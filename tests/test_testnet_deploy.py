"""
Tests for testnet deployment: genesis creation, import/export, validation,
multi-node init, faucet server, and chain initialization.
"""

import json
import os
import shutil
import tempfile
import time

import pytest

from oasyce_plugin.consensus.core.types import OAS_DECIMALS, from_units, to_units
from oasyce_plugin.consensus.testnet_config import (
    DEFAULT_TESTNET_CONFIG,
    DEVNET_CONFIG,
    TestnetConfig,
    ValidatorInfo,
)
from oasyce_plugin.consensus.genesis import (
    GenesisState,
    GenesisValidator,
    create_genesis,
    export_genesis,
    import_genesis,
    initialize_chain,
    validate_genesis,
)
from oasyce_plugin.consensus.network.sync_protocol import GENESIS_PREV_HASH


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="oasyce_deploy_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def sample_validators():
    """Three sample validators for testing."""
    return [
        ValidatorInfo(pubkey="aaa111" * 5 + "aa", stake=1000 * OAS_DECIMALS,
                      commission=1000, moniker="val-0"),
        ValidatorInfo(pubkey="bbb222" * 5 + "bb", stake=2000 * OAS_DECIMALS,
                      commission=500, moniker="val-1"),
        ValidatorInfo(pubkey="ccc333" * 5 + "cc", stake=500 * OAS_DECIMALS,
                      commission=2000, moniker="val-2"),
    ]


@pytest.fixture()
def testnet_config(sample_validators):
    """Testnet config with sample validators."""
    return TestnetConfig(
        chain_id="oasyce-test-deploy",
        genesis_time=1710720000,
        initial_validators=sample_validators,
    )


# ── TestnetConfig tests ──────────────────────────────────────────────


class TestTestnetConfig:
    def test_default_config_values(self):
        """Default testnet config has expected parameters."""
        cfg = DEFAULT_TESTNET_CONFIG
        assert cfg.chain_id == "oasyce-testnet-1"
        assert cfg.blocks_per_epoch == 10
        assert cfg.min_stake == 100 * OAS_DECIMALS
        assert cfg.faucet_enabled is True
        assert cfg.faucet_amount == 10000 * OAS_DECIMALS

    def test_devnet_config(self):
        """Devnet config has lower barriers than testnet."""
        assert DEVNET_CONFIG.min_stake < DEFAULT_TESTNET_CONFIG.min_stake
        assert DEVNET_CONFIG.block_reward > DEFAULT_TESTNET_CONFIG.block_reward
        assert DEVNET_CONFIG.voting_period < DEFAULT_TESTNET_CONFIG.voting_period
        assert DEVNET_CONFIG.chain_id == "oasyce-devnet-1"

    def test_config_to_dict_roundtrip(self, testnet_config):
        """Config serializes and deserializes correctly."""
        d = testnet_config.to_dict()
        restored = TestnetConfig.from_dict(d)
        assert restored.chain_id == testnet_config.chain_id
        assert restored.genesis_time == testnet_config.genesis_time
        assert restored.min_stake == testnet_config.min_stake
        assert len(restored.initial_validators) == len(testnet_config.initial_validators)
        for orig, rest in zip(testnet_config.initial_validators, restored.initial_validators):
            assert orig.pubkey == rest.pubkey
            assert orig.stake == rest.stake
            assert orig.commission == rest.commission

    def test_config_to_consensus_params(self, testnet_config):
        """to_consensus_params() produces valid params dict."""
        params = testnet_config.to_consensus_params()
        assert params["chain_id"] == testnet_config.chain_id
        assert params["blocks_per_epoch"] == testnet_config.blocks_per_epoch
        assert params["unbonding_blocks"] == testnet_config.unbonding_blocks
        assert params["jail_duration"] == testnet_config.jail_duration
        assert "epoch_duration" in params

    def test_config_to_economics(self, testnet_config):
        """to_economics() produces valid economics dict."""
        econ = testnet_config.to_economics()
        assert econ["block_reward"] == testnet_config.block_reward
        assert econ["min_stake"] == testnet_config.min_stake
        assert econ["halving_interval"] == testnet_config.halving_interval
        assert econ["min_deposit"] == testnet_config.min_deposit

    def test_config_from_dict_defaults(self):
        """from_dict with empty dict uses defaults."""
        cfg = TestnetConfig.from_dict({})
        assert cfg.chain_id == "oasyce-testnet-1"
        assert cfg.min_stake == 100 * OAS_DECIMALS

    def test_validator_info_fields(self):
        """ValidatorInfo stores correct fields."""
        v = ValidatorInfo(pubkey="abc123", stake=500, commission=1500, moniker="test")
        assert v.pubkey == "abc123"
        assert v.stake == 500
        assert v.commission == 1500
        assert v.moniker == "test"


# ── Genesis creation tests ───────────────────────────────────────────


class TestGenesisCreation:
    def test_create_genesis_basic(self, testnet_config, sample_validators):
        """create_genesis produces valid GenesisState."""
        state = create_genesis(testnet_config, sample_validators)
        assert state.chain_id == "oasyce-test-deploy"
        assert state.genesis_time == 1710720000
        assert len(state.validators) == 3
        assert state.total_stake == (1000 + 2000 + 500) * OAS_DECIMALS
        assert state.genesis_hash != ""
        assert state.genesis_block.block_number == 0

    def test_create_genesis_uses_config_validators(self, testnet_config):
        """create_genesis uses config.initial_validators when no override."""
        state = create_genesis(testnet_config)
        assert len(state.validators) == len(testnet_config.initial_validators)

    def test_create_genesis_empty_validators(self):
        """create_genesis with no validators produces empty set."""
        config = TestnetConfig(chain_id="empty-chain")
        state = create_genesis(config, [])
        assert len(state.validators) == 0
        assert state.total_stake == 0
        assert state.genesis_hash != ""

    def test_genesis_block_properties(self, testnet_config, sample_validators):
        """Genesis block has correct properties."""
        state = create_genesis(testnet_config, sample_validators)
        block = state.genesis_block
        assert block.block_number == 0
        assert block.prev_hash == GENESIS_PREV_HASH
        assert block.chain_id == "oasyce-test-deploy"
        assert block.timestamp == 1710720000
        assert block.proposer == "genesis"
        assert len(block.operations) == 0

    def test_genesis_hash_deterministic(self, testnet_config, sample_validators):
        """Same config produces same genesis hash."""
        state1 = create_genesis(testnet_config, sample_validators)
        state2 = create_genesis(testnet_config, sample_validators)
        assert state1.genesis_hash == state2.genesis_hash

    def test_different_chain_id_different_hash(self, sample_validators):
        """Different chain_id produces different genesis hash."""
        config1 = TestnetConfig(chain_id="chain-a", genesis_time=1000)
        config2 = TestnetConfig(chain_id="chain-b", genesis_time=1000)
        state1 = create_genesis(config1, sample_validators)
        state2 = create_genesis(config2, sample_validators)
        assert state1.genesis_hash != state2.genesis_hash


# ── Genesis export/import tests ──────────────────────────────────────


class TestGenesisExportImport:
    def test_export_creates_file(self, tmp_dir, testnet_config, sample_validators):
        """export_genesis creates a JSON file."""
        state = create_genesis(testnet_config, sample_validators)
        path = os.path.join(tmp_dir, "genesis.json")
        export_genesis(state, path)
        assert os.path.exists(path)

        data = json.loads(open(path).read())
        assert data["chain_id"] == "oasyce-test-deploy"
        assert len(data["validators"]) == 3

    def test_import_roundtrip(self, tmp_dir, testnet_config, sample_validators):
        """export → import preserves all fields."""
        state = create_genesis(testnet_config, sample_validators)
        path = os.path.join(tmp_dir, "genesis.json")
        export_genesis(state, path)

        restored = import_genesis(path)
        assert restored.chain_id == state.chain_id
        assert restored.genesis_time == state.genesis_time
        assert restored.genesis_hash == state.genesis_hash
        assert len(restored.validators) == len(state.validators)
        assert restored.total_stake == state.total_stake

        for orig, rest in zip(state.validators, restored.validators):
            assert orig.pubkey == rest.pubkey
            assert orig.stake == rest.stake
            assert orig.commission == rest.commission

    def test_import_nonexistent_file(self):
        """import_genesis raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            import_genesis("/nonexistent/genesis.json")

    def test_import_invalid_json(self, tmp_dir):
        """import_genesis raises ValueError for invalid JSON."""
        path = os.path.join(tmp_dir, "bad.json")
        with open(path, "w") as f:
            f.write("not json{{{")
        with pytest.raises(ValueError, match="Invalid genesis JSON"):
            import_genesis(path)

    def test_import_missing_fields(self, tmp_dir):
        """import_genesis raises ValueError for missing required fields."""
        path = os.path.join(tmp_dir, "incomplete.json")
        with open(path, "w") as f:
            json.dump({"foo": "bar"}, f)
        with pytest.raises(ValueError, match="missing required fields"):
            import_genesis(path)

    def test_export_creates_parent_dirs(self, tmp_dir, testnet_config):
        """export_genesis creates parent directories."""
        state = create_genesis(testnet_config, [])
        path = os.path.join(tmp_dir, "sub", "dir", "genesis.json")
        export_genesis(state, path)
        assert os.path.exists(path)

    def test_genesis_config_preserved(self, tmp_dir, testnet_config, sample_validators):
        """Config is preserved through export/import."""
        state = create_genesis(testnet_config, sample_validators)
        path = os.path.join(tmp_dir, "genesis.json")
        export_genesis(state, path)

        restored = import_genesis(path)
        assert restored.config is not None
        assert restored.config.chain_id == testnet_config.chain_id
        assert restored.config.min_stake == testnet_config.min_stake
        assert restored.config.faucet_enabled == testnet_config.faucet_enabled


# ── Genesis validation tests ─────────────────────────────────────────


class TestGenesisValidation:
    def test_valid_genesis(self, testnet_config, sample_validators):
        """Valid genesis passes validation."""
        state = create_genesis(testnet_config, sample_validators)
        errors = validate_genesis(state)
        assert errors == []

    def test_empty_chain_id(self, sample_validators):
        """Empty chain_id fails validation."""
        config = TestnetConfig(chain_id="")
        state = create_genesis(config, sample_validators)
        errors = validate_genesis(state)
        assert any("chain_id is empty" in e for e in errors)

    def test_negative_genesis_time(self, sample_validators):
        """Negative genesis_time fails validation."""
        config = TestnetConfig(genesis_time=-1)
        state = create_genesis(config, sample_validators)
        errors = validate_genesis(state)
        assert any("genesis_time must be positive" in e for e in errors)

    def test_duplicate_validator_pubkey(self):
        """Duplicate validator pubkeys fail validation."""
        v1 = ValidatorInfo(pubkey="same_key", stake=1000 * OAS_DECIMALS, commission=1000)
        v2 = ValidatorInfo(pubkey="same_key", stake=2000 * OAS_DECIMALS, commission=500)
        config = TestnetConfig()
        state = create_genesis(config, [v1, v2])
        errors = validate_genesis(state)
        assert any("duplicate" in e for e in errors)

    def test_zero_stake_validator(self):
        """Zero-stake validator fails validation."""
        v = ValidatorInfo(pubkey="abc123", stake=0, commission=1000)
        config = TestnetConfig()
        state = create_genesis(config, [v])
        errors = validate_genesis(state)
        assert any("non-positive stake" in e for e in errors)

    def test_invalid_commission(self):
        """Commission > 5000 fails validation."""
        v = ValidatorInfo(pubkey="abc123", stake=1000 * OAS_DECIMALS, commission=6000)
        config = TestnetConfig()
        state = create_genesis(config, [v])
        errors = validate_genesis(state)
        assert any("invalid commission" in e for e in errors)

    def test_negative_commission(self):
        """Negative commission fails validation."""
        v = ValidatorInfo(pubkey="abc123", stake=1000 * OAS_DECIMALS, commission=-100)
        config = TestnetConfig()
        state = create_genesis(config, [v])
        errors = validate_genesis(state)
        assert any("invalid commission" in e for e in errors)

    def test_empty_validator_pubkey(self):
        """Empty pubkey fails validation."""
        v = ValidatorInfo(pubkey="", stake=1000 * OAS_DECIMALS, commission=1000)
        config = TestnetConfig()
        state = create_genesis(config, [v])
        errors = validate_genesis(state)
        assert any("empty pubkey" in e for e in errors)

    def test_valid_empty_validators(self):
        """Genesis with no validators is valid."""
        config = TestnetConfig()
        state = create_genesis(config, [])
        errors = validate_genesis(state)
        assert errors == []


# ── Chain initialization tests ───────────────────────────────────────


class TestChainInitialization:
    def test_initialize_chain(self, tmp_dir, testnet_config, sample_validators):
        """initialize_chain creates engine with registered validators."""
        state = create_genesis(testnet_config, sample_validators)
        db_path = os.path.join(tmp_dir, "consensus.db")
        engine = initialize_chain(state, db_path=db_path)

        try:
            validators = engine.get_validators(include_inactive=True)
            assert len(validators) == 3
            assert engine.chain_id == "oasyce-test-deploy"
        finally:
            engine.close()

    def test_initialize_chain_stakes(self, tmp_dir, testnet_config, sample_validators):
        """Initialized validators have correct stakes."""
        state = create_genesis(testnet_config, sample_validators)
        db_path = os.path.join(tmp_dir, "consensus.db")
        engine = initialize_chain(state, db_path=db_path)

        try:
            validators = engine.get_validators(include_inactive=False)
            stakes = {v["validator_id"]: v["total_stake"] for v in validators}

            for orig in sample_validators:
                assert stakes.get(orig.pubkey) == orig.stake
        finally:
            engine.close()

    def test_initialize_chain_no_db_path(self, tmp_dir, testnet_config, sample_validators):
        """initialize_chain works with a temp db path."""
        state = create_genesis(testnet_config, sample_validators)
        db_path = os.path.join(tmp_dir, "inmem.db")
        engine = initialize_chain(state, db_path=db_path)
        try:
            assert len(engine.get_validators()) == 3
        finally:
            engine.close()

    def test_initialize_chain_empty_genesis(self, tmp_dir):
        """Chain can be initialized with empty validator set."""
        config = TestnetConfig(chain_id="empty-test")
        state = create_genesis(config, [])
        db_path = os.path.join(tmp_dir, "consensus.db")
        engine = initialize_chain(state, db_path=db_path)
        try:
            assert len(engine.get_validators()) == 0
            assert engine.chain_id == "empty-test"
        finally:
            engine.close()

    def test_initialize_uses_config_params(self, tmp_dir):
        """Engine uses params from genesis config."""
        config = TestnetConfig(
            chain_id="custom-params",
            blocks_per_epoch=5,
            unbonding_blocks=50,
        )
        v = ValidatorInfo(pubkey="val1pubkey" * 3, stake=1000 * OAS_DECIMALS, commission=1000)
        state = create_genesis(config, [v])
        db_path = os.path.join(tmp_dir, "consensus.db")
        engine = initialize_chain(state, db_path=db_path)
        try:
            assert engine.blocks_per_epoch == 5
            assert engine.unbonding_blocks == 50
        finally:
            engine.close()

    def test_genesis_hash_matches_engine(self, tmp_dir, testnet_config, sample_validators):
        """Engine's genesis hash matches the genesis state."""
        state = create_genesis(testnet_config, sample_validators)
        db_path = os.path.join(tmp_dir, "consensus.db")
        engine = initialize_chain(state, db_path=db_path)
        try:
            engine_hash = engine.get_genesis_hash()
            assert engine_hash == state.genesis_hash
        finally:
            engine.close()


# ── Multi-node init tests ────────────────────────────────────────────


class TestMultiNodeInit:
    def test_multi_node_genesis_consistency(self, tmp_dir, testnet_config, sample_validators):
        """Multiple nodes initialized from same genesis have same state."""
        state = create_genesis(testnet_config, sample_validators)

        engines = []
        for i in range(3):
            db_path = os.path.join(tmp_dir, f"node-{i}.db")
            engine = initialize_chain(state, db_path=db_path)
            engines.append(engine)

        try:
            # All nodes should have same genesis hash
            hashes = [e.get_genesis_hash() for e in engines]
            assert len(set(hashes)) == 1

            # All nodes should have same validator count
            counts = [len(e.get_validators()) for e in engines]
            assert all(c == 3 for c in counts)

            # All nodes should have same chain_id
            chain_ids = [e.chain_id for e in engines]
            assert all(cid == "oasyce-test-deploy" for cid in chain_ids)
        finally:
            for e in engines:
                e.close()

    def test_different_chain_id_prevents_cross_sync(self, tmp_dir, sample_validators):
        """Nodes with different chain_ids have different genesis hashes."""
        config_a = TestnetConfig(chain_id="chain-a", genesis_time=1000)
        config_b = TestnetConfig(chain_id="chain-b", genesis_time=1000)

        state_a = create_genesis(config_a, sample_validators)
        state_b = create_genesis(config_b, sample_validators)

        db_a = os.path.join(tmp_dir, "node-a.db")
        db_b = os.path.join(tmp_dir, "node-b.db")

        engine_a = initialize_chain(state_a, db_path=db_a)
        engine_b = initialize_chain(state_b, db_path=db_b)

        try:
            assert engine_a.get_genesis_hash() != engine_b.get_genesis_hash()
            assert engine_a.chain_id != engine_b.chain_id
        finally:
            engine_a.close()
            engine_b.close()


# ── Faucet with genesis tests ────────────────────────────────────────


class TestFaucetWithGenesis:
    def test_faucet_after_genesis(self, tmp_dir, testnet_config, sample_validators):
        """Faucet works after chain initialization."""
        from oasyce_plugin.services.faucet import Faucet

        state = create_genesis(testnet_config, sample_validators)
        db_path = os.path.join(tmp_dir, "consensus.db")
        engine = initialize_chain(state, db_path=db_path)

        faucet = Faucet(tmp_dir)
        result = faucet.claim("new-user")
        assert result["success"] is True
        assert result["amount"] == Faucet.TESTNET_DRIP

        engine.close()

    def test_faucet_rate_limit(self, tmp_dir):
        """Faucet enforces 24h cooldown."""
        from oasyce_plugin.services.faucet import Faucet
        from unittest.mock import patch
        import time as _time

        faucet = Faucet(tmp_dir)
        base = _time.time()

        with patch("oasyce_plugin.services.faucet.time") as mock_time:
            mock_time.time.return_value = base
            r1 = faucet.claim("user-a")
            assert r1["success"] is True

            mock_time.time.return_value = base + 3600  # 1 hour later
            r2 = faucet.claim("user-a")
            assert r2["success"] is False
            assert "Cooldown" in r2["error"]

            mock_time.time.return_value = base + 86401  # 24h + 1s later
            r3 = faucet.claim("user-a")
            assert r3["success"] is True

    def test_faucet_config_amount(self, testnet_config):
        """Testnet config faucet amount is reasonable."""
        assert testnet_config.faucet_amount == 10000 * OAS_DECIMALS
        assert testnet_config.faucet_cooldown == 86400  # 24 hours


# ── GenesisState serialization tests ─────────────────────────────────


class TestGenesisStateSerialization:
    def test_to_dict(self, testnet_config, sample_validators):
        """GenesisState.to_dict() includes all fields."""
        state = create_genesis(testnet_config, sample_validators)
        d = state.to_dict()
        assert "chain_id" in d
        assert "genesis_time" in d
        assert "genesis_hash" in d
        assert "genesis_block" in d
        assert "validators" in d
        assert "total_stake" in d
        assert "config" in d

    def test_from_dict_roundtrip(self, testnet_config, sample_validators):
        """GenesisState.from_dict roundtrip preserves data."""
        state = create_genesis(testnet_config, sample_validators)
        d = state.to_dict()
        restored = GenesisState.from_dict(d)
        assert restored.chain_id == state.chain_id
        assert restored.genesis_hash == state.genesis_hash
        assert restored.total_stake == state.total_stake

    def test_genesis_validator_serialization(self):
        """GenesisValidator serializes correctly."""
        gv = GenesisValidator(
            pubkey="test_key", stake=5000 * OAS_DECIMALS,
            commission=1500, moniker="my-validator"
        )
        d = gv.to_dict()
        assert d["pubkey"] == "test_key"
        assert d["stake"] == 5000 * OAS_DECIMALS
        assert d["commission"] == 1500
        assert d["moniker"] == "my-validator"

        restored = GenesisValidator.from_dict(d)
        assert restored.pubkey == gv.pubkey
        assert restored.stake == gv.stake


# ── Config validation edge cases ─────────────────────────────────────


class TestConfigEdgeCases:
    def test_single_validator(self):
        """Single validator testnet works."""
        v = ValidatorInfo(pubkey="solo_val_key" * 3, stake=100 * OAS_DECIMALS, commission=0)
        config = TestnetConfig(initial_validators=[v])
        state = create_genesis(config)
        errors = validate_genesis(state)
        assert errors == []
        assert state.total_stake == 100 * OAS_DECIMALS

    def test_max_commission_validator(self):
        """Validator with max commission (5000 bps = 50%) is valid."""
        v = ValidatorInfo(pubkey="max_comm_key" * 3, stake=100 * OAS_DECIMALS, commission=5000)
        config = TestnetConfig()
        state = create_genesis(config, [v])
        errors = validate_genesis(state)
        assert errors == []

    def test_config_immutable(self):
        """TestnetConfig is frozen."""
        cfg = TestnetConfig()
        with pytest.raises(AttributeError):
            cfg.chain_id = "modified"  # type: ignore

    def test_validator_info_immutable(self):
        """ValidatorInfo is frozen."""
        v = ValidatorInfo(pubkey="key", stake=100, commission=1000)
        with pytest.raises(AttributeError):
            v.stake = 200  # type: ignore
