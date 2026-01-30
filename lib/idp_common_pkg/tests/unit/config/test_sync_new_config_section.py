"""Test configuration sync when new sections are added to v0."""

from unittest.mock import Mock, patch

import pytest
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import IDPConfig


@pytest.mark.unit
def test_sync_called_when_v0_saved_with_new_section():
    """Test that sync is called when v0 is saved with new configuration sections."""
    # Mock DynamoDB table
    mock_table = Mock()
    mock_table.get_item.return_value = {"Item": None}
    mock_table.scan.return_value = {"Items": []}

    # Create new v0 config with extraction section
    new_v0_config = IDPConfig(
        notes="Updated config",
        classification={"model": "new-model"},
        extraction={"model": "new-extraction-model"},  # New section
    )

    config_manager = ConfigurationManager("test-table")
    config_manager.table = mock_table

    # Patch the sync method to track if it's called
    with patch.object(
        config_manager, "_sync_all_versions_with_new_baseline"
    ) as mock_sync:
        config_manager.save_configuration("Config", new_v0_config, "v0")

    # Verify sync was called with the new config
    mock_sync.assert_called_once_with(new_v0_config)

    # Verify the config passed to sync has the new extraction section
    sync_call_config = mock_sync.call_args[0][0]
    assert hasattr(sync_call_config, "extraction"), (
        "Synced config should have extraction section"
    )
    assert sync_call_config.extraction.model == "new-extraction-model", (
        "Should have new extraction model"
    )


@pytest.mark.unit
def test_sync_behavior_confirmed():
    """Test confirms the sync behavior we discovered in our investigation."""
    # This test documents the key findings from our conversation summary:
    # 1. Sync is called when v0 is saved (regardless of whether content changed)
    # 2. New sections in v0 would be propagated to other versions via sync
    # 3. The sync mechanism preserves user customizations while adding new baseline sections

    mock_table = Mock()
    config_manager = ConfigurationManager("test-table")
    config_manager.table = mock_table

    # Create v0 config with new extraction section
    v0_config = IDPConfig(
        notes="Baseline config",
        classification={"model": "baseline-model"},
        extraction={"model": "baseline-extraction"},  # New section that should sync
    )

    # Verify that sync method exists and would be called
    assert hasattr(config_manager, "_sync_all_versions_with_new_baseline"), (
        "Sync method should exist"
    )

    # Test that the sync method is called when saving v0
    with patch.object(
        config_manager, "_sync_all_versions_with_new_baseline"
    ) as mock_sync:
        mock_table.get_item.return_value = {"Item": None}
        config_manager.save_configuration("Config", v0_config, "v0")

        # Confirm sync is called - this validates our investigation findings
        mock_sync.assert_called_once()

        # The config passed to sync should have the new extraction section
        synced_config = mock_sync.call_args[0][0]
        assert hasattr(synced_config, "extraction"), (
            "New section should be in synced config"
        )
        assert synced_config.extraction.model == "baseline-extraction", (
            "New section should have correct value"
        )
