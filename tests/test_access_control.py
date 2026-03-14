"""
Tests for the Data Security & Access Control subsystem.

Covers:
  - AccessLevel enum
  - ReputationEngine scoring
  - ExposureRegistry cumulative tracking & fragmentation detection
  - LiabilityWindow delayed release
  - DataAccessProvider access-level checks & bond calculation
"""
import time

import pytest

from oasyce_plugin.services.access import (
    AccessLevel,
    access_level_index,
    parse_max_access_level,
)
from oasyce_plugin.services.access.config import AccessControlConfig
from oasyce_plugin.services.access.provider import DataAccessProvider, AccessResult
from oasyce_plugin.services.reputation import ReputationEngine
from oasyce_plugin.services.exposure.registry import ExposureRegistry
from oasyce_plugin.services.exposure.window import LiabilityWindow


# ─── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def config():
    return AccessControlConfig()


@pytest.fixture
def reputation(config):
    return ReputationEngine(config=config)


@pytest.fixture
def exposure(config):
    return ExposureRegistry(config=config)


@pytest.fixture
def window(config):
    return LiabilityWindow(config=config)


@pytest.fixture
def provider(config, reputation, exposure):
    p = DataAccessProvider(config=config, reputation=reputation, exposure=exposure)
    p.register_asset("ASSET_001", value=1000.0, risk_level="public")
    p.register_asset("ASSET_002", value=500.0, risk_level="high", max_access_level="L1")
    return p


# ═══════════════════════════════════════════════════════════════════
#  AccessLevel Enum
# ═══════════════════════════════════════════════════════════════════

class TestAccessLevel:
    def test_enum_values(self):
        assert AccessLevel.L0_QUERY.value == "L0"
        assert AccessLevel.L1_SAMPLE.value == "L1"
        assert AccessLevel.L2_COMPUTE.value == "L2"
        assert AccessLevel.L3_DELIVER.value == "L3"

    def test_ordering(self):
        assert access_level_index(AccessLevel.L0_QUERY) == 0
        assert access_level_index(AccessLevel.L3_DELIVER) == 3
        assert access_level_index(AccessLevel.L1_SAMPLE) < access_level_index(AccessLevel.L2_COMPUTE)

    def test_parse_max_access_level(self):
        assert parse_max_access_level("L0") == AccessLevel.L0_QUERY
        assert parse_max_access_level("L3") == AccessLevel.L3_DELIVER
        with pytest.raises(ValueError):
            parse_max_access_level("L9")

    def test_string_enum(self):
        assert AccessLevel.L0_QUERY == "L0"
        assert isinstance(AccessLevel.L0_QUERY, str)


# ═══════════════════════════════════════════════════════════════════
#  ReputationEngine
# ═══════════════════════════════════════════════════════════════════

class TestReputationEngine:
    def test_initial_score(self, reputation):
        assert reputation.get_reputation("agent-1") == 10.0

    def test_success_increases_score(self, reputation):
        score = reputation.update("agent-1", success=True)
        assert score == 15.0  # 10 + 5

    def test_damage_decreases_score(self, reputation):
        # First boost the score so damage doesn't floor at 0
        reputation.update("agent-1", success=True)
        reputation.update("agent-1", success=True)
        score = reputation.update("agent-1", success=False)
        # 10 + 5 + 5 - 10 = 10
        assert score == 10.0

    def test_leak_penalty(self, reputation):
        # Boost first
        for _ in range(12):
            reputation.update("agent-1", success=True)
        # 10 + 60 = 70
        score = reputation.update("agent-1", leak_detected=True)
        # 70 - 50 = 20
        assert score == 20.0

    def test_score_floor_at_zero(self, reputation):
        score = reputation.update("agent-1", leak_detected=True)
        # 10 - 50 = -40, floored at 0
        assert score == 0.0

    def test_time_decay(self, reputation):
        # Boost to 70
        for _ in range(12):
            reputation.update("agent-1", success=True)
        # Apply 2 decay periods (180 days)
        score = reputation.update("agent-1", time_since_last=180.0)
        # 70 - 10 = 60  (but damage also applies since success=False → -10)
        # Actually: 70 + (-10 for damage) + (-10 for 2 periods) = 50
        # Wait — success=False and leak_detected=False → damage penalty applies
        assert score == 50.0

    def test_decay_floor(self, reputation):
        # Boost high
        for _ in range(20):
            reputation.update("agent-1", success=True)
        # 10 + 100 = 110 (uncapped)
        # Apply massive decay
        score = reputation.update("agent-1", time_since_last=900.0, success=True)
        # 110 + 5 (success) then 10 periods decay = -50
        # 115 - 50 = 65 → but floor is 50 → max(65, 50) = 65
        assert score >= 50.0

    def test_bond_discount(self, reputation):
        # Initial rep = 10 → discount = 1 - 10/100 = 0.9
        discount = reputation.get_bond_discount("agent-1")
        assert discount == 0.9

    def test_bond_discount_high_rep(self, reputation):
        for _ in range(18):
            reputation.update("agent-1", success=True)
        # 10 + 90 = 100
        discount = reputation.get_bond_discount("agent-1")
        assert discount == 0.0

    def test_multiple_agents_independent(self, reputation):
        reputation.update("agent-1", success=True)
        assert reputation.get_reputation("agent-1") == 15.0
        assert reputation.get_reputation("agent-2") == 10.0


# ═══════════════════════════════════════════════════════════════════
#  ExposureRegistry
# ═══════════════════════════════════════════════════════════════════

class TestExposureRegistry:
    def test_no_exposure(self, exposure):
        assert exposure.get_cumulative_exposure("agent-1", "ASSET_001") == 0.0
        assert exposure.get_exposure_factor("agent-1", "ASSET_001") == 1.0

    def test_single_access(self, exposure):
        exposure.track_access("agent-1", "ASSET_001", 100.0, "L0")
        assert exposure.get_cumulative_exposure("agent-1", "ASSET_001") == 100.0

    def test_cumulative_tracking(self, exposure):
        exposure.track_access("agent-1", "ASSET_001", 100.0, "L0")
        exposure.track_access("agent-1", "ASSET_001", 100.0, "L1")
        exposure.track_access("agent-1", "ASSET_001", 100.0, "L2")
        assert exposure.get_cumulative_exposure("agent-1", "ASSET_001") == 300.0

    def test_exposure_factor_grows(self, exposure):
        exposure.track_access("agent-1", "ASSET_001", 100.0, "L0")
        # factor = 1 + 100/100 = 2.0
        assert exposure.get_exposure_factor("agent-1", "ASSET_001") == 2.0

        exposure.track_access("agent-1", "ASSET_001", 100.0, "L1")
        # factor = 1 + 200/100 = 3.0
        assert exposure.get_exposure_factor("agent-1", "ASSET_001") == 3.0

    def test_agents_isolated(self, exposure):
        exposure.track_access("agent-1", "ASSET_001", 100.0, "L0")
        assert exposure.get_cumulative_exposure("agent-2", "ASSET_001") == 0.0

    def test_no_fragmentation_single_access(self, exposure):
        exposure.track_access("agent-1", "ASSET_001", 100.0, "L0")
        assert exposure.check_fragmentation_attack("agent-1", "ASSET_001") is False

    def test_fragmentation_detected(self, exposure):
        """Multiple small accesses summing to more than the largest single one."""
        exposure.track_access("agent-1", "ASSET_001", 50.0, "L0")
        exposure.track_access("agent-1", "ASSET_001", 50.0, "L0")
        exposure.track_access("agent-1", "ASSET_001", 50.0, "L0")
        # total=150 > max_single=50 → fragmentation detected
        assert exposure.check_fragmentation_attack("agent-1", "ASSET_001") is True

    def test_no_fragmentation_single_large(self, exposure):
        """One large access followed by a smaller one is not fragmentation
        when total <= 2 × max."""
        exposure.track_access("agent-1", "ASSET_001", 100.0, "L0")
        exposure.track_access("agent-1", "ASSET_001", 50.0, "L0")
        # total=150 > max_single=100 → fragmentation detected
        assert exposure.check_fragmentation_attack("agent-1", "ASSET_001") is True


# ═══════════════════════════════════════════════════════════════════
#  LiabilityWindow
# ═══════════════════════════════════════════════════════════════════

class TestLiabilityWindow:
    def test_lock_bond(self, window):
        record = window.lock_bond("agent-1", "ASSET_001", 500.0, "L0")
        assert record.amount == 500.0
        assert record.access_level == "L0"
        assert record.released is False

    def test_release_time(self, window, config):
        window.lock_bond("agent-1", "ASSET_001", 500.0, "L0")
        release_time = window.get_release_time("agent-1", "ASSET_001")
        assert release_time is not None
        # Should be approximately now + L0_window
        assert release_time > time.time()
        assert release_time <= time.time() + config.L0_window + 1

    def test_cannot_release_early(self, window):
        window.lock_bond("agent-1", "ASSET_001", 500.0, "L3")
        # L3 = 30 days, cannot release now
        assert window.release_bond("agent-1", "ASSET_001") is False

    def test_release_after_window(self, window):
        record = window.lock_bond("agent-1", "ASSET_001", 500.0, "L0")
        # Manually set release_after to the past
        record.release_after = time.time() - 1
        assert window.release_bond("agent-1", "ASSET_001") is True

    def test_double_release_fails(self, window):
        record = window.lock_bond("agent-1", "ASSET_001", 500.0, "L0")
        record.release_after = time.time() - 1
        window.release_bond("agent-1", "ASSET_001")
        assert window.release_bond("agent-1", "ASSET_001") is False

    def test_no_bond_release(self, window):
        assert window.release_bond("agent-1", "NONEXIST") is False

    def test_no_bond_release_time(self, window):
        assert window.get_release_time("agent-1", "NONEXIST") is None

    def test_window_duration_by_level(self, window, config):
        for level, expected in [
            ("L0", config.L0_window),
            ("L1", config.L1_window),
            ("L2", config.L2_window),
            ("L3", config.L3_window),
        ]:
            before = time.time()
            window.lock_bond("agent-1", f"ASSET_{level}", 100.0, level)
            release = window.get_release_time("agent-1", f"ASSET_{level}")
            assert abs(release - (before + expected)) < 2  # 2s tolerance

    def test_get_bond(self, window):
        window.lock_bond("agent-1", "ASSET_001", 500.0, "L2")
        bond = window.get_bond("agent-1", "ASSET_001")
        assert bond is not None
        assert bond.amount == 500.0
        assert bond.access_level == "L2"


# ═══════════════════════════════════════════════════════════════════
#  DataAccessProvider — Access Level Checks
# ═══════════════════════════════════════════════════════════════════

class TestDataAccessProviderAccess:
    def test_unknown_asset(self, provider):
        result = provider.query("agent-1", "NONEXIST")
        assert result.success is False
        assert "Unknown asset" in result.error

    def test_l0_allowed_for_sandbox(self, provider, reputation):
        """Sandbox agents (rep < 20) can access L0."""
        assert reputation.get_reputation("agent-1") < 20.0
        result = provider.query("agent-1", "ASSET_001")
        assert result.success is True
        assert result.access_level == "L0"

    def test_l1_denied_for_sandbox(self, provider, reputation):
        """Sandbox agents cannot access L1+."""
        assert reputation.get_reputation("agent-1") < 20.0
        result = provider.sample("agent-1", "ASSET_001")
        assert result.success is False

    def test_l1_allowed_after_reputation(self, provider, reputation):
        """After building reputation, L1 access is granted."""
        for _ in range(3):
            reputation.update("agent-1", success=True)
        # rep = 10 + 15 = 25 > 20 threshold
        result = provider.sample("agent-1", "ASSET_001")
        assert result.success is True

    def test_exceeds_max_access_level(self, provider, reputation):
        """ASSET_002 has max_access_level=L1, so L2 should fail."""
        for _ in range(5):
            reputation.update("agent-1", success=True)
        result = provider.compute("agent-1", "ASSET_002")
        assert result.success is False
        assert "exceeds" in result.error

    def test_deliver_requires_high_rep(self, provider, reputation):
        """L3 delivery requires non-sandbox reputation."""
        for _ in range(5):
            reputation.update("agent-1", success=True)
        result = provider.deliver("agent-1", "ASSET_001")
        assert result.success is True
        assert result.access_level == "L3"


# ═══════════════════════════════════════════════════════════════════
#  DataAccessProvider — Bond Calculation
# ═══════════════════════════════════════════════════════════════════

class TestBondCalculation:
    def test_l0_bond_public_new_agent(self, provider, reputation):
        """L0, public risk, new agent (rep=10), no prior exposure.

        Bond = 1000 × 1.0 × 1.0 × 0.9 × 1.0 = 900.0
        """
        result = provider.query("agent-1", "ASSET_001")
        assert result.success is True
        assert result.bond_required == 900.0

    def test_l3_bond_public(self, provider, reputation):
        """L3, public risk, rep boosted to 35.

        Bond = 1000 × 5.0 × 1.0 × (1 - 35/100) × 1.0 = 5000 × 0.65 = 3250
        """
        for _ in range(5):
            reputation.update("agent-1", success=True)
        # rep = 10 + 25 = 35
        result = provider.deliver("agent-1", "ASSET_001")
        assert result.success is True
        assert result.bond_required == 3250.0

    def test_high_risk_multiplier(self, provider, reputation):
        """ASSET_002 has risk=high (2.0×) and value=500.

        L0: Bond = 500 × 1.0 × 2.0 × 0.9 × 1.0 = 900.0
        """
        result = provider.query("agent-1", "ASSET_002")
        assert result.success is True
        assert result.bond_required == 900.0

    def test_exposure_increases_bond(self, provider, reputation):
        """Repeated access increases exposure factor → higher bond."""
        first = provider.query("agent-1", "ASSET_001")
        # After first access, exposure factor = 1 + 1000/1000 = 2.0
        second = provider.query("agent-1", "ASSET_001")
        assert second.bond_required > first.bond_required

    def test_bond_with_zero_rep(self, reputation, config, exposure):
        """Agent with rep=0 pays full bond (discount factor = 1.0)."""
        reputation.update("agent-1", leak_detected=True)  # rep → 0
        provider = DataAccessProvider(
            config=config, reputation=reputation, exposure=exposure
        )
        provider.register_asset("ASSET_X", value=100.0)
        # L0: 100 × 1.0 × 1.0 × 1.0 × 1.0 = 100
        result = provider.query("agent-1", "ASSET_X")
        assert result.success is True  # L0 allowed even in sandbox
        assert result.bond_required == 100.0


# ═══════════════════════════════════════════════════════════════════
#  Config Helpers
# ═══════════════════════════════════════════════════════════════════

class TestAccessControlConfig:
    def test_multiplier_for(self, config):
        assert config.multiplier_for("L0") == 1.0
        assert config.multiplier_for("L3") == 5.0

    def test_window_for(self, config):
        assert config.window_for("L0") == 86400
        assert config.window_for("L3") == 2592000

    def test_risk_factor_for(self, config):
        assert config.risk_factor_for("public") == 1.0
        assert config.risk_factor_for("critical") == 3.0
        assert config.risk_factor_for("unknown") == 1.0  # defaults to public

    def test_frozen(self, config):
        with pytest.raises(AttributeError):
            config.L0_multiplier = 99.0
