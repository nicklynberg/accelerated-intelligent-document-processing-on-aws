# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Bedrock model configuration utilities.

This module provides utilities for building model configurations with
proper token limits, caching settings, and retry behavior.
"""

import logging
import re
from typing import Any

from botocore.config import Config

from idp_common.bedrock.client import CACHEPOINT_SUPPORTED_MODELS

logger = logging.getLogger(__name__)


def supports_prompt_caching(model_id: str) -> bool:
    """
    Check if a model supports prompt caching (cachePoint in system prompt).

    Args:
        model_id: The Bedrock model identifier

    Returns:
        True if the model supports prompt caching, False otherwise
    """
    return model_id in CACHEPOINT_SUPPORTED_MODELS


def supports_tool_caching(model_id: str) -> bool:
    """
    Check if a model supports tool caching (cachePoint in toolConfig).

    Note: Only Claude models support tool caching. Nova models support
    prompt caching but NOT tool caching.

    Args:
        model_id: The Bedrock model identifier

    Returns:
        True if the model supports tool caching, False otherwise
    """
    return "anthropic.claude" in model_id or "us.anthropic.claude" in model_id


def get_model_max_tokens(model_id: str) -> int:
    """
    Get the maximum output tokens supported by a model.

    Args:
        model_id: The Bedrock model identifier

    Returns:
        Maximum output tokens for the model
    """
    model_id_lower = model_id.lower()

    # Check Claude 4 patterns first (more specific)
    if re.search(r"claude-(opus|sonnet|haiku)-4", model_id_lower):
        return 64_000

    # Check Nova models
    if any(
        nova in model_id_lower
        for nova in ["nova-premier", "nova-pro", "nova-lite", "nova-micro"]
    ):
        return 10_000

    # Check Claude 3 models
    if "claude-3" in model_id_lower:
        return 8_192

    # Default fallback
    return 4_096


def build_model_config(
    model_id: str,
    max_tokens: int | None = None,
    max_retries: int = 3,
    connect_timeout: float = 60.0,
    read_timeout: float = 300.0,
) -> dict[str, Any]:
    """
    Build model configuration with token limits and caching settings.

    This function:
    1. Creates boto3 Config with retry and timeout settings
    2. Determines model-specific max token limits
    3. Validates and caps max_tokens if needed
    4. Auto-detects and enables caching support (prompt and tool caching)

    Args:
        model_id: Bedrock model identifier (supports us.*, eu.*, and global.anthropic.*)
        max_tokens: Optional max tokens override (will be capped at model max)
        max_retries: Maximum retry attempts for API calls (default: 3)
        connect_timeout: Connection timeout in seconds (default: 60.0)
        read_timeout: Read timeout in seconds (default: 300.0)

    Returns:
        Dictionary of model configuration parameters.
        Automatically uses BedrockModel for regional models (us.*, eu.*) and
        AnthropicModel with AnthropicBedrock for cross-region models (global.anthropic.*).
    """
    # Configure retry behavior and timeouts using boto3 Config
    boto_config = Config(
        retries={
            "max_attempts": max_retries,
            "mode": "adaptive",  # Uses exponential backoff with adaptive retry mode
        },
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )

    # Get model-specific maximum token limits
    model_max = get_model_max_tokens(model_id)

    # Use config value if provided, but cap at model's maximum
    if max_tokens is not None:
        if max_tokens > model_max:
            logger.warning(
                "Config max_tokens exceeds model limit, capping at model maximum",
                extra={
                    "config_max_tokens": max_tokens,
                    "model_max_tokens": model_max,
                    "model_id": model_id,
                },
            )
            max_output_tokens = model_max
        else:
            max_output_tokens = max_tokens
    else:
        # No config value - use model maximum
        max_output_tokens = model_max

    # Build base model config
    model_config = dict(
        model_id=model_id, boto_client_config=boto_config, max_tokens=max_output_tokens
    )

    logger.info(
        "Setting max_tokens for model",
        extra={
            "max_tokens": max_output_tokens,
            "model_id": model_id,
            "model_max_tokens": model_max,
        },
    )

    # Auto-detect caching support based on model capabilities
    if supports_prompt_caching(model_id):
        model_config["cache_prompt"] = "default"
        logger.info(
            "Prompt caching enabled for model",
            extra={"model_id": model_id, "auto_detected": True},
        )

        # Only enable tool caching if the model supports it (Claude only, not Nova)
        if supports_tool_caching(model_id):
            model_config["cache_tools"] = "default"
            logger.info(
                "Tool caching enabled for model",
                extra={"model_id": model_id, "auto_detected": True},
            )
        else:
            logger.info(
                "Tool caching not supported for model",
                extra={"model_id": model_id, "reason": "prompt_caching_only"},
            )
    else:
        logger.debug("Caching not supported for model", extra={"model_id": model_id})

    return model_config
