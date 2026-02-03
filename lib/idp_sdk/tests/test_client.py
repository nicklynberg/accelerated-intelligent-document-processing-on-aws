# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for IDP SDK Client.

These tests focus on the SDK interface and models without requiring
full idp_cli dependencies.
"""

from datetime import datetime

import pytest


class TestIDPClientInit:
    """Test IDPClient initialization."""

    def test_init_without_params(self):
        """Client can be created without parameters."""
        from idp_sdk import IDPClient

        client = IDPClient()
        assert client.stack_name is None
        assert client.region is None

    def test_init_with_stack_name(self):
        """Client can be created with stack name."""
        from idp_sdk import IDPClient

        client = IDPClient(stack_name="test-stack")
        assert client.stack_name == "test-stack"

    def test_init_with_region(self):
        """Client can be created with region."""
        from idp_sdk import IDPClient

        client = IDPClient(region="us-east-1")
        assert client.region == "us-east-1"

    def test_init_with_all_params(self):
        """Client can be created with all parameters."""
        from idp_sdk import IDPClient

        client = IDPClient(stack_name="test-stack", region="eu-west-1")
        assert client.stack_name == "test-stack"
        assert client.region == "eu-west-1"

    def test_set_stack_name(self):
        """Stack name can be set after initialization."""
        from idp_sdk import IDPClient

        client = IDPClient()
        client.stack_name = "new-stack"
        assert client.stack_name == "new-stack"

    def test_set_stack_name_clears_cache(self):
        """Setting stack name clears resource cache."""
        from idp_sdk import IDPClient

        client = IDPClient(stack_name="old-stack")
        client._resources_cache = {"key": "value"}
        client.stack_name = "new-stack"
        assert client._resources_cache is None


class TestRequireStack:
    """Test _require_stack method."""

    def test_require_stack_with_default(self):
        """Returns default stack name when set."""
        from idp_sdk import IDPClient

        client = IDPClient(stack_name="default-stack")
        assert client._require_stack() == "default-stack"

    def test_require_stack_with_override(self):
        """Override takes precedence over default."""
        from idp_sdk import IDPClient

        client = IDPClient(stack_name="default-stack")
        assert client._require_stack("override-stack") == "override-stack"

    def test_require_stack_raises_without_stack(self):
        """Raises error when no stack available."""
        from idp_sdk import IDPClient, IDPConfigurationError

        client = IDPClient()
        with pytest.raises(IDPConfigurationError) as exc_info:
            client._require_stack()
        assert "stack_name is required" in str(exc_info.value)


class TestModels:
    """Test Pydantic models."""

    def test_pattern_enum(self):
        """Pattern enum has correct values."""
        from idp_sdk import Pattern

        assert Pattern.PATTERN_1.value == "pattern-1"
        assert Pattern.PATTERN_2.value == "pattern-2"
        assert Pattern.PATTERN_3.value == "pattern-3"

    def test_rerun_step_enum(self):
        """RerunStep enum has correct values."""
        from idp_sdk import RerunStep

        assert RerunStep.CLASSIFICATION.value == "classification"
        assert RerunStep.EXTRACTION.value == "extraction"

    def test_document_status_enum(self):
        """DocumentStatus enum has correct values."""
        from idp_sdk import DocumentStatus

        assert DocumentStatus.QUEUED.value == "QUEUED"
        assert DocumentStatus.COMPLETED.value == "COMPLETED"
        assert DocumentStatus.FAILED.value == "FAILED"

    def test_batch_result_creation(self):
        """BatchResult can be created with required fields."""
        from idp_sdk import BatchResult

        result = BatchResult(
            batch_id="test-batch",
            document_ids=["doc1", "doc2"],
            queued=2,
            uploaded=2,
            failed=0,
            source="./test/",
            output_prefix="test",
            timestamp=datetime.now(),
        )

        assert result.batch_id == "test-batch"
        assert len(result.document_ids) == 2
        assert result.documents_queued == 2

    def test_manifest_result_creation(self):
        """ManifestResult can be created."""
        from idp_sdk import ManifestResult

        result = ManifestResult(
            output_path="manifest.csv",
            document_count=10,
            baselines_matched=5,
            test_set_created=False,
            test_set_name=None,
        )

        assert result.document_count == 10
        assert result.baselines_matched == 5

    def test_validation_result_creation(self):
        """ValidationResult can be created."""
        from idp_sdk import ValidationResult

        result = ValidationResult(
            valid=True, error=None, document_count=5, has_baselines=True
        )

        assert result.valid is True
        assert result.has_baselines is True

    def test_config_create_result_creation(self):
        """ConfigCreateResult can be created."""
        from idp_sdk import ConfigCreateResult

        result = ConfigCreateResult(
            yaml_content="key: value", output_path="config.yaml"
        )

        assert result.yaml_content == "key: value"
        assert result.output_path == "config.yaml"

    def test_config_validation_result_creation(self):
        """ConfigValidationResult can be created."""
        from idp_sdk import ConfigValidationResult

        result = ConfigValidationResult(
            valid=False, errors=["Error 1", "Error 2"], warnings=["Warning 1"]
        )

        assert result.valid is False
        assert len(result.errors) == 2
        assert len(result.warnings) == 1

    def test_single_document_deletion_result_creation(self):
        """SingleDocumentDeletionResult can be created."""
        from idp_sdk import SingleDocumentDeletionResult

        result = SingleDocumentDeletionResult(
            success=True,
            object_key="batch-123/doc1.pdf",
            deleted={
                "input_file": True,
                "output_files": 5,
                "list_entries": True,
                "document_record": True,
            },
            errors=[],
        )

        assert result.success is True
        assert result.object_key == "batch-123/doc1.pdf"
        assert result.deleted["input_file"] is True
        assert result.deleted["output_files"] == 5
        assert len(result.errors) == 0

    def test_document_deletion_result_creation(self):
        """DocumentDeletionResult can be created."""
        from idp_sdk import DocumentDeletionResult, SingleDocumentDeletionResult

        single_result = SingleDocumentDeletionResult(
            success=True,
            object_key="batch-123/doc1.pdf",
            deleted={"input_file": True},
            errors=[],
        )

        result = DocumentDeletionResult(
            success=True,
            deleted_count=2,
            failed_count=0,
            total_count=2,
            dry_run=False,
            results=[single_result],
        )

        assert result.success is True
        assert result.deleted_count == 2
        assert result.failed_count == 0
        assert result.total_count == 2
        assert result.dry_run is False
        assert len(result.results) == 1

    def test_document_deletion_result_dry_run(self):
        """DocumentDeletionResult supports dry_run flag."""
        from idp_sdk import DocumentDeletionResult

        result = DocumentDeletionResult(
            success=True,
            deleted_count=0,
            failed_count=0,
            total_count=5,
            dry_run=True,
            results=[],
        )

        assert result.dry_run is True
        assert result.total_count == 5


class TestExceptions:
    """Test exception hierarchy."""

    def test_idp_error_base(self):
        """All exceptions inherit from IDPError."""
        from idp_sdk import (
            IDPConfigurationError,
            IDPError,
            IDPProcessingError,
            IDPResourceNotFoundError,
            IDPStackError,
            IDPTimeoutError,
            IDPValidationError,
        )

        assert issubclass(IDPConfigurationError, IDPError)
        assert issubclass(IDPStackError, IDPError)
        assert issubclass(IDPProcessingError, IDPError)
        assert issubclass(IDPValidationError, IDPError)
        assert issubclass(IDPResourceNotFoundError, IDPError)
        assert issubclass(IDPTimeoutError, IDPError)

    def test_exception_message(self):
        """Exceptions preserve message."""
        from idp_sdk import IDPConfigurationError

        exc = IDPConfigurationError("test message")
        assert str(exc) == "test message"

    def test_exception_inherits_from_exception(self):
        """IDPError inherits from Exception."""
        from idp_sdk import IDPError

        assert issubclass(IDPError, Exception)


class TestExports:
    """Test that all expected symbols are exported."""

    def test_client_exported(self):
        """IDPClient is exported."""
        from idp_sdk import IDPClient

        assert IDPClient is not None

    def test_exceptions_exported(self):
        """All exceptions are exported."""
        from idp_sdk import (
            IDPConfigurationError,
            IDPError,
            IDPProcessingError,
            IDPResourceNotFoundError,
            IDPStackError,
            IDPTimeoutError,
            IDPValidationError,
        )

        assert all(
            [
                IDPError,
                IDPConfigurationError,
                IDPStackError,
                IDPProcessingError,
                IDPValidationError,
                IDPResourceNotFoundError,
                IDPTimeoutError,
            ]
        )

    def test_enums_exported(self):
        """All enums are exported."""
        from idp_sdk import (
            DocumentStatus,
            Pattern,
            RerunStep,
            StackStatus,
        )

        assert all([StackStatus, DocumentStatus, Pattern, RerunStep])

    def test_models_exported(self):
        """All models are exported."""
        from idp_sdk import (
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
            DocumentStatusInfo,
            DownloadResult,
            LoadTestResult,
            ManifestDocument,
            ManifestResult,
            RerunResult,
            SingleDocumentDeletionResult,
            StackResources,
            StopWorkflowsResult,
            ValidationResult,
        )

        assert all(
            [
                DeploymentResult,
                DeletionResult,
                BatchResult,
                BatchStatusResult,
                DocumentStatusInfo,
                DocumentDeletionResult,
                SingleDocumentDeletionResult,
                RerunResult,
                DownloadResult,
                ManifestDocument,
                ManifestResult,
                ValidationResult,
                BatchInfo,
                StopWorkflowsResult,
                LoadTestResult,
                ConfigCreateResult,
                ConfigValidationResult,
                ConfigDownloadResult,
                ConfigUploadResult,
                StackResources,
            ]
        )

    def test_version_exported(self):
        """Version is exported."""
        from idp_sdk import __version__

        assert __version__ == "0.1.0"
