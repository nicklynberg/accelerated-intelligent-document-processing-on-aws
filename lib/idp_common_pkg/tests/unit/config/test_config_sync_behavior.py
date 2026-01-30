# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import IDPConfig


@pytest.mark.unit
class TestConfigSyncBehavior:
    """Test configuration sync behavior when v0 is updated"""

    @pytest.fixture
    def mock_table(self):
        """Mock DynamoDB table"""
        table = Mock()
        table.get_item.return_value = {"Item": None}
        table.put_item.return_value = {}
        table.scan.return_value = {"Items": []}
        table.update_item.return_value = {}
        return table

    @pytest.fixture
    def config_manager(self, mock_table):
        """ConfigurationManager with mocked table"""
        with patch("boto3.resource") as mock_resource:
            mock_dynamodb = Mock()
            mock_dynamodb.Table.return_value = mock_table
            mock_resource.return_value = mock_dynamodb

            manager = ConfigurationManager("test-table")
            manager.table = mock_table
            return manager

    def test_sync_method_called_when_v0_saved(self, config_manager, mock_table):
        """Test that _sync_all_versions_with_new_baseline is called when v0 is saved"""

        # Create a simple v0 config
        v0_config = IDPConfig(
            classification={"model": "test-model"},
            classes=[{"name": "test", "description": "test"}],
        )

        # Mock that v0 doesn't exist yet (new save)
        mock_table.get_item.return_value = {"Item": None}

        # Patch the sync method to track if it's called
        with patch.object(
            config_manager, "_sync_all_versions_with_new_baseline"
        ) as mock_sync:
            # Save v0 - this should call the sync method
            config_manager.save_configuration("Config", v0_config, version="v0")

            # Verify sync was called with the v0 config
            mock_sync.assert_called_once_with(v0_config)
            print("✓ Sync method was called when v0 was saved")

    def test_sync_method_not_called_when_v1_saved(self, config_manager, mock_table):
        """Test that sync is NOT called when non-v0 versions are saved"""

        v1_config = IDPConfig(
            classification={"model": "test-model"},
            classes=[{"name": "test", "description": "test"}],
        )

        mock_table.get_item.return_value = {"Item": None}

        with patch.object(
            config_manager, "_sync_all_versions_with_new_baseline"
        ) as mock_sync:
            # Save v1 - this should NOT call sync
            config_manager.save_configuration("Config", v1_config, version="v1")

            # Verify sync was NOT called
            mock_sync.assert_not_called()
            print("✓ Sync method was NOT called when v1 was saved")

    def test_sync_method_not_called_when_skip_sync_true(
        self, config_manager, mock_table
    ):
        """Test that sync is NOT called when skip_sync=True"""

        v0_config = IDPConfig(
            classification={"model": "test-model"},
            classes=[{"name": "test", "description": "test"}],
        )

        mock_table.get_item.return_value = {"Item": None}

        with patch.object(
            config_manager, "_sync_all_versions_with_new_baseline"
        ) as mock_sync:
            # Save v0 with skip_sync=True - should NOT call sync
            config_manager.save_configuration(
                "Config", v0_config, version="v0", skip_sync=True
            )

            # Verify sync was NOT called
            mock_sync.assert_not_called()
            print("✓ Sync method was NOT called when skip_sync=True")

    def test_lambda_style_save_triggers_sync(self, config_manager, mock_table):
        """Test that saving v0 like the Lambda does still triggers sync"""

        v0_config = IDPConfig(
            classification={"model": "test-model"},
            classes=[{"name": "test", "description": "test"}],
        )

        mock_table.get_item.return_value = {"Item": None}

        with patch.object(
            config_manager, "_sync_all_versions_with_new_baseline"
        ) as mock_sync:
            # Save v0 exactly like the Lambda does (with metadata)
            current_time = datetime.utcnow().isoformat() + "Z"
            metadata = {"updated_at": current_time}

            config_manager.save_configuration(
                "Config",
                v0_config,
                version="v0",
                description="System default configuration (v0)",
                metadata=metadata,
            )

            # Verify sync was still called despite metadata
            mock_sync.assert_called_once_with(v0_config)
            print("✓ Sync method was called even with Lambda-style metadata")
