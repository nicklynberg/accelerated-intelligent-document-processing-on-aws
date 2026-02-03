# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import boto3
from botocore.exceptions import ClientError

from .constants import (
    CONFIG_TYPE_CUSTOM,
    CONFIG_TYPE_CUSTOM_PRICING,
    CONFIG_TYPE_DEFAULT,
    CONFIG_TYPE_DEFAULT_PRICING,
    CONFIG_TYPE_SCHEMA,
    VALID_CONFIG_TYPES,
)
from .merge_utils import deep_update, get_diff_dict, apply_delta_with_deletions, strip_matching_defaults
from .models import ConfigurationRecord, IDPConfig, PricingConfig, SchemaConfig, ConfigMetadata

logger = logging.getLogger(__name__)


class ConfigurationManager:
    """
    Manages IDP configurations stored in DynamoDB.

    All operations use IDPConfig (Pydantic models) - no dict manipulation!
    ConfigurationRecord handles DynamoDB serialization internally.

    Example:
        manager = ConfigurationManager()

        # Get configuration (always returns IDPConfig)
        config = manager.get_configuration(CONFIG_TYPE_DEFAULT)

        # Save configuration
        manager.save_configuration(CONFIG_TYPE_CUSTOM, config)
    """

    def __init__(self, table_name: Optional[str] = None):
        """
        Initialize the configuration manager.

        Args:
            table_name: Optional override for configuration table name.
                       If not provided, uses CONFIGURATION_TABLE_NAME env var.

        Raises:
            ValueError: If table name cannot be determined
        """
        table_name = table_name or os.environ.get("CONFIGURATION_TABLE_NAME")
        if not table_name:
            raise ValueError(
                "Configuration table name not provided. Either set CONFIGURATION_TABLE_NAME "
                "environment variable or provide table_name parameter."
            )

        self.dynamodb = boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(table_name)  # pyright: ignore[reportAttributeAccessIssue]
        self.table_name = table_name
        logger.info(f"ConfigurationManager initialized with table: {table_name}")

    def get_configuration(
        self, config_type: str, version: Optional[str] = None
    ) -> Optional[Union[SchemaConfig, IDPConfig, PricingConfig]]:
        """
        Retrieve configuration from DynamoDB.

        Args:
            config_type: Configuration type ("Config", "Schema", "Pricing", or legacy "Default"/"Custom")
            version: Version identifier for Config type only (default, production-config, test-config, etc.). 
                    If None for Config type, returns active version.
                    Ignored for Schema/Pricing types.

        Returns:
            SchemaConfig for Schema type, PricingConfig for Pricing, IDPConfig for Config/versions, or None if not found
        """
        try:
            # Handle versioned Config type
            if config_type == "Config":
                if version:
                    # Check if version exists first
                    version_record = self._read_record("Config", version)
                    if not version_record:
                        return None
                    
                    # For non-default versions, merge with default baseline for automatic inheritance
                    if version != "default":
                        return self._get_merged_version_config(version)
                    else:
                        # Get default directly
                        record = version_record
                else:
                    # Get active version (merging handled in _get_active_config_version)
                    record = self._get_active_config_version()
            else:
                # For all other types, pass config_type directly
                record = self._read_record(config_type, "")
                
            if record is None:
                logger.info(f"Configuration not found: {config_type}" + (f"/{version}" if version else ""))
                return None

            return record.config

        except ClientError as e:
            logger.error(f"Error retrieving configuration {config_type}: {e}")
            raise

    def get_raw_configuration(self, config_type: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve RAW configuration from DynamoDB without Pydantic validation.
        
        This is critical for the Custom configuration which should return ONLY
        the user-modified fields (sparse delta), NOT a full config with Pydantic defaults.
        
        Design Pattern:
        - Custom item stores ONLY user deltas
        - Using Pydantic validation would fill in all defaults (BAD for delta pattern)
        - This method returns the raw dict exactly as stored in DynamoDB
        
        Args:
            config_type: Configuration type (typically CONFIG_TYPE_CUSTOM)
            
        Returns:
            Raw dict from DynamoDB (without Pydantic default-filling), or None if not found
            
        Raises:
            ClientError: If DynamoDB operation fails
        """
        try:
            response = self.table.get_item(Key={"Configuration": config_type})
            item = response.get("Item")
            
            if item is None:
                logger.info(f"Raw configuration not found: {config_type}")
                return None
            
            # Remove the DynamoDB partition key - return only the config data
            config_data = {k: v for k, v in item.items() if k != "Configuration"}
            
            logger.info(f"Retrieved raw configuration for {config_type}")
            return config_data
            
        except ClientError as e:
            logger.error(f"Error retrieving raw configuration {config_type}: {e}")
            raise

    def save_raw_configuration(self, config_type: str, config_dict: Dict[str, Any]) -> None:
        """
        Save raw configuration dict to DynamoDB WITHOUT Pydantic validation.
        
        This is critical for Custom configs which should store ONLY user deltas (sparse).
        Using Pydantic would fill in all defaults, which defeats the delta pattern.
        
        WARNING: Only use for CONFIG_TYPE_CUSTOM to preserve sparse delta pattern.
        For other config types (Default, Schema), use save_configuration() which
        validates through Pydantic.
        
        Args:
            config_type: Configuration type (should be CONFIG_TYPE_CUSTOM)
            config_dict: Raw dict to save (only user deltas, no defaults)
            
        Raises:
            ClientError: If DynamoDB operation fails
        """
        try:
            # Build DynamoDB item directly without Pydantic
            # IMPORTANT: Stringify values to convert floats to strings for DynamoDB
            # (DynamoDB doesn't accept Python float types, only Decimal or string)
            item = {"Configuration": config_type}
            stringified = ConfigurationRecord._stringify_values(config_dict)
            item.update(stringified)
            
            self.table.put_item(Item=item)
            logger.info(f"Saved raw configuration (sparse delta): {config_type}")
            
        except ClientError as e:
            logger.error(f"Error saving raw configuration {config_type}: {e}")
            raise

    def sync_custom_with_new_default(
        self, old_default: IDPConfig, new_default: IDPConfig, old_custom: IDPConfig
    ) -> IDPConfig:
        """
        Sync Custom config when Default is updated, preserving user customizations.

        Algorithm:
        1. Find what the user customized (diff between old_custom and old_default)
        2. Start with new_default
        3. Apply user customizations to new_default

        This ensures users get all new default values except for fields they customized.

        Args:
            old_default: Previous default configuration
            new_default: New default configuration being saved
            old_custom: Current custom configuration

        Returns:
            New custom configuration with user changes preserved
        """
        from copy import deepcopy

        # Convert to dicts
        old_default_dict = old_default.model_dump(mode="python")
        old_custom_dict = old_custom.model_dump(mode="python")
        new_default_dict = new_default.model_dump(mode="python")

        # Find what the user customized (only fields that differ)
        user_customizations = get_diff_dict(old_default_dict, old_custom_dict)

        logger.info(
            f"User customizations to preserve: {list(user_customizations.keys())}"
        )

        # Start with new default and apply user customizations
        new_custom_dict = deepcopy(new_default_dict)
        deep_update(new_custom_dict, user_customizations)

        return IDPConfig(**new_custom_dict)

    def save_configuration(
        self,
        config_type: str,
        config: Union[SchemaConfig, IDPConfig, PricingConfig, Dict[str, Any]],
        version: Optional[str] = None,
        description: Optional[str] = None,
        skip_sync: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Save configuration to DynamoDB using composite key structure.

        Args:
            config_type: Configuration type ("Config", "Schema", "Pricing")
            config: SchemaConfig, IDPConfig, PricingConfig model, or dict
            version: Version identifier for Config type only (default, production-config, test-config, etc.). 
                    If None for Config type, saves to active version.
                    Ignored for Schema/Pricing types.
            description: Version description
            skip_sync: If True, skip automatic sync when updating Config versions
            metadata: Optional metadata (created_at, updated_at only)

        Note: Use activate_version() to control which version is active.

        Example:
            save_configuration("Config", idp_config, version="v1", description="User config")
            activate_version("v1")  # Separate activation step

        Raises:
            ClientError: If DynamoDB operation fails
        """
        # Convert dict to appropriate config type if needed
        if isinstance(config, dict):
            if config_type == CONFIG_TYPE_SCHEMA:
                config = SchemaConfig(**config)
            elif config_type in (CONFIG_TYPE_DEFAULT_PRICING, CONFIG_TYPE_CUSTOM_PRICING):
                config = PricingConfig(**config)
            else:
                config = IDPConfig(**config)

        # Handle legacy config types
        if config_type == CONFIG_TYPE_DEFAULT:
            config_type = "Config"
            if version is None:
                version = "default"
        elif config_type == CONFIG_TYPE_CUSTOM:
            config_type = "Config"
            if version is None:
                version = "v1"

        # For Config type, determine version and preserve active status
        if config_type == "Config":
            if version is None:
                # Get active version to update
                active_record = self._get_active_config_version()
                if active_record:
                    version = active_record.version
                else:
                    # No active version exists, default to default
                    version = "default"
            
            # Check if this version already exists to preserve is_active status and metadata
            existing_record = self._read_record("Config", version)
            is_active_status = existing_record.is_active if existing_record else False
            
            # Simple metadata handling
            import datetime
            timestamp = datetime.datetime.utcnow().isoformat() + "Z"
            
            if existing_record:
                # Existing config - preserve created_at, update updated_at
                metadata = {
                    "created_at": existing_record.metadata.created_at if existing_record.metadata else timestamp,
                    "updated_at": timestamp
                }
            else:
                # New config - set both timestamps
                metadata = {
                    "created_at": timestamp,
                    "updated_at": timestamp
                }
            
            # If updating default (baseline), sync all other versions
            if version == "default" and not skip_sync and isinstance(config, IDPConfig):
                self._sync_all_versions_with_new_baseline(config)
            
            configuration_type = "Config"
        else:
            # For all other types, use config_type directly
            configuration_type, version = config_type, ""
            is_active_status = None  # Non-Config types don't use is_active

        # Create record with metadata
        config_metadata = None
        if metadata:
            config_metadata = ConfigMetadata(**metadata)
        
        record = ConfigurationRecord(
            configuration_type=configuration_type,
            version=version,
            is_active=is_active_status,  # Preserve existing active status or None for new
            description=description,
            config=config,
            metadata=config_metadata
        )

        # Write to DynamoDB
        self._write_record(record, f"Config#{version}" if config_type == "Config" and version else config_type)

    def activate_version(self, version: str) -> None:
        """
        Activate a specific Config version and deactivate all others.
        
        Args:
            version: Version to activate (default, production-config, test-config, etc.)
            
        Raises:
            ValueError: If version doesn't exist
            ClientError: If DynamoDB operation fails
        """
        # First, verify the version exists
        target_record = self._read_record("Config", version)
        if not target_record:
            raise ValueError(f"Config version {version} not found")
        
        # Scan for all Config# versions
        try:
            response = self.table.scan(
                FilterExpression="begins_with(Configuration, :config_prefix)",
                ExpressionAttributeValues={":config_prefix": "Config#"}
            )
            
            # Update all versions
            for item in response.get('Items', []):
                config_key = item.get('Configuration', '')
                if "#" in config_key:
                    _, item_version = config_key.split("#", 1)
                    should_be_active = (item_version == version)
                    
                    # Update is_active field
                    self.table.update_item(
                        Key={"Configuration": config_key},
                        UpdateExpression="SET IsActive = :active",
                        ExpressionAttributeValues={":active": should_be_active}
                    )
            
            logger.info(f"Activated Config version {version}")
            
        except ClientError as e:
            logger.error(f"Error activating version {version}: {e}")
            raise

    def list_config_versions(self) -> List[Dict[str, Any]]:
        """
        List all configuration versions.
        
        Returns:
            List of version info dicts with versionId, isActive, createdAt, updatedAt, description
        """
        try:
            response = self.table.scan(
                FilterExpression="begins_with(Configuration, :config_prefix)",
                ExpressionAttributeValues={":config_prefix": "Config#"},
                ProjectionExpression="Configuration, IsActive, CreatedAt, UpdatedAt, Description"
            )
            
            versions = []
            for item in response.get('Items', []):
                config_key = item.get('Configuration', '')
                if "#" in config_key:
                    _, version = config_key.split("#", 1)
                    versions.append({
                        "versionName": version,
                        "isActive": item.get('IsActive'),  # Can be None, True, or False
                        "createdAt": item.get('CreatedAt'),
                        "updatedAt": item.get('UpdatedAt'),
                        "description": item.get('Description', f"Configuration version {version}")
                    })
            
            return versions
            
        except ClientError as e:
            logger.error(f"Error listing config versions: {e}")
            return []


        

    def delete_configuration(self, config_type: str, version: Optional[str] = None) -> None:
        """
        Delete configuration from DynamoDB using single key.

        Args:
            config_type: Configuration type ("Config", "Schema", "Pricing", or legacy "Default"/"Custom")
            version: Version identifier for Config type only (default, production-config, test-config, etc.). 
                    Required for Config type, ignored for Schema/Pricing types.

        Raises:
            ClientError: If DynamoDB operation fails
            ValueError: If version is required but not provided
        """
        try:
            # Handle versioned Config type
            if config_type == "Config":
                if version is None:
                    raise ValueError("Version is required for Config type")
                
                # Check if trying to delete active version
                record = self._read_record("Config", version)
                logger.info(f"Checking version {version} for deletion. Record found: {record is not None}, Is active: {record.is_active if record else 'N/A'}")
                
                if record and record.is_active:
                    raise ValueError(f"Cannot delete active version {version}. Activate another version first.")
                
                key = f"Config#{version}"
            else:
                # For all other types, use config_type directly
                key = config_type

            self.table.delete_item(Key={"Configuration": key})
            logger.info(f"Deleted configuration: {config_type}" + (f"/{version}" if version else ""))
        except ClientError as e:
            logger.error(f"Error deleting configuration {config_type}: {e}")
            raise

    # ===== Pricing Configuration Methods =====

    def get_merged_pricing(self) -> Optional[PricingConfig]:
        """
        Get the merged pricing configuration (DefaultPricing + CustomPricing deltas).

        This mirrors the Default/Custom pattern for IDP configuration:
        - DefaultPricing: Full baseline pricing from deployment
        - CustomPricing: Only user overrides/deltas (if any)

        Returns:
            Merged PricingConfig with custom overrides applied, or None if not found

        Raises:
            ClientError: If DynamoDB operation fails
        """
        from copy import deepcopy

        # Get default pricing
        default_config = self.get_configuration(CONFIG_TYPE_DEFAULT_PRICING)
        if default_config is None:
            logger.warning("DefaultPricing not found in DynamoDB")
            return None

        if not isinstance(default_config, PricingConfig):
            logger.warning(
                f"Expected PricingConfig but got {type(default_config).__name__}"
            )
            return None

        # Get custom pricing (deltas only)
        custom_config = self.get_configuration(CONFIG_TYPE_CUSTOM_PRICING)

        # If no custom pricing, return default
        if custom_config is None:
            logger.info("No CustomPricing found, returning DefaultPricing")
            return default_config

        if not isinstance(custom_config, PricingConfig):
            logger.warning(
                f"CustomPricing is not PricingConfig, returning DefaultPricing"
            )
            return default_config

        # Merge: Start with default, apply custom overrides
        default_dict = default_config.model_dump(mode="python")
        custom_dict = custom_config.model_dump(mode="python")

        merged_dict = deepcopy(default_dict)
        deep_update(merged_dict, custom_dict)

        logger.info("Merged DefaultPricing with CustomPricing deltas")
        return PricingConfig(**merged_dict)

    def save_custom_pricing(self, pricing_deltas: Union[PricingConfig, Dict[str, Any]]) -> bool:
        """
        Save custom pricing overrides to DynamoDB.

        This saves only the user's customizations (deltas from default).
        The deltas are merged with DefaultPricing when reading.

        Args:
            pricing_deltas: PricingConfig or dict with only the fields that differ from default

        Returns:
            True on success

        Raises:
            ClientError: If DynamoDB operation fails
        """
        # Convert dict to PricingConfig if needed
        if isinstance(pricing_deltas, dict):
            pricing_deltas = PricingConfig(**pricing_deltas)

        # Save to CustomPricing
        self.save_configuration(CONFIG_TYPE_CUSTOM_PRICING, pricing_deltas)

        logger.info("Saved CustomPricing configuration")
        return True

    def delete_custom_pricing(self) -> bool:
        """
        Delete custom pricing, effectively resetting to defaults.

        After deletion, get_merged_pricing() will return DefaultPricing only.

        Returns:
            True on success

        Raises:
            ClientError: If DynamoDB operation fails
        """
        try:
            self.delete_configuration(CONFIG_TYPE_CUSTOM_PRICING)
            logger.info("Deleted CustomPricing, pricing reset to defaults")
            return True
        except ClientError as e:
            # If the item doesn't exist, that's fine - it's already "deleted"
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                logger.info("CustomPricing already deleted or never existed")
                return True
            raise

    def handle_update_custom_configuration(
        self, custom_config: Union[str, Dict[str, Any], IDPConfig], version: Optional[str] = None, description: Optional[str] = None
    ) -> bool:
        """
        Handle the updateConfiguration GraphQL mutation.

        This method:
        1. Parses the input (JSON string, dict, or IDPConfig)
        2. Validates that config is not empty (prevents data loss)
        3. Merges diff into existing configuration
        4. Saves updated configuration
        
        Args:
            custom_config: Configuration as JSON string, dict, or IDPConfig
            version: Version to update (default, production-config, test-config, etc.). If None, updates active version.

        Returns:
            True on success

        Raises:
            Exception: If configuration update fails or is empty
        """
        # Reject completely empty configuration to prevent accidental data deletion
        if not custom_config:
            logger.error("Rejecting empty configuration update")
            raise Exception(
                "Cannot update with empty configuration. Frontend should not send empty diffs."
            )

        # Parse input
        if isinstance(custom_config, str):
            config_dict = json.loads(custom_config)
        elif isinstance(custom_config, IDPConfig):
            config_dict = custom_config.model_dump(mode="python")
        else:
            config_dict = custom_config

        # Extract special flags before processing
        reset_to_default = config_dict.pop("resetToDefault", False) if isinstance(config_dict, dict) else False
        
        # Handle reset to default - copy default config to specified version
        if reset_to_default:
            logger.info(f"Resetting version {version} to default")
            
            # Get default configuration
            default_config = self.get_configuration("Config", "default")
            if not default_config or not isinstance(default_config, IDPConfig):
                raise Exception("Cannot reset to default: default configuration not found")
            
            # Save default config to the specified version (no activation change)
            self.save_configuration("Config", default_config, version=version)
            logger.info(f"Reset version {version} to match default")
            return True

        # Additional validation: reject if parsed config is empty dict
        if isinstance(config_dict, dict) and len(config_dict) == 0:
            logger.error("Rejecting empty configuration dict")
            raise Exception(
                "Cannot update with empty configuration. Frontend should not send empty diffs."
            )

        # Remove legacy pricing field if present (now stored separately as Pricing type)
        config_dict.pop("pricing", None)

        # Convert to IDPConfig for validation
        config = IDPConfig(**config_dict)

        # Get existing configuration to merge with
        existing_config = self.get_configuration("Config", version)
        if not existing_config or not isinstance(existing_config, IDPConfig):
            # Fallback: If version doesn't exist, use default as base
            logger.warning(f"Version {version} not found, using default as base")
            existing_config = self.get_configuration("Config", "default") or IDPConfig()

        # Apply the diff to existing config (deep update to handle nested objects)
        existing_dict = existing_config.model_dump(mode="python")
        update_dict = config.model_dump(mode="python", exclude_unset=True)
        deep_update(existing_dict, update_dict)
        merged_config = IDPConfig(**existing_dict)

        # Handle version name changes - check if version changed in update
        if 'version_name' in update_dict:
            new_version = update_dict['version_name']
            if new_version != version:
                logger.info(f"Version name changed: moving from {version} to {new_version}")
                
                # Check if new version already exists
                existing_new_version = self.get_configuration("Config", new_version)
                if existing_new_version:
                    raise Exception(f"Cannot rename: version '{new_version}' already exists")
                
                # Save to new version
                self.save_configuration("Config", merged_config, version=new_version, description=description)
                
                # Delete old version
                self.delete_configuration("Config", version)
                
                logger.info(f"Successfully moved version from {version} to {new_version}")
                return True
        
        # Save updated configuration (same version)
        self.save_configuration("Config", merged_config, version=version, description=description)
        logger.info(f"Updated Config version {version or 'active'} by merging diff")

        return True

    # ===== Private Methods =====

    def _sync_all_versions_with_new_baseline(self, new_baseline: IDPConfig) -> None:
        """
        Sync all Config versions with new default baseline.
        
        For each version > default:
        1. Get old default and the version config
        2. Calculate what the user customized (diff between version and old default)
        3. Apply those customizations to new baseline
        4. Save the synced version
        
        Args:
            new_baseline: The new default configuration
        """
        try:
            # Get old default for comparison
            old_baseline = self.get_configuration("Config", "default")
            if not old_baseline or not isinstance(old_baseline, IDPConfig):
                logger.info("No existing default to sync from")
                return
            
            # Query all Config versions
            response = self.table.scan(
                FilterExpression="begins_with(Configuration, :config_prefix)",
                ExpressionAttributeValues={":config_prefix": "Config#"}
            )
            
            # Sync each version > default
            for item in response.get('Items', []):
                version = item.get('Version', '')
                if version and version != "default":
                    # Get the current version config
                    current_version = self.get_configuration("Config", version)
                    if current_version and isinstance(current_version, IDPConfig):
                        logger.info(f"Syncing version {version} with new default baseline")
                        
                        # Calculate user customizations and apply to new baseline
                        synced_config = self.sync_custom_with_new_default(
                            old_baseline, new_baseline, current_version
                        )
                        
                        # Save the synced version (skip_sync=True to avoid recursion)
                        self.save_configuration(
                            "Config", 
                            synced_config, 
                            version=version, 
                            skip_sync=True
                        )
            
        except ClientError as e:
            logger.error(f"Error syncing versions with new baseline: {e}")
            raise

    def _get_active_config_version(self) -> Optional[ConfigurationRecord]:
        """
        Get the active Config version (where is_active=True).
        For non-default active versions, merges with default baseline for automatic inheritance.
        
        Returns:
            ConfigurationRecord with is_active=True, or None if not found
        """
        try:
            # Scan for Config# keys with IsActive=True
            response = self.table.scan(
                FilterExpression="begins_with(Configuration, :config_prefix) AND IsActive = :active",
                ExpressionAttributeValues={
                    ":config_prefix": "Config#",
                    ":active": True
                }
            )
            
            items = response.get('Items', [])
            if not items:
                logger.info("No active Config version found")
                return None
            
            if len(items) > 1:
                logger.warning(f"Multiple active Config versions found: {len(items)}")
            
            # Get the first active version found
            active_record = ConfigurationRecord.from_dynamodb_item(items[0])
            
            # If active version is not default, merge with default baseline
            if active_record.version != "default":
                merged_config = self._get_merged_version_config(active_record.version)
                if merged_config:
                    # Return record with merged config
                    active_record.config = merged_config
            
            return active_record
            
        except ClientError as e:
            logger.error(f"Error scanning for active Config version: {e}")
            return None

    def _get_merged_version_config(self, version: str) -> Optional[IDPConfig]:
        """
        Get version config merged with default baseline for automatic inheritance.
        
        Args:
            version: Version identifier (production-config, test-config, etc.)
            
        Returns:
            Merged IDPConfig with default baseline + version customizations, or None if not found
        """
        try:
            # Get default baseline
            default_record = self._read_record("Config", "default")
            if not default_record:
                logger.warning("No default baseline found for merging")
                # Fallback to version config only
                version_record = self._read_record("Config", version)
                return version_record.config if version_record else None
            
            # Get version config
            version_record = self._read_record("Config", version)
            if not version_record:
                logger.info(f"Version {version} not found, returning default baseline")
                return default_record.config
            
            # Merge default baseline with version customizations
            from copy import deepcopy
            default_dict = default_record.config.model_dump(mode="python")
            version_dict = version_record.config.model_dump(mode="python")
            
            # Start with default baseline and apply version customizations
            merged_dict = deepcopy(default_dict)
            deep_update(merged_dict, version_dict)
            
            return IDPConfig(**merged_dict)
            
        except ClientError as e:
            logger.error(f"Error merging version {version} with default: {e}")
            raise

    def _read_record(self, configuration_type: str, version: str = "") -> Optional[ConfigurationRecord]:
        """
        Read ConfigurationRecord from DynamoDB using single key.

        Args:
            configuration_type: Configuration type (Config, Schema, Pricing)
            version: Version identifier for Config type (default, production-config, test-config, ...) or "" for Schema/Pricing

        Returns:
            ConfigurationRecord or None if not found
        """
        # Generate single key
        if configuration_type == "Config" and version:
            key = f"Config#{version}"
        else:
            key = configuration_type
            
        response = self.table.get_item(Key={"Configuration": key})
        item = response.get("Item")

        if item is None:
            return None

        return ConfigurationRecord.from_dynamodb_item(item)

    def _write_record(self, record: ConfigurationRecord, identifier: Optional[str] = None) -> None:
        """
        Write ConfigurationRecord to DynamoDB using single key.

        Args:
            record: ConfigurationRecord to write
            identifier: Optional identifier for logging (e.g., "v1", "Schema")
        """
        item = record.to_dynamodb_item()
        self.table.put_item(Item=item)
        
        # Generate log identifier
        if identifier:
            log_id = identifier
        elif record.configuration_type == "Config" and record.version:
            log_id = f"Config#{record.version}"
        else:
            log_id = record.configuration_type
            
        logger.info(f"Saved configuration: {log_id}")
