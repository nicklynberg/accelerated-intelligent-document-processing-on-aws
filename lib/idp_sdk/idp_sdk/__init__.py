# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDP SDK - Python SDK for IDP Accelerator

Provides programmatic access to document processing capabilities.

Example:
    >>> from idp_sdk import IDPClient
    >>>
    >>> # Stack operations
    >>> client = IDPClient()
    >>> client.stack.deploy(stack_name="my-stack", pattern="pattern-2")
    >>>
    >>> # Batch operations
    >>> client = IDPClient(stack_name="my-stack", region="us-west-2")
    >>> result = client.batch.run(source="./documents/")
    >>> status = client.batch.get_status(batch_id=result.batch_id)
    >>>
    >>> # Config operations (no stack required)
    >>> client = IDPClient()
    >>> client.config.create(features="min", output="config.yaml")
"""

from .client import IDPClient
from .exceptions import (
    IDPConfigurationError,
    IDPError,
    IDPProcessingError,
    IDPResourceNotFoundError,
    IDPStackError,
    IDPTimeoutError,
    IDPValidationError,
)
from .models import (
    BatchDeletionResult,
    BatchDownloadResult,
    BatchInfo,
    BatchRerunResult,
    BatchResult,
    BatchStatus,
    ConfigCreateResult,
    ConfigDownloadResult,
    ConfigUploadResult,
    ConfigValidationResult,
    DocumentDeletionResult,
    DocumentDownloadResult,
    DocumentRerunResult,
    DocumentState,
    DocumentStatus,
    DocumentUploadResult,
    LoadTestResult,
    ManifestDocument,
    ManifestResult,
    ManifestValidationResult,
    Pattern,
    RerunStep,
    StackDeletionResult,
    StackDeploymentResult,
    StackResources,
    StackState,
    StopWorkflowsResult,
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "IDPClient",
    # Exceptions
    "IDPError",
    "IDPConfigurationError",
    "IDPStackError",
    "IDPProcessingError",
    "IDPValidationError",
    "IDPResourceNotFoundError",
    "IDPTimeoutError",
    # Enums
    "StackState",
    "DocumentState",
    "Pattern",
    "RerunStep",
    # Stack models
    "StackDeploymentResult",
    "StackDeletionResult",
    "StackResources",
    # Batch models
    "BatchResult",
    "BatchStatus",
    "BatchInfo",
    "BatchRerunResult",
    "BatchDownloadResult",
    "BatchDeletionResult",
    # Document models
    "DocumentStatus",
    "DocumentUploadResult",
    "DocumentDownloadResult",
    "DocumentRerunResult",
    "DocumentDeletionResult",
    # Config models
    "ConfigCreateResult",
    "ConfigValidationResult",
    "ConfigDownloadResult",
    "ConfigUploadResult",
    # Manifest models
    "ManifestDocument",
    "ManifestResult",
    "ManifestValidationResult",
    # Testing models
    "StopWorkflowsResult",
    "LoadTestResult",
]
