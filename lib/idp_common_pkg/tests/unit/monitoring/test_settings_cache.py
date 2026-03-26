# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for idp_common.monitoring.settings_cache
"""

import json
import threading
from unittest.mock import MagicMock

from idp_common.monitoring.settings_cache import SettingsCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ssm_response(settings: dict) -> dict:
    """Build a mock SSM get_parameter response."""
    return {"Parameter": {"Value": json.dumps(settings)}}


def _make_mock_ssm(settings: dict) -> MagicMock:
    """Return a mock SSM client that returns *settings* from get_parameter."""
    mock = MagicMock()
    mock.get_parameter.return_value = _make_ssm_response(settings)
    return mock


# ---------------------------------------------------------------------------
# Basic cache behaviour
# ---------------------------------------------------------------------------


class TestSettingsCache:
    def test_get_returns_value_on_first_call(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"TrackingTableName": "my-table"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        result = cache.get("TrackingTableName")

        assert result == "my-table"
        ssm.get_parameter.assert_called_once_with(Name="/my/param")

    def test_get_returns_cached_value_on_second_call(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"Key": "value"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        # Two calls
        cache.get("Key")
        cache.get("Key")

        # SSM should only be called once
        assert ssm.get_parameter.call_count == 1

    def test_get_returns_default_for_missing_key(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        result = cache.get("NonExistentKey", default="fallback")
        assert result == "fallback"

    def test_cache_expires_after_ttl_and_refetches(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"Key": "v1"})
        cache = SettingsCache(ttl_seconds=0, ssm_client=ssm)  # TTL = 0 → always expired

        cache.get("Key")
        cache.get("Key")

        # With TTL=0, every call should refresh
        assert ssm.get_parameter.call_count == 2

    def test_invalidate_forces_refresh(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"Key": "v1"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        cache.get("Key")  # loads cache
        cache.invalidate()  # marks cache as expired
        cache.get("Key")  # should reload

        assert ssm.get_parameter.call_count == 2

    def test_get_all_returns_copy_of_settings(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        settings = {"A": "1", "B": "2"}
        ssm = _make_mock_ssm(settings)
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        result = cache.get_all()
        assert result == settings
        # Modifying the result should not affect the cache
        result["A"] = "mutated"
        assert cache.get("A") == "1"


# ---------------------------------------------------------------------------
# CloudWatch log groups helper
# ---------------------------------------------------------------------------


class TestGetCloudWatchLogGroups:
    def test_returns_list_from_comma_separated_string(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/p")
        ssm = _make_mock_ssm(
            {"CloudWatchLogGroups": "/aws/lambda/fn1,/aws/lambda/fn2, /aws/lambda/fn3 "}
        )
        cache = SettingsCache(ssm_client=ssm)
        groups = cache.get_cloudwatch_log_groups()
        assert groups == ["/aws/lambda/fn1", "/aws/lambda/fn2", "/aws/lambda/fn3"]

    def test_returns_empty_list_when_key_missing(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/p")
        ssm = _make_mock_ssm({})
        cache = SettingsCache(ssm_client=ssm)
        assert cache.get_cloudwatch_log_groups() == []

    def test_returns_empty_list_when_value_is_empty_string(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/p")
        ssm = _make_mock_ssm({"CloudWatchLogGroups": ""})
        cache = SettingsCache(ssm_client=ssm)
        assert cache.get_cloudwatch_log_groups() == []


# ---------------------------------------------------------------------------
# Missing SETTINGS_PARAMETER_NAME env var
# ---------------------------------------------------------------------------


class TestMissingEnvVar:
    def test_get_returns_default_when_param_name_not_set(self, monkeypatch):
        monkeypatch.delenv("SETTINGS_PARAMETER_NAME", raising=False)
        ssm = MagicMock()
        cache = SettingsCache(ssm_client=ssm)

        result = cache.get("AnyKey", default="my-default")

        # SSM should NOT be called
        ssm.get_parameter.assert_not_called()
        assert result == "my-default"


# ---------------------------------------------------------------------------
# SSM failure resilience
# ---------------------------------------------------------------------------


class TestSSMFailureResilience:
    def test_ssm_exception_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("SSM unavailable")
        cache = SettingsCache(ssm_client=ssm)

        # Should not raise — returns default
        result = cache.get("Key", default="safe")
        assert result == "safe"

    def test_ssm_failure_does_not_tight_retry(self, monkeypatch):
        """After a failed refresh the cache_time is still advanced to avoid hammering SSM."""
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("SSM unavailable")
        cache = SettingsCache(ttl_seconds=60, ssm_client=ssm)

        cache.get("Key")
        cache.get("Key")  # Second call within TTL — should not retry

        # Only one SSM call should have been made within the TTL window
        assert ssm.get_parameter.call_count == 1


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_reads_all_succeed(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"SharedKey": "thread-safe-value"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        results = []
        errors = []

        def read():
            try:
                results.append(cache.get("SharedKey"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors in concurrent reads: {errors}"
        assert all(r == "thread-safe-value" for r in results)
        # Cache should only be loaded once despite 20 concurrent reads
        assert ssm.get_parameter.call_count == 1
