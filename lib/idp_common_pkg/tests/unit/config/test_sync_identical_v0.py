# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from unittest.mock import Mock, patch

import pytest
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import IDPConfig


@pytest.mark.unit
class TestSyncWithIdenticalV0:
    """Test sync behavior when new v0 is identical to old v0"""

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

    def test_sync_with_identical_v0_content(self, config_manager, mock_table):
        """Test what happens when new v0 is identical to old v0"""

        # Create identical v0 configs
        identical_config = IDPConfig(
            classification={"model": "same-model"},
            classes=[{"name": "same", "description": "same class"}],
        )

        old_v0 = identical_config
        new_v0 = identical_config  # Exactly the same

        # Create v1 with user customizations
        v1_config = IDPConfig(
            classification={"model": "same-model"},  # Same as v0
            extraction={"model": "custom-extraction"},  # User customization
            classes=[{"name": "same", "description": "same class"}],
        )

        # Mock get_configuration calls
        def mock_get_config(config_type, version=None):
            if config_type == "Config" and version == "v0":
                return old_v0  # Return old v0 (identical to new)
            elif config_type == "Config" and version == "v1":
                return v1_config  # Return v1 to be synced
            return None

        # Mock scan to return v1
        mock_table.scan.return_value = {
            "Items": [{"Configuration": "Config#v1", "Version": "v1"}]
        }

        # Track save_configuration calls
        save_calls = []

        def track_save(*args, **kwargs):
            save_calls.append((args, kwargs))
            return None

        with patch.object(
            config_manager, "get_configuration", side_effect=mock_get_config
        ):
            with patch.object(
                config_manager, "save_configuration", side_effect=track_save
            ):
                # Call sync with identical v0
                config_manager._sync_all_versions_with_new_baseline(new_v0)

        print(f"Save calls when v0 is identical: {len(save_calls)}")

        if save_calls:
            for i, (args, kwargs) in enumerate(save_calls):
                print(
                    f"  Call {i}: version={kwargs.get('version')}, skip_sync={kwargs.get('skip_sync')}"
                )

            # Check if v1 was still synced
            v1_synced = any(
                kwargs.get("version") == "v1" for args, kwargs in save_calls
            )
            print(f"v1 was synced: {v1_synced}")

            if v1_synced:
                print(
                    "✓ Even with identical v0, v1 is still synced (timestamps updated)"
                )
            else:
                print("✗ v1 was not synced")
        else:
            print("✗ No save calls made - sync was skipped")

    def test_sync_with_no_user_customizations(self, config_manager, mock_table):
        """Test sync when v1 has no customizations (identical to old v0)"""

        # Create configs where v1 is identical to old v0
        base_config = IDPConfig(
            classification={"model": "base-model"},
            classes=[{"name": "base", "description": "base class"}],
        )

        old_v0 = base_config
        new_v0 = IDPConfig(
            classification={"model": "new-model"},  # Changed
            classes=[{"name": "base", "description": "base class"}],
        )
        v1_config = base_config  # Identical to old v0 (no customizations)

        def mock_get_config(config_type, version=None):
            if config_type == "Config" and version == "v0":
                return old_v0
            elif config_type == "Config" and version == "v1":
                return v1_config
            return None

        mock_table.scan.return_value = {
            "Items": [{"Configuration": "Config#v1", "Version": "v1"}]
        }

        save_calls = []

        def track_save(*args, **kwargs):
            save_calls.append((args, kwargs))
            return None

        with patch.object(
            config_manager, "get_configuration", side_effect=mock_get_config
        ):
            with patch.object(
                config_manager, "save_configuration", side_effect=track_save
            ):
                config_manager._sync_all_versions_with_new_baseline(new_v0)

        print(f"Save calls when v1 has no customizations: {len(save_calls)}")

        if save_calls:
            v1_synced = any(
                kwargs.get("version") == "v1" for args, kwargs in save_calls
            )
            print(f"v1 was synced: {v1_synced}")

            if v1_synced:
                # Check what the synced config looks like
                v1_call = next(
                    (args, kwargs)
                    for args, kwargs in save_calls
                    if kwargs.get("version") == "v1"
                )
                synced_config = v1_call[0][1]  # The config object
                print(
                    f"Synced v1 classification model: {synced_config.classification.model}"
                )

                if synced_config.classification.model == "new-model":
                    print(
                        "✓ v1 was updated to match new v0 (no user customizations to preserve)"
                    )
                else:
                    print("✗ v1 was not properly synced")
        else:
            print("✗ No sync occurred")
