"""Tests for ProtocolParams — configurable economic parameters."""

import os
import pytest

from oasyce.core.protocol_params import (
    PARAM_BOUNDS,
    ParamValidationError,
    ProtocolParams,
    get_protocol_params,
    reset_params_cache,
)


class TestDefaults:
    def test_defaults_are_valid(self):
        p = ProtocolParams()
        p.validate()  # Should not raise

    def test_rates_sum_to_one(self):
        p = ProtocolParams()
        total = p.creator_rate + p.validator_rate + p.burn_rate + p.treasury_rate
        assert total == pytest.approx(1.0)

    def test_default_values(self):
        p = ProtocolParams()
        assert p.reserve_ratio == 0.50
        assert p.creator_rate == 0.93
        assert p.validator_rate == 0.03
        assert p.burn_rate == 0.02
        assert p.treasury_rate == 0.02

    def test_frozen(self):
        """ProtocolParams is immutable."""
        p = ProtocolParams()
        with pytest.raises(AttributeError):
            p.reserve_ratio = 0.99


class TestValidation:
    def test_rates_must_sum_to_one(self):
        p = ProtocolParams(creator_rate=0.50, validator_rate=0.07)
        with pytest.raises(ParamValidationError, match="sum to"):
            p.validate()

    def test_reserve_ratio_too_low(self):
        p = ProtocolParams(reserve_ratio=0.05)
        with pytest.raises(ParamValidationError, match="reserve_ratio"):
            p.validate()

    def test_reserve_ratio_too_high(self):
        p = ProtocolParams(reserve_ratio=1.5)
        with pytest.raises(ParamValidationError, match="reserve_ratio"):
            p.validate()

    def test_burn_rate_too_high(self):
        """Burn rate capped at 15% to prevent liquidity death."""
        p = ProtocolParams(
            creator_rate=0.59,
            validator_rate=0.01,
            burn_rate=0.30,
            treasury_rate=0.10,
        )
        with pytest.raises(ParamValidationError, match="burn_rate"):
            p.validate()

    def test_creator_rate_too_low(self):
        """Creator/reserve must be >= 50% for pool stability."""
        p = ProtocolParams(
            creator_rate=0.40,
            validator_rate=0.25,
            burn_rate=0.15,
            treasury_rate=0.20,
        )
        with pytest.raises(ParamValidationError):
            p.validate()

    def test_valid_custom_params(self):
        """Custom params within bounds should pass."""
        p = ProtocolParams(
            reserve_ratio=0.35,
            creator_rate=0.70,
            validator_rate=0.15,
            burn_rate=0.10,
            treasury_rate=0.05,
        )
        p.validate()  # Should not raise

    def test_solvency_cap_bounds(self):
        p = ProtocolParams(reserve_solvency_cap=0.3)
        with pytest.raises(ParamValidationError, match="reserve_solvency_cap"):
            p.validate()


class TestSerialization:
    def test_to_dict(self):
        p = ProtocolParams()
        d = p.to_dict()
        assert d["reserve_ratio"] == 0.50
        assert d["creator_rate"] == 0.93
        assert len(d) == 8  # all fields

    def test_from_dict_roundtrip(self):
        p1 = ProtocolParams()
        d = p1.to_dict()
        p2 = ProtocolParams.from_dict(d)
        assert p1 == p2

    def test_from_dict_ignores_unknown(self):
        d = ProtocolParams().to_dict()
        d["unknown_field"] = 42
        p = ProtocolParams.from_dict(d)  # Should not raise
        assert not hasattr(p, "unknown_field")

    def test_from_dict_validates(self):
        d = {"reserve_ratio": 0.01}  # below minimum
        with pytest.raises(ParamValidationError):
            ProtocolParams.from_dict(d)


class TestEnvOverride:
    def test_env_override(self, monkeypatch):
        reset_params_cache()
        monkeypatch.setenv("OASYCE_PARAM_RESERVE_RATIO", "0.45")
        p = get_protocol_params(force_reload=True)
        assert p.reserve_ratio == 0.45
        reset_params_cache()

    def test_env_override_rate(self, monkeypatch):
        """Override one rate — rest must still sum to 1.0 with defaults."""
        reset_params_cache()
        # 0.88 + 0.03 + 0.02 + 0.07 = 1.00
        monkeypatch.setenv("OASYCE_PARAM_CREATOR_RATE", "0.88")
        monkeypatch.setenv("OASYCE_PARAM_TREASURY_RATE", "0.07")
        p = get_protocol_params(force_reload=True)
        assert p.creator_rate == 0.88
        assert p.treasury_rate == 0.07
        reset_params_cache()

    def test_env_invalid_ignored(self, monkeypatch):
        reset_params_cache()
        monkeypatch.setenv("OASYCE_PARAM_RESERVE_RATIO", "not_a_number")
        p = get_protocol_params(force_reload=True)
        assert p.reserve_ratio == 0.50  # default
        reset_params_cache()

    def test_caching(self):
        reset_params_cache()
        p1 = get_protocol_params()
        p2 = get_protocol_params()
        assert p1 is p2  # Same object

    def test_force_reload(self):
        reset_params_cache()
        p1 = get_protocol_params()
        p2 = get_protocol_params(force_reload=True)
        assert p1 == p2
        assert p1 is not p2  # Different object


class TestBoundsCompleteness:
    def test_all_rate_fields_have_bounds(self):
        """Every rate field must have bounds defined."""
        rate_fields = {
            "creator_rate",
            "validator_rate",
            "burn_rate",
            "treasury_rate",
            "reserve_ratio",
        }
        for name in rate_fields:
            assert name in PARAM_BOUNDS, f"Missing bounds for {name}"
