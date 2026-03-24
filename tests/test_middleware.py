"""Tests for API key auth and rate limiting middleware."""

import pytest

from oasyce.middleware import RateLimiter, _is_read_only


class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter(rate=5, window_seconds=60)
        for _ in range(5):
            assert rl.allow("ip1") is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(rate=3, window_seconds=60)
        for _ in range(3):
            assert rl.allow("ip1") is True
        assert rl.allow("ip1") is False

    def test_different_keys_independent(self):
        rl = RateLimiter(rate=2, window_seconds=60)
        assert rl.allow("ip1") is True
        assert rl.allow("ip1") is True
        assert rl.allow("ip1") is False
        # Different key should still work
        assert rl.allow("ip2") is True

    def test_remaining(self):
        rl = RateLimiter(rate=5, window_seconds=60)
        assert rl.remaining("ip1") == 5
        rl.allow("ip1")
        assert rl.remaining("ip1") == 4
        for _ in range(4):
            rl.allow("ip1")
        assert rl.remaining("ip1") == 0


class TestReadOnlyDetection:
    def test_get_is_read_only(self):
        assert _is_read_only("GET", "/anything") is True

    def test_post_health_is_read(self):
        assert _is_read_only("POST", "/health") is True

    def test_post_escrow_create_is_write(self):
        assert _is_read_only("POST", "/v1/escrow/create") is False

    def test_post_auction_is_write(self):
        assert _is_read_only("POST", "/market/v1/auction") is False

    def test_get_bonding_curve_is_read(self):
        assert _is_read_only("GET", "/v1/bonding_curve/ASSET_1") is True
