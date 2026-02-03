# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import os
from typing import Dict, Any, Optional, Union, overload, Literal
from botocore.exceptions import ClientError
import logging
from copy import deepcopy
from .configuration_manager import ConfigurationManager
from .merge_utils import deep_update
from .models import (
    IDPConfig,
    ConfigurationRecord,
    ExtractionConfig,
    ClassificationConfig,
    AssessmentConfig,
    SchemaConfig,
    SummarizationConfig,
    OCRConfig,
    AgenticConfig,
    ImageConfig,
    PricingConfig,
)
from .constants import (
    CONFIG_TYPE_SCHEMA,
    CONFIG_TYPE_DEFAULT,
    CONFIG_TYPE_CUSTOM,
    CONFIG_TYPE_DEFAULT_PRICING,
    CONFIG_TYPE_CUSTOM_PRICING,
    VALID_CONFIG_TYPES,
)

logger = logging.getLogger(__name__)


class ConfigurationReader:
    def __init__(self, table_name=None):
        """
        Initialize the configuration reader using the table name from environment variable or parameter

        Args:
            table_name: Optional override for configuration table name
        """
        # Use ConfigurationManager for all operations (with built-in migration)
        self.manager = ConfigurationManager(table_name)
        logger.info(f"Initialized ConfigurationReader with ConfigurationManager")

    @overload
    def get_configuration(
        self, config_type: str, *, as_dict: Literal[True]
    ) -> Optional[Dict[str, Any]]: ...

    @overload
    def get_configuration(
        self, config_type: str, *, as_dict: Literal[False]
    ) -> Optional[Union[IDPConfig, SchemaConfig, PricingConfig]]: ...

    def get_configuration(
        self, config_type: str, *, as_dict: bool = True
    ) -> Optional[Union[Dict[str, Any], IDPConfig, SchemaConfig, PricingConfig]]:
        """
        Retrieve a configuration item from DynamoDB with automatic migration

        Args:
            config_type: The configuration type to retrieve ('Default' or 'Custom')
            as_dict: If True (default), return raw dictionary for backward compatibility

        Returns:
            Configuration dictionary if found (auto-migrated if needed), None otherwise
        """
        # ConfigurationManager now returns IDPConfig by default
        idp_config = self.manager.get_configuration(config_type)

        if idp_config is None:
            return None

        # Convert to dict if requested (for backward compatibility)
        if as_dict:
            config_dict = idp_config.model_dump(mode="python")
            # Add Configuration key back for backward compatibility
            config_dict["Configuration"] = config_type
            return config_dict

        return idp_config

    def simple_merge(
        self, default: Dict[str, Any], custom: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Deep merge with custom values overriding defaults.

        Custom configuration should only contain fields that differ from default,
        not a complete configuration tree. Nested dicts are merged recursively.

        Args:
            default: The default configuration dictionary
            custom: The custom overrides dictionary

        Returns:
            Merged configuration dictionary (default updated with custom)
        """
        from copy import deepcopy

        merged = deepcopy(default)
        return deep_update(merged, custom)

    @overload
    def get_merged_configuration(self, *, as_model: Literal[True]) -> IDPConfig: ...

    @overload
    def get_merged_configuration(
        self, *, as_model: Literal[False]
    ) -> Dict[str, Any]: ...

    def get_merged_configuration(
        self, *, as_model: bool = False
    ) -> Union[IDPConfig, Dict[str, Any]]:
        """
        Get and merge Default and Custom configurations for runtime processing.
        
        DESIGN PATTERN (CRITICAL):
        - Default: Full stack baseline (Pydantic validated)
        - Custom: SPARSE DELTAS ONLY (raw from DynamoDB, NO Pydantic defaults!)
        - Merged: Default deep-updated with Custom = final runtime config
        
        This is THE method to use for all runtime document processing.

        Args:
            as_model: If True, return IDPConfig Pydantic model. If False (default), return dict.

        Returns:
            Merged configuration as IDPConfig or dictionary
        """
        try:
            # Get Default configuration (Pydantic validated - this is correct for Default)
            default_config = self.get_configuration("Default", as_dict=True)
            if not default_config:
                raise ValueError("Default configuration not found")
            
            # Remove the 'Configuration' key as it's not part of the actual config
            default_config.pop("Configuration", None)

            # Get Custom configuration as RAW dict (NO Pydantic defaults!)
            # This is critical for the sparse delta pattern to work correctly
            custom_config = self.manager.get_raw_configuration("Custom")

            # If no custom config exists, use default as-is
            if not custom_config:
                logger.info("No Custom configuration found, using Default only")
                merged_config = default_config
            else:
                # Merge: Default deep-updated with Custom deltas
                merged_config = self.simple_merge(default_config, custom_config)

            logger.info("Successfully merged Default + Custom configurations for runtime")

            # Return Pydantic model if requested
            if as_model:
                return IDPConfig(**merged_config)

            return merged_config

        except Exception as e:
            logger.error(f"Error getting merged configuration: {str(e)}")
            raise


@overload
def get_config(
    *, table_name: Optional[str] = None, as_model: Literal[True]
) -> IDPConfig:
    """
    Get configuration as Pydantic model.

    Use config.to_dict() to convert to mutable dict with extra fields:
        config = get_config(as_model=True)
        config_dict = config.to_dict(sagemaker_endpoint_name=endpoint)
    """
    ...


@overload
def get_config(
    *, table_name: Optional[str] = None, as_model: Literal[False] = False
) -> Dict[str, Any]:
    """Get configuration as mutable dictionary."""
    ...


def get_config(
    *, table_name: Optional[str] = None, as_model: bool = False
) -> Union[IDPConfig, Dict[str, Any]]:
    """
    Get the merged configuration using the environment variable for table name.

    Args:
        table_name: Optional override for configuration table name
        as_model: If True, return IDPConfig Pydantic model. If False (default), return dict.

    Returns:
        Merged configuration as IDPConfig (with .to_dict() helper) or mutable dictionary.

    Examples:
        # Get as dict for direct manipulation
        config = get_config(as_model=False)
        config["extra_field"] = "value"

        # Get as model, convert to dict with extras
        config = get_config(as_model=True)
        config_dict = config.to_dict(sagemaker_endpoint_name=endpoint)
    """
    reader = ConfigurationReader(table_name)
    return reader.get_merged_configuration(as_model=as_model)