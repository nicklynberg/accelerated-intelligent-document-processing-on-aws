# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

import boto3
import json
import os
from typing import Dict, Any, Optional, Union
from botocore.exceptions import ClientError
import logging

from .models import IDPConfig, SchemaConfig, PricingConfig, ConfigurationRecord
from .merge_utils import deep_update, apply_delta_with_deletions, strip_matching_defaults, get_diff_dict
from .constants import (
    CONFIG_TYPE_SCHEMA,
    CONFIG_TYPE_DEFAULT,
    CONFIG_TYPE_CUSTOM,
    CONFIG_TYPE_DEFAULT_PRICING,
    CONFIG_TYPE_CUSTOM_PRICING,
    VALID_CONFIG_TYPES,
)

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
        self, config_type: str
    ) -> Optional[Union[SchemaConfig, IDPConfig, PricingConfig]]:
        """
        Retrieve configuration from DynamoDB.

        This method:
        1. Reads the DynamoDB item
        2. Deserializes into ConfigurationRecord (auto-migrates legacy format)
        3. Checks if migration occurred and persists if needed
        4. Returns SchemaConfig for Schema type, PricingConfig for Pricing, IDPConfig for Default/Custom

        Args:
            config_type: Configuration type (Schema, Default, Custom, Pricing)

        Returns:
            SchemaConfig for Schema type, PricingConfig for Pricing, IDPConfig for Default/Custom, or None if not found

        Raises:
            ClientError: If DynamoDB operation fails
        """
        try:
            record = self._read_record(config_type)
            if record is None:
                logger.info(f"Configuration not found: {config_type}")
                return None

            # Note: ConfigurationRecord.from_dynamodb_item() auto-migrates legacy format
            # We don't need to check for migration separately - it's already done
            # If we want to persist the migration, we can optionally do so here

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

    def get_merged_configuration(self) -> Optional[IDPConfig]:
        """
        Get merged Default + Custom configuration for runtime processing.
        
        This is THE method to use for all runtime document processing.
        It properly merges the stack Default with user Custom deltas.
        
        Design Pattern:
        - Default = complete stack baseline (from deployment)
        - Custom = sparse user deltas ONLY
        - Merged = Default deep-updated with Custom = final runtime config
        
        Returns:
            Merged IDPConfig ready for runtime use, or None if Default doesn't exist
            
        Raises:
            ClientError: If DynamoDB operation fails
        """
        from copy import deepcopy
        
        # Get the full Default configuration (Pydantic validated - this is correct)
        default_config = self.get_configuration(CONFIG_TYPE_DEFAULT)
        if default_config is None:
            logger.warning("Default configuration not found - cannot create merged config")
            return None
            
        if not isinstance(default_config, IDPConfig):
            logger.error(f"Default config is not IDPConfig: {type(default_config)}")
            return None
        
        # Get Custom as RAW dict (no Pydantic defaults!)
        custom_dict = self.get_raw_configuration(CONFIG_TYPE_CUSTOM)
        
        # If no Custom, return Default as-is
        if not custom_dict:
            logger.info("No Custom configuration, returning Default")
            return default_config
        
        # Merge: Start with Default, deep update with Custom deltas
        default_dict = default_config.model_dump(mode="python")
        merged_dict = deepcopy(default_dict)
        deep_update(merged_dict, custom_dict)
        
        logger.info("Merged Default + Custom configurations for runtime")
        return IDPConfig(**merged_dict)

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
        skip_sync: bool = False,
    ) -> None:
        """
        Save configuration to DynamoDB.

        This method:
        1. Converts dict to appropriate config type if needed
        2. If saving Default, syncs Custom to preserve user customizations (unless skip_sync=True)
        3. Creates ConfigurationRecord
        4. Serializes to DynamoDB item
        5. Writes to DynamoDB
        
        Args:
            config_type: Configuration type (Schema, Default, Custom, DefaultPricing, CustomPricing)
            config: SchemaConfig, IDPConfig, PricingConfig model, or dict (dict will be converted to appropriate type)
            skip_sync: If True, skip automatic Custom sync when saving Default (used for save-as-default)

        Raises:
            ClientError: If DynamoDB operation fails
        """
        # Convert dict to appropriate config type if needed (for backward compatibility)
        if isinstance(config, dict):
            if config_type == CONFIG_TYPE_SCHEMA:
                config = SchemaConfig(**config)
            elif config_type in (CONFIG_TYPE_DEFAULT_PRICING, CONFIG_TYPE_CUSTOM_PRICING):
                config = PricingConfig(**config)
            else:
                config = IDPConfig(**config)

        # If updating Default, sync Custom to preserve user customizations
        # Skip sync if this is a "save as default" operation where Custom will be deleted
        if (
            config_type == CONFIG_TYPE_DEFAULT
            and not skip_sync
            and isinstance(config, IDPConfig)
        ):
            old_default = self.get_configuration(CONFIG_TYPE_DEFAULT)
            old_custom = self.get_configuration(CONFIG_TYPE_CUSTOM)

            if (
                old_default
                and old_custom
                and isinstance(old_default, IDPConfig)
                and isinstance(old_custom, IDPConfig)
            ):
                logger.info(
                    "Syncing Custom config with new Default while preserving user customizations"
                )
                new_custom = self.sync_custom_with_new_default(
                    old_default, config, old_custom
                )
                # Save the synced custom config
                self.save_configuration(CONFIG_TYPE_CUSTOM, new_custom, skip_sync=True)

        # Create record
        record = ConfigurationRecord(configuration_type=config_type, config=config)

        # Write to DynamoDB
        self._write_record(record)

        

    def delete_configuration(self, config_type: str) -> None:
        """
        Delete configuration from DynamoDB.

        Args:
            config_type: Configuration type to delete

        Raises:
            ClientError: If DynamoDB operation fails
        """
        try:
            self.table.delete_item(Key={"Configuration": config_type})
            logger.info(f"Deleted configuration: {config_type}")
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
        self, custom_config: Union[str, Dict[str, Any], IDPConfig]
    ) -> bool:
        """
        Handle the updateConfiguration GraphQL mutation.
        
        DESIGN PATTERN (CRITICAL):
        - Custom stores ONLY user deltas (sparse)
        - Frontend sends deltas to merge into existing Custom
        - We DO NOT use Pydantic defaults when reading existing Custom
        
        Operations:
        - resetToDefault=True: Delete Custom entirely (empty = use all defaults)
        - saveAsDefault=True: Save merged config as new Default, empty Custom
        - Normal update: Merge deltas into existing Custom (raw, no Pydantic)

        Args:
            custom_config: Configuration deltas as JSON string, dict, or IDPConfig

        Returns:
            True on success

        Raises:
            Exception: If configuration update fails
        """
        # Parse input to dict
        if isinstance(custom_config, str):
            config_dict = json.loads(custom_config)
        elif isinstance(custom_config, IDPConfig):
            config_dict = custom_config.model_dump(mode="python")
        else:
            config_dict = custom_config if custom_config else {}

        # Extract special flags before processing
        save_as_default = config_dict.pop("saveAsDefault", False) if isinstance(config_dict, dict) else False
        reset_to_default = config_dict.pop("resetToDefault", False) if isinstance(config_dict, dict) else False
        replace_custom = config_dict.pop("replaceCustom", False) if isinstance(config_dict, dict) else False
        
        # Remove legacy pricing field if present (now stored separately as DefaultPricing/CustomPricing)
        if isinstance(config_dict, dict):
            config_dict.pop("pricing", None)

        # Handle reset to default - delete Custom entirely
        # Empty Custom = use all defaults (this is the expected behavior)
        if reset_to_default:
            logger.info("Resetting Custom configuration by deleting it")
            try:
                self.delete_configuration(CONFIG_TYPE_CUSTOM)
            except Exception as e:
                # If Custom doesn't exist, that's fine - it's already "reset"
                logger.info(f"Custom config may not exist (already reset): {e}")
            logger.info("Custom configuration deleted - all defaults will now be used")
            return True

        # For empty config without special flags, nothing to do
        if not config_dict or (isinstance(config_dict, dict) and len(config_dict) == 0):
            logger.info("Empty configuration update with no special flags - no changes made")
            return True

        if save_as_default:
            # Save as Default: Frontend sends the complete merged config
            # This becomes the new baseline, then we delete Custom
            config = IDPConfig(**config_dict)
            
            # Skip sync since we're about to delete Custom anyway
            self.save_configuration(CONFIG_TYPE_DEFAULT, config, skip_sync=True)

            # Delete Custom since the new baseline now includes all customizations
            try:
                self.delete_configuration(CONFIG_TYPE_CUSTOM)
            except Exception:
                pass  # Custom might not exist
            
            logger.info("Saved current state as new Default and cleared Custom")
        elif replace_custom:
            # Replace Custom entirely (used for import operations)
            # This deletes existing Custom first, then saves the imported config as new Custom
            # Imported config is already merged with system defaults by frontend/import process
            logger.info("Replace Custom mode: clearing existing Custom before applying imported config")
            
            # Delete existing Custom first
            try:
                self.delete_configuration(CONFIG_TYPE_CUSTOM)
            except Exception:
                pass  # Custom might not exist
            
            # Validate that Default + imported config creates a valid config
            default_config = self.get_configuration(CONFIG_TYPE_DEFAULT)
            if default_config and isinstance(default_config, IDPConfig):
                from copy import deepcopy
                default_dict = default_config.model_dump(mode="python")
                validation_dict = deepcopy(default_dict)
                deep_update(validation_dict, config_dict)
                # This validates the merged config is valid - will raise ValidationError if not
                IDPConfig(**validation_dict)
                logger.info("Validated merged Default + imported configuration")
                
                # AUTO-CLEANUP: Remove fields that match their Default equivalents
                strip_matching_defaults(config_dict, default_dict)
                logger.info("Auto-cleaned imported config (removed values matching defaults)")
            
            # Save ONLY the sparse Custom deltas (NO Pydantic defaults!)
            self.save_raw_configuration(CONFIG_TYPE_CUSTOM, config_dict)
            logger.info("Replaced Custom configuration with imported config")
        else:
            # Normal custom config update - merge deltas into existing Custom
            # IMPORTANT: Use RAW Custom (no Pydantic defaults!) to preserve sparse pattern
            existing_custom_dict = self.get_raw_configuration(CONFIG_TYPE_CUSTOM)
            
            # If Custom doesn't exist, start with empty dict (NOT Default!)
            # Custom should only contain user deltas
            if existing_custom_dict is None:
                existing_custom_dict = {}
                logger.info("No existing Custom - creating new sparse delta config")
            
            # Merge the new deltas into existing Custom deltas
            # IMPORTANT: Use apply_delta_with_deletions to handle null values as deletions
            # This supports "reset to default" for individual fields:
            # - Frontend sends {"classification": {"model": null}} 
            # - Backend removes "model" from Custom.classification
            # - When merged with Default, the Default value is used
            apply_delta_with_deletions(existing_custom_dict, config_dict)
            
            # Validate that Default + merged Custom creates a valid config
            # (but don't save the merged version - save only the sparse Custom)
            default_config = self.get_configuration(CONFIG_TYPE_DEFAULT)
            if default_config and isinstance(default_config, IDPConfig):
                from copy import deepcopy
                default_dict = default_config.model_dump(mode="python")
                validation_dict = deepcopy(default_dict)
                deep_update(validation_dict, existing_custom_dict)
                # This validates the merged config is valid - will raise ValidationError if not
                IDPConfig(**validation_dict)
                logger.info("Validated merged Default + Custom configuration")
                
                # AUTO-CLEANUP: Remove Custom fields that match their Default equivalents
                # This implements "self-healing" for sparse delta pattern:
                # - If user sets a value to its default, remove it from Custom
                # - Handles "restore to default" naturally (just set the default value)
                # - Keeps Custom truly sparse (only real customizations)
                strip_matching_defaults(existing_custom_dict, default_dict)
                logger.info("Auto-cleaned Custom config (removed values matching defaults)")
            
            # Save ONLY the sparse Custom deltas (NO Pydantic defaults!)
            self.save_raw_configuration(CONFIG_TYPE_CUSTOM, existing_custom_dict)
            logger.info("Updated Custom configuration by merging deltas (sparse save)")

        return True

    # ===== Private Methods =====

    def _read_record(self, config_type: str) -> Optional[ConfigurationRecord]:
        """
        Read ConfigurationRecord from DynamoDB.

        Args:
            config_type: Configuration type to read

        Returns:
            ConfigurationRecord or None if not found
        """
        response = self.table.get_item(Key={"Configuration": config_type})
        item = response.get("Item")

        if item is None:
            return None

        return ConfigurationRecord.from_dynamodb_item(item)

    def _write_record(self, record: ConfigurationRecord) -> None:
        """
        Write ConfigurationRecord to DynamoDB.

        Args:
            record: ConfigurationRecord to write
        """
        item = record.to_dynamodb_item()
        self.table.put_item(Item=item)
        logger.info(f"Saved configuration: {record.configuration_type}")