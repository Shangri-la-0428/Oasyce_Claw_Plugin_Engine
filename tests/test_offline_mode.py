"""
Tests for offline mode: detector, cache, degradation manager, CLI commands.

Covers:
  - OfflineDetector: status transitions, hysteresis, callbacks
  - ProviderCache: CRUD, TTL expiry, batch ops, purge
  - OfflineModeManager: feature tiers, command checks, summaries
  - CLI: status and cache commands
"""

import json
import os
import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest

from oasyce_plugin.consensus.network.offline_detector import (
    OfflineDetector,
    DEGRADED_THRESHOLD,
    OFFLINE_THRESHOLD,
    RECOVERY_THRESHOLD,
)
from oasyce_plugin.consensus.provider_cache import ProviderCache
from oasyce_plugin.consensus.offline_mode import (
    OfflineModeManager,
    CRITICAL,
    DEGRADED,
    UNAVAILABLE,
    COMMAND_FEATURE_MAP,
)


# ═══════════════════════════════════════════════════════════════════
# OfflineDetector tests
# ═══════════════════════════════════════════════════════════════════


class TestOfflineDetector:
    """Tests for network connectivity detection."""

    def test_initial_state_is_online(self):
        d = OfflineDetector()
        assert d.get_status() == "online"
        assert d.is_online is True

    def test_check_connectivity_success(self):
        d = OfflineDetector()
        with patch.object(d, "_probe_tcp", return_value=True):
            result = d.check_connectivity()
        assert result is True
        assert d.get_status() == "online"

    def test_single_failure_stays_online(self):
        d = OfflineDetector()
        with patch.object(d, "_probe_tcp", return_value=False):
            d.check_connectivity()
        assert d.get_status() == "online"
        assert d.consecutive_failures == 1

    def test_degraded_after_threshold(self):
        d = OfflineDetector()
        with patch.object(d, "_probe_tcp", return_value=False):
            for _ in range(DEGRADED_THRESHOLD):
                d.check_connectivity()
        assert d.get_status() == "degraded"

    def test_offline_after_threshold(self):
        d = OfflineDetector()
        with patch.object(d, "_probe_tcp", return_value=False):
            for _ in range(OFFLINE_THRESHOLD):
                d.check_connectivity()
        assert d.get_status() == "offline"

    def test_recovery_from_offline_to_degraded(self):
        d = OfflineDetector()
        d.force_status("offline")
        with patch.object(d, "_probe_tcp", return_value=True):
            d.check_connectivity()
        assert d.get_status() == "degraded"

    def test_recovery_from_degraded_to_online(self):
        d = OfflineDetector()
        d.force_status("degraded")
        with patch.object(d, "_probe_tcp", return_value=True):
            for _ in range(RECOVERY_THRESHOLD):
                d.check_connectivity()
        assert d.get_status() == "online"

    def test_full_recovery_cycle(self):
        """offline → degraded → online via consecutive successes."""
        d = OfflineDetector()
        d.force_status("offline")
        with patch.object(d, "_probe_tcp", return_value=True):
            d.check_connectivity()  # offline → degraded
            assert d.get_status() == "degraded"
            for _ in range(RECOVERY_THRESHOLD):
                d.check_connectivity()
            assert d.get_status() == "online"

    def test_callback_fired_on_transition(self):
        d = OfflineDetector()
        transitions = []
        d.on_status_change(lambda old, new: transitions.append((old, new)))

        with patch.object(d, "_probe_tcp", return_value=False):
            for _ in range(DEGRADED_THRESHOLD):
                d.check_connectivity()

        assert ("online", "degraded") in transitions

    def test_callback_not_fired_without_transition(self):
        d = OfflineDetector()
        transitions = []
        d.on_status_change(lambda old, new: transitions.append((old, new)))

        with patch.object(d, "_probe_tcp", return_value=True):
            d.check_connectivity()
            d.check_connectivity()

        assert len(transitions) == 0

    def test_callback_exception_does_not_crash(self):
        d = OfflineDetector()
        d.on_status_change(lambda old, new: 1 / 0)  # raises ZeroDivisionError
        d.force_status("degraded")  # should not raise

    def test_force_status_valid(self):
        d = OfflineDetector()
        for s in ("online", "degraded", "offline"):
            d.force_status(s)
            assert d.get_status() == s

    def test_force_status_invalid(self):
        d = OfflineDetector()
        with pytest.raises(ValueError):
            d.force_status("unknown")

    def test_get_info(self):
        d = OfflineDetector(check_interval=60, bootstrap_host="node.example.com")
        info = d.get_info()
        assert info["status"] == "online"
        assert info["check_interval"] == 60
        assert info["bootstrap_host"] == "node.example.com"
        assert info["consecutive_failures"] == 0

    def test_consecutive_counters_reset(self):
        """Success resets failure count and vice versa."""
        d = OfflineDetector()
        with patch.object(d, "_probe_tcp", return_value=False):
            d.check_connectivity()
        assert d.consecutive_failures == 1

        with patch.object(d, "_probe_tcp", return_value=True):
            d.check_connectivity()
        assert d.consecutive_failures == 0
        assert d.consecutive_successes == 1

        with patch.object(d, "_probe_tcp", return_value=False):
            d.check_connectivity()
        assert d.consecutive_successes == 0

    def test_last_check_updated(self):
        d = OfflineDetector()
        assert d.last_check == 0
        with patch.object(d, "_probe_tcp", return_value=True):
            d.check_connectivity()
        assert d.last_check > 0

    def test_probe_tcp_failure(self):
        """_probe_tcp returns False when connection fails."""
        d = OfflineDetector(timeout=0.1)
        import socket
        with patch("socket.socket") as mock_sock:
            mock_sock.return_value.connect.side_effect = socket.timeout("timed out")
            result = d._probe_tcp("192.0.2.1", 1)
        assert result is False

    def test_flapping_resistance(self):
        """Alternating success/failure should not cause rapid state changes."""
        d = OfflineDetector()
        with patch.object(d, "_probe_tcp", return_value=False):
            d.check_connectivity()
        with patch.object(d, "_probe_tcp", return_value=True):
            d.check_connectivity()
        with patch.object(d, "_probe_tcp", return_value=False):
            d.check_connectivity()
        # Never left online because failures never hit threshold consecutively
        assert d.get_status() == "online"


# ═══════════════════════════════════════════════════════════════════
# ProviderCache tests
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def cache(tmp_path):
    db = os.path.join(str(tmp_path), "test_cache.db")
    c = ProviderCache(db_path=db, default_ttl=60)
    yield c
    c.close()


class TestProviderCache:
    """Tests for SQLite provider cache."""

    def test_cache_and_retrieve(self, cache):
        cache.cache_provider("p1", {"name": "Provider One", "url": "http://p1"})
        result = cache.get_cached_provider("p1")
        assert result is not None
        assert result["name"] == "Provider One"

    def test_get_missing_returns_none(self, cache):
        assert cache.get_cached_provider("nonexistent") is None

    def test_ttl_expiry(self, cache):
        cache.cache_provider("p1", {"name": "P1"}, ttl=1)
        # Immediately should be available
        assert cache.get_cached_provider("p1") is not None
        # After TTL expires
        time.sleep(1.1)
        assert cache.get_cached_provider("p1") is None

    def test_ttl_expiry_ignore(self, cache):
        cache.cache_provider("p1", {"name": "P1"}, ttl=1)
        time.sleep(1.1)
        result = cache.get_cached_provider("p1", ignore_ttl=True)
        assert result is not None
        assert result["_expired"] is True

    def test_update_existing(self, cache):
        cache.cache_provider("p1", {"name": "Old"})
        cache.cache_provider("p1", {"name": "New"})
        result = cache.get_cached_provider("p1")
        assert result["name"] == "New"

    def test_get_all_cached(self, cache):
        cache.cache_provider("p1", {"name": "P1"})
        cache.cache_provider("p2", {"name": "P2"})
        results = cache.get_all_cached()
        assert len(results) == 2

    def test_get_all_excludes_expired(self, cache):
        cache.cache_provider("p1", {"name": "P1"}, ttl=1)
        cache.cache_provider("p2", {"name": "P2"}, ttl=3600)
        time.sleep(1.1)
        results = cache.get_all_cached(include_expired=False)
        assert len(results) == 1
        assert results[0]["name"] == "P2"

    def test_get_all_includes_expired(self, cache):
        cache.cache_provider("p1", {"name": "P1"}, ttl=1)
        cache.cache_provider("p2", {"name": "P2"}, ttl=3600)
        time.sleep(1.1)
        results = cache.get_all_cached(include_expired=True)
        assert len(results) == 2

    def test_remove_provider(self, cache):
        cache.cache_provider("p1", {"name": "P1"})
        cache.remove_provider("p1")
        assert cache.get_cached_provider("p1") is None

    def test_clear(self, cache):
        cache.cache_provider("p1", {"name": "P1"})
        cache.cache_provider("p2", {"name": "P2"})
        cache.clear()
        assert cache.get_all_cached() == []

    def test_purge_expired(self, cache):
        cache.cache_provider("p1", {"name": "P1"}, ttl=1)
        cache.cache_provider("p2", {"name": "P2"}, ttl=3600)
        time.sleep(1.1)
        removed = cache.purge_expired()
        assert removed == 1
        assert len(cache.get_all_cached()) == 1

    def test_stats(self, cache):
        cache.cache_provider("p1", {"name": "P1"}, ttl=1)
        cache.cache_provider("p2", {"name": "P2"}, ttl=3600)
        time.sleep(1.1)
        stats = cache.stats()
        assert stats["total"] == 2
        assert stats["active"] == 1
        assert stats["expired"] == 1

    def test_cache_many(self, cache):
        providers = [
            {"provider_id": "p1", "name": "P1"},
            {"provider_id": "p2", "name": "P2"},
            {"provider_id": "p3", "name": "P3"},
        ]
        cache.cache_many(providers)
        assert len(cache.get_all_cached()) == 3

    def test_cached_at_metadata(self, cache):
        cache.cache_provider("p1", {"name": "P1"})
        result = cache.get_cached_provider("p1")
        assert "_cached_at" in result
        assert "_expired" in result
        assert result["_expired"] is False

    def test_empty_cache_stats(self, cache):
        stats = cache.stats()
        assert stats["total"] == 0
        assert stats["active"] == 0
        assert stats["expired"] == 0


# ═══════════════════════════════════════════════════════════════════
# OfflineModeManager tests
# ═══════════════════════════════════════════════════════════════════


class TestOfflineModeManager:
    """Tests for graceful degradation strategy."""

    def _make_manager(self, status="online", tmp_path=None):
        detector = OfflineDetector()
        detector.force_status(status)
        cache = None
        if tmp_path:
            db = os.path.join(str(tmp_path), "test_cache.db")
            cache = ProviderCache(db_path=db)
        return OfflineModeManager(detector=detector, cache=cache)

    def test_online_all_features_available(self):
        m = self._make_manager("online")
        available = m.get_available_features()
        all_features = CRITICAL + DEGRADED + UNAVAILABLE
        assert set(available) == set(all_features)

    def test_degraded_no_unavailable_features(self):
        m = self._make_manager("degraded")
        available = m.get_available_features()
        assert set(CRITICAL).issubset(set(available))
        assert set(DEGRADED).issubset(set(available))
        for f in UNAVAILABLE:
            assert f not in available

    def test_offline_only_critical(self):
        m = self._make_manager("offline")
        available = m.get_available_features()
        assert set(available) == set(CRITICAL)

    def test_unavailable_features_online(self):
        m = self._make_manager("online")
        assert m.get_unavailable_features() == []

    def test_unavailable_features_offline(self):
        m = self._make_manager("offline")
        unavailable = m.get_unavailable_features()
        assert set(DEGRADED + UNAVAILABLE).issubset(set(unavailable))

    def test_is_feature_available(self):
        m = self._make_manager("offline")
        assert m.is_feature_available("view_own_assets") is True
        assert m.is_feature_available("register_asset") is False

    def test_feature_tier(self):
        m = self._make_manager("online")
        assert m.get_feature_tier("view_own_assets") == "critical"
        assert m.get_feature_tier("browse_network") == "degraded"
        assert m.get_feature_tier("register_asset") == "unavailable"
        assert m.get_feature_tier("nonexistent") == "unknown"

    def test_unavailable_reason_online(self):
        m = self._make_manager("online")
        assert m.get_unavailable_reason("register_asset") == ""

    def test_unavailable_reason_offline_unavailable_tier(self):
        m = self._make_manager("offline")
        reason = m.get_unavailable_reason("register_asset")
        assert "requires network" in reason.lower() or "offline" in reason.lower()

    def test_unavailable_reason_degraded_mode(self):
        m = self._make_manager("degraded")
        reason = m.get_unavailable_reason("register_asset")
        assert "degraded" in reason.lower() or "network" in reason.lower()

    def test_unavailable_reason_critical_always_empty(self):
        for status in ("online", "degraded", "offline"):
            m = self._make_manager(status)
            assert m.get_unavailable_reason("view_own_assets") == ""

    def test_check_command_online(self):
        m = self._make_manager("online")
        allowed, msg = m.check_command("register")
        assert allowed is True
        assert msg == ""

    def test_check_command_offline_blocked(self):
        m = self._make_manager("offline")
        allowed, msg = m.check_command("register")
        assert allowed is False
        assert msg != ""

    def test_check_command_offline_critical_allowed(self):
        m = self._make_manager("offline")
        allowed, msg = m.check_command("balance")
        assert allowed is True

    def test_check_command_degraded_cached(self):
        m = self._make_manager("degraded")
        allowed, msg = m.check_command("search")
        assert allowed is True
        assert "cached" in msg.lower() or "degraded" in msg.lower()

    def test_check_command_unknown_allowed(self):
        m = self._make_manager("offline")
        allowed, msg = m.check_command("some_unknown_command")
        assert allowed is True

    def test_summary_online(self):
        m = self._make_manager("online")
        s = m.summary()
        assert s["connectivity"] == "online"
        assert s["unavailable_count"] == 0

    def test_summary_offline(self):
        m = self._make_manager("offline")
        s = m.summary()
        assert s["connectivity"] == "offline"
        assert s["unavailable_count"] > 0

    def test_summary_with_cache(self, tmp_path):
        m = self._make_manager("online", tmp_path=tmp_path)
        s = m.summary()
        assert s["cache"] is not None
        assert "total" in s["cache"]
        m.cache.close()

    def test_degraded_reason_with_cache(self, tmp_path):
        """Offline + cache → reason mentions cached data."""
        m = self._make_manager("offline", tmp_path=tmp_path)
        m.cache.cache_provider("p1", {"provider_id": "p1", "name": "P1"})
        reason = m.get_unavailable_reason("browse_network")
        assert "cached" in reason.lower() or "cache" in reason.lower()
        m.cache.close()

    def test_degraded_reason_no_cache(self):
        """Offline + no cache → reason says no cached data."""
        m = self._make_manager("offline")
        reason = m.get_unavailable_reason("browse_network")
        assert "no cached data" in reason.lower() or "unavailable" in reason.lower()

    def test_command_feature_map_completeness(self):
        """All mapped features should exist in one of the tiers."""
        all_features = set(CRITICAL + DEGRADED + UNAVAILABLE)
        for cmd, feature in COMMAND_FEATURE_MAP.items():
            assert feature in all_features, f"Command '{cmd}' maps to unknown feature '{feature}'"
