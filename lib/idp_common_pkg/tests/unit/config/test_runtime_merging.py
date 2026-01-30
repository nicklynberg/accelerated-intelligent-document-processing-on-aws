"""Test runtime merging of versioned configurations with v0 baseline."""

from unittest.mock import Mock

import pytest
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import ConfigurationRecord, IDPConfig


@pytest.mark.unit
def test_get_configuration_calls_merge_for_non_v0():
    """Test that get_configuration calls merge method for non-v0 versions."""
    mock_table = Mock()
    config_manager = ConfigurationManager("test-table")
    config_manager.table = mock_table

    # Mock the merge method to track if it's called
    merge_called = []

    def mock_merge(version):
        merge_called.append(version)
        return IDPConfig(notes=f"merged-{version}")

    config_manager._get_merged_version_config = mock_merge

    # Get v1 configuration - should call merge
    result = config_manager.get_configuration("Config", "v1")

    # Verify merge was called
    assert len(merge_called) == 1
    assert merge_called[0] == "v1"
    assert result.notes == "merged-v1"


@pytest.mark.unit
def test_get_configuration_v0_no_merge():
    """Test that get_configuration doesn't merge for v0."""
    mock_table = Mock()
    config_manager = ConfigurationManager("test-table")
    config_manager.table = mock_table

    # Create v0 config
    v0_config = IDPConfig(notes="v0 direct")

    # Mock _read_record
    def mock_read_record(config_type, version):
        if config_type == "Config" and version == "v0":
            return ConfigurationRecord(
                configuration_type="Config",
                version="v0",
                config=v0_config,
                is_active=True,
            )
        return None

    config_manager._read_record = mock_read_record

    # Mock merge method to ensure it's not called
    merge_called = []

    def mock_merge(version):
        merge_called.append(version)
        return IDPConfig(notes=f"merged-{version}")

    config_manager._get_merged_version_config = mock_merge

    # Get v0 configuration - should NOT call merge
    result = config_manager.get_configuration("Config", "v0")

    # Verify merge was NOT called and v0 returned directly
    assert len(merge_called) == 0
    assert result.notes == "v0 direct"


@pytest.mark.unit
def test_merge_version_config_combines_v0_and_version():
    """Test that _get_merged_version_config properly merges v0 + version."""
    mock_table = Mock()
    config_manager = ConfigurationManager("test-table")
    config_manager.table = mock_table

    # Create v0 baseline
    v0_config = IDPConfig(notes="v0 baseline", classification={"model": "v0-model"})

    # Create v1 with different notes
    v1_config = IDPConfig(notes="v1 customized", classification={"model": "v1-model"})

    # Mock _read_record
    def mock_read_record(config_type, version):
        if config_type == "Config" and version == "v0":
            return ConfigurationRecord(
                configuration_type="Config",
                version="v0",
                config=v0_config,
                is_active=False,
            )
        elif config_type == "Config" and version == "v1":
            return ConfigurationRecord(
                configuration_type="Config",
                version="v1",
                config=v1_config,
                is_active=True,
            )
        return None

    config_manager._read_record = mock_read_record

    # Test the merge method directly
    result = config_manager._get_merged_version_config("v1")

    # Verify merging worked - v1 customizations should override v0
    assert result is not None
    assert result.notes == "v1 customized"  # v1 override
    assert result.classification.model == "v1-model"  # v1 override
