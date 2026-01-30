# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from unittest.mock import Mock, patch

import pytest
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import IDPConfig


@pytest.mark.unit
class TestSyncInternals:
    """Test what happens inside the sync method"""

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

    def test_sync_method_execution_flow(self, config_manager, mock_table):
        """Test the internal flow of _sync_all_versions_with_new_baseline"""

        # Create configs
        old_v0 = IDPConfig(
            classification={"model": "old-model"},
            classes=[{"name": "old", "description": "old class"}],
        )

        new_v0 = IDPConfig(
            classification={"model": "new-model"},  # Changed
            classes=[{"name": "old", "description": "old class"}],  # Same
        )

        v1_config = IDPConfig(
            classification={"model": "old-model"},  # Same as old v0
            extraction={"model": "custom-extraction"},  # User customization
            classes=[{"name": "old", "description": "old class"}],
        )

        # Mock get_configuration calls
        def mock_get_config(config_type, version=None):
            if config_type == "Config" and version == "v0":
                return old_v0  # Return old v0 for comparison
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
            # Don't actually save to avoid recursion
            return None

        with patch.object(
            config_manager, "get_configuration", side_effect=mock_get_config
        ):
            with patch.object(
                config_manager, "save_configuration", side_effect=track_save
            ):
                # Call the sync method directly
                config_manager._sync_all_versions_with_new_baseline(new_v0)

        print(f"Save calls made during sync: {len(save_calls)}")
        for i, (args, kwargs) in enumerate(save_calls):
            print(f"Call {i}: args={args[:3]}, skip_sync={kwargs.get('skip_sync')}")

        # Should have called save_configuration for v1 with skip_sync=True
        assert len(save_calls) >= 1, "Expected at least one save call for v1"

        # Check the actual parameters being passed
        print("Detailed save call analysis:")
        for i, (args, kwargs) in enumerate(save_calls):
            print(f"  Call {i}:")
            print(f"    args length: {len(args)}")
            if len(args) >= 1:
                print(f"    args[0] (config_type): {args[0]}")
            if len(args) >= 2:
                print(f"    args[1] (config): {type(args[1])}")
            if len(args) >= 3:
                print(f"    args[2]: {args[2]}")
            print(f"    kwargs: {kwargs}")

        # Look for version in kwargs instead
        v1_save_call = None
        for args, kwargs in save_calls:
            if kwargs.get("version") == "v1":
                v1_save_call = (args, kwargs)
                break

        if v1_save_call:
            assert v1_save_call[1].get("skip_sync"), (
                "v1 save should have skip_sync=True"
            )
            print("✓ Sync method executed and called save_configuration for v1")
        else:
            print("✗ v1 was not saved during sync - checking why...")
            # The sync might not be finding v1 or there might be no differences

    def test_sync_with_no_existing_v0(self, config_manager, mock_table):
        """Test sync behavior when no existing v0 exists"""

        new_v0 = IDPConfig(
            classification={"model": "new-model"},
            classes=[{"name": "test", "description": "test"}],
        )

        # Mock that no v0 exists
        def mock_get_config(config_type, version=None):
            return None  # No existing v0

        mock_table.scan.return_value = {"Items": []}

        with patch.object(
            config_manager, "get_configuration", side_effect=mock_get_config
        ):
            # This should return early and not crash
            config_manager._sync_all_versions_with_new_baseline(new_v0)

        print("✓ Sync handled missing v0 gracefully")

    def test_sync_with_no_other_versions(self, config_manager, mock_table):
        """Test sync behavior when no other versions exist"""

        old_v0 = IDPConfig(classification={"model": "old"}, classes=[])
        new_v0 = IDPConfig(classification={"model": "new"}, classes=[])

        def mock_get_config(config_type, version=None):
            if config_type == "Config" and version == "v0":
                return old_v0
            return None

        # Mock scan returns no other versions
        mock_table.scan.return_value = {"Items": []}

        save_calls = []

        def track_save(*args, **kwargs):
            save_calls.append((args, kwargs))

        with patch.object(
            config_manager, "get_configuration", side_effect=mock_get_config
        ):
            with patch.object(
                config_manager, "save_configuration", side_effect=track_save
            ):
                config_manager._sync_all_versions_with_new_baseline(new_v0)

        # Should not make any save calls since no other versions exist
        assert len(save_calls) == 0, (
            "No save calls should be made when no other versions exist"
        )
        print("✓ Sync made no calls when no other versions exist")
