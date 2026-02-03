# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDP SDK - Python SDK for IDP Accelerator

Provides programmatic access to document processing capabilities.

Example:
    >>> from idp_sdk import IDPClient
    >>>
    >>> # For stack-dependent operations
    >>> client = IDPClient(stack_name="my-idp-stack", region="us-west-2")
    >>> result = client.run_inference(source="./documents/")
    >>> status = client.get_status(batch_id=result.batch_id)
    >>>
    >>> # For stack-independent operations
    >>> client = IDPClient()
    >>> manifest = client.generate_manifest(directory="./docs/")
    >>> config = client.config_create(features="min")
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
    BatchInfo,
    BatchResult,
    BatchStatusResult,
    ConfigCreateResult,
    ConfigDownloadResult,
    ConfigUploadResult,
    ConfigValidationResult,
    DeletionResult,
    DeploymentResult,
    DocumentDeletionResult,
    DocumentStatus,
    DocumentStatusInfo,
    DownloadResult,
    LoadTestResult,
    ManifestDocument,
    ManifestResult,
    Pattern,
    RerunResult,
    RerunStep,
    SingleDocumentDeletionResult,
    StackResources,
    StackStatus,
    StopWorkflowsResult,
    ValidationResult,
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
    "StackStatus",
    "DocumentStatus",
    "Pattern",
    "RerunStep",
    # Models
    "DeploymentResult",
    "DeletionResult",
    "BatchResult",
    "BatchStatusResult",
    "DocumentStatusInfo",
    "DocumentDeletionResult",
    "SingleDocumentDeletionResult",
    "RerunResult",
    "DownloadResult",
    "ManifestDocument",
    "ManifestResult",
    "ValidationResult",
    "BatchInfo",
    "StopWorkflowsResult",
    "LoadTestResult",
    "ConfigCreateResult",
    "ConfigValidationResult",
    "ConfigDownloadResult",
    "ConfigUploadResult",
    "StackResources",
]
