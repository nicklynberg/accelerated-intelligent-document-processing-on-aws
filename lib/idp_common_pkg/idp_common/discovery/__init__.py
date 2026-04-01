# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Discovery module for IDP document class discovery.

Provides both single-document discovery (ClassesDiscovery) and
multi-document discovery with clustering and agentic analysis.
"""

from idp_common.discovery.classes_discovery import ClassesDiscovery

__all__ = [
    "ClassesDiscovery",
]
