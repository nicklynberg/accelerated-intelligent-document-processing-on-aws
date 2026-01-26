# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Utility functions for configuration merging and manipulation.

This module provides utilities for:
- Deep merging of configuration dictionaries
- Loading system defaults from YAML files (packaged within idp_common)
- Merging user configs with system defaults
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from copy import deepcopy

# Use importlib.resources for Python 3.9+
if sys.version_info >= (3, 9):
    from importlib.resources import files as importlib_files
    from importlib.resources import as_file
else:
    from importlib_resources import files as importlib_files
    from importlib_resources import as_file

logger = logging.getLogger(__name__)

# Valid pattern names
VALID_PATTERNS = ["pattern-1", "pattern-2", "pattern-3"]


def deep_update(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively update target dict with source dict.

    Nested dictionaries are merged recursively. Other values are deep copied
    to avoid mutation issues.

    Args:
        target: Target dictionary to update
        source: Source dictionary with updates

    Returns:
        Updated target dictionary (modified in place)
    """
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            deep_update(target[key], value)
        else:
            target[key] = deepcopy(value)
    return target


def get_diff_dict(base: Dict[str, Any], modified: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get a dictionary containing only the fields that differ between base and modified.

    This creates a "diff dict" that when applied to base (via deep_update) would
    produce modified. Recursively compares nested dictionaries.

    Args:
        base: Base/default dictionary
        modified: Modified/custom dictionary

    Returns:
        Dictionary containing only the differences (values from modified that differ from base)

    Example:
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        modified = {"a": 1, "b": {"c": 5, "d": 3}, "e": 6}
        result = {"b": {"c": 5}, "e": 6}  # Only changed/added fields
    """
    diff = {}

    # Check for added or changed keys in modified
    for key, value in modified.items():
        if key not in base:
            # New key - include it
            diff[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(base[key], dict):
            # Both are dicts - recurse
            nested_diff = get_diff_dict(base[key], value)
            if nested_diff:  # Only include if there are differences
                diff[key] = nested_diff
        elif value != base[key]:
            # Value changed
            diff[key] = deepcopy(value)

    # Note: We don't track deletions (keys in base but not in modified)
    # This is intentional - Custom should always be a complete config

    return diff


def get_system_defaults_dir() -> Path:
    """
    Get the path to the system_defaults directory.

    The system_defaults directory is now bundled within the idp_common package
    at idp_common/config/system_defaults/. This ensures the defaults are available
    in all environments (Lambda, notebooks, pip-installed, etc.)

    Returns:
        Path to the system_defaults directory

    Priority order:
        1. Package resources (idp_common.config.system_defaults)
        2. Environment variable IDP_SYSTEM_DEFAULTS_DIR
        3. Legacy: config_library/system_defaults from project root
    """
    # Priority 1: Use package resources (works in Lambda, pip installed, etc.)
    try:
        # Get the package resource directory
        defaults_resource = importlib_files("idp_common.config.system_defaults")
        # For directories, we can use the traversable directly as a path
        # This works because the package includes the directory
        defaults_path = Path(str(defaults_resource))
        if defaults_path.exists() and defaults_path.is_dir():
            logger.debug(f"Using package system_defaults: {defaults_path}")
            return defaults_path
    except (ModuleNotFoundError, TypeError, AttributeError) as e:
        logger.debug(f"Package resources not available: {e}")

    # Priority 2: Environment variable override
    env_path = os.environ.get("IDP_SYSTEM_DEFAULTS_DIR")
    if env_path:
        env_defaults_dir = Path(env_path)
        if env_defaults_dir.exists():
            logger.debug(f"Using env var system_defaults: {env_defaults_dir}")
            return env_defaults_dir

    # Priority 3: Legacy - relative to this file or project root
    current_file = Path(__file__)
    
    # Check relative to this file (system_defaults is sibling directory)
    sibling_dir = current_file.parent / "system_defaults"
    if sibling_dir.exists():
        logger.debug(f"Using sibling system_defaults: {sibling_dir}")
        return sibling_dir

    # Legacy fallback: config_library/system_defaults from various roots
    possible_roots = [
        current_file.parent.parent.parent.parent.parent.parent,  # From package
        Path.cwd(),  # Current working directory
        Path(os.environ.get("IDP_PROJECT_ROOT", "")),  # Environment variable
    ]

    for root in possible_roots:
        defaults_dir = root / "config_library" / "system_defaults"
        if defaults_dir.exists():
            logger.debug(f"Using legacy system_defaults: {defaults_dir}")
            return defaults_dir

    raise FileNotFoundError(
        "Could not locate system_defaults directory. "
        "The idp_common package should include this directory. "
        "If running from source, ensure you're in the project root or set IDP_SYSTEM_DEFAULTS_DIR."
    )


def load_yaml_file(path: Path) -> Dict[str, Any]:
    """
    Load a YAML file and return its contents as a dictionary.

    Args:
        path: Path to the YAML file

    Returns:
        Dictionary containing the YAML contents

    Raises:
        FileNotFoundError: If the file doesn't exist
        yaml.YAMLError: If the file contains invalid YAML
    """
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)

    return content if content is not None else {}


def _resolve_inheritance(
    config: Dict[str, Any],
    defaults_dir: Path,
    resolved_files: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Recursively resolve _inherits directive in a config.

    Supports both string (single file) and list (multiple files) inheritance.

    Args:
        config: Configuration with potential _inherits directive
        defaults_dir: Directory containing the defaults files
        resolved_files: Set of already resolved files (to prevent cycles)

    Returns:
        Merged configuration with all inheritance resolved
    """
    if resolved_files is None:
        resolved_files = set()

    # Get _inherits directive (can be string or list)
    inherits = config.pop("_inherits", None)

    if inherits is None:
        return config

    # Normalize to list
    if isinstance(inherits, str):
        inherits_list = [inherits]
    else:
        inherits_list = inherits

    # Start with empty config
    result: Dict[str, Any] = {}

    # Process each inherited file in order
    for inherit_file in inherits_list:
        if inherit_file in resolved_files:
            logger.warning(f"Circular inheritance detected: {inherit_file}")
            continue

        resolved_files.add(inherit_file)
        inherit_path = defaults_dir / inherit_file

        if not inherit_path.exists():
            raise FileNotFoundError(f"Inherited file not found: {inherit_path}")

        # Load inherited config and recursively resolve its inheritance
        inherited_config = load_yaml_file(inherit_path)
        inherited_config = _resolve_inheritance(
            inherited_config, defaults_dir, resolved_files.copy()
        )

        # Merge inherited config into result
        deep_update(result, inherited_config)

    # Finally, merge the current config on top (it has highest priority)
    deep_update(result, config)

    return result


def load_system_defaults(pattern: str = "pattern-2") -> Dict[str, Any]:
    """
    Load system defaults for a specific pattern.

    This function loads the pattern file and recursively resolves all
    inheritance directives. Patterns can inherit from:
    - A single base file: _inherits: base.yaml
    - Multiple modules: _inherits: [base-notes.yaml, base-classes.yaml, base-ocr.yaml, ...]

    Args:
        pattern: Pattern name (pattern-1, pattern-2, pattern-3)

    Returns:
        Dictionary containing the merged system defaults

    Raises:
        ValueError: If pattern is not valid
        FileNotFoundError: If defaults files don't exist
    """
    if pattern not in VALID_PATTERNS:
        raise ValueError(
            f"Invalid pattern '{pattern}'. Valid patterns: {VALID_PATTERNS}"
        )

    defaults_dir = get_system_defaults_dir()

    # Load pattern-specific defaults
    pattern_path = defaults_dir / f"{pattern}.yaml"
    pattern_config = load_yaml_file(pattern_path)

    # Recursively resolve all inheritance
    result = _resolve_inheritance(pattern_config, defaults_dir)

    return result


def merge_config_with_defaults(
    user_config: Dict[str, Any],
    pattern: str = "pattern-2",
    validate: bool = False,
) -> Dict[str, Any]:
    """
    Merge a user's config with system defaults.

    User values take precedence over defaults. Missing fields in user config
    are populated from system defaults.

    Args:
        user_config: User's configuration dictionary (may be partial)
        pattern: Pattern to use for defaults (pattern-1, pattern-2, pattern-3)
        validate: If True, validate the merged config with Pydantic

    Returns:
        Complete configuration dictionary with defaults applied

    Example:
        user_config = {
            "classification": {"model": "us.amazon.nova-lite-v1:0"},
            "classes": [...]
        }
        result = merge_config_with_defaults(user_config, "pattern-2")
        # Result has all fields populated from defaults, with user's model override
    """
    # Load system defaults
    defaults = load_system_defaults(pattern)

    # Deep merge user config on top of defaults
    result = deepcopy(defaults)
    deep_update(result, user_config)

    if validate:
        # Import here to avoid circular imports
        from idp_common.config.models import IDPConfig

        IDPConfig.model_validate(result)

    return result
