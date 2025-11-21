# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Bedrock integration module for IDP Common package."""

from .client import BedrockClient, default_client, invoke_model
from .model_config import (
    build_model_config,
    get_model_max_tokens,
    supports_prompt_caching,
    supports_tool_caching,
)

# Add version info
__version__ = "0.1.0"

# Export the public API
__all__ = [
    "BedrockClient",
    "invoke_model",
    "default_client",
    "build_model_config",
    "get_model_max_tokens",
    "supports_prompt_caching",
    "supports_tool_caching",
]

# Re-export key functions from the default client for backward compatibility
extract_text_from_response = default_client.extract_text_from_response
generate_embedding = default_client.generate_embedding
format_prompt = default_client.format_prompt
