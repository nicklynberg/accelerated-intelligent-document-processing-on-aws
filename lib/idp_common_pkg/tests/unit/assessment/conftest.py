# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Pytest configuration for assessment tests.

These tests need strands modules mocked since they test the assessment service
which imports strands modules but the tests don't actually execute strands code.
"""

import sys
from unittest.mock import MagicMock

# Mock strands modules before any assessment imports
# This allows tests to import assessment code without requiring strands package
sys.modules["strands"] = MagicMock()
sys.modules["strands.agent"] = MagicMock()
sys.modules["strands.agent.conversation_manager"] = MagicMock()
sys.modules["strands.models"] = MagicMock()
sys.modules["strands.models.bedrock"] = MagicMock()
sys.modules["strands.types"] = MagicMock()
sys.modules["strands.types.content"] = MagicMock()
sys.modules["strands.types.media"] = MagicMock()
sys.modules["strands.hooks"] = MagicMock()
sys.modules["strands.hooks.events"] = MagicMock()
