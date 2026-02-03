# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDP SDK Models

Pydantic models for typed responses from SDK operations.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StackStatus(str, Enum):
    """CloudFormation stack status."""

    CREATE_IN_PROGRESS = "CREATE_IN_PROGRESS"
    CREATE_COMPLETE = "CREATE_COMPLETE"
    CREATE_FAILED = "CREATE_FAILED"
    UPDATE_IN_PROGRESS = "UPDATE_IN_PROGRESS"
    UPDATE_COMPLETE = "UPDATE_COMPLETE"
    UPDATE_FAILED = "UPDATE_FAILED"
    DELETE_IN_PROGRESS = "DELETE_IN_PROGRESS"
    DELETE_COMPLETE = "DELETE_COMPLETE"
    DELETE_FAILED = "DELETE_FAILED"
    ROLLBACK_IN_PROGRESS = "ROLLBACK_IN_PROGRESS"
    ROLLBACK_COMPLETE = "ROLLBACK_COMPLETE"
    UPDATE_ROLLBACK_IN_PROGRESS = "UPDATE_ROLLBACK_IN_PROGRESS"
    UPDATE_ROLLBACK_COMPLETE = "UPDATE_ROLLBACK_COMPLETE"


class DocumentStatus(str, Enum):
    """Document processing status."""

    QUEUED = "QUEUED"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    OCR = "OCR"
    CLASSIFYING = "CLASSIFYING"
    EXTRACTING = "EXTRACTING"
    ASSESSING = "ASSESSING"
    SUMMARIZING = "SUMMARIZING"
    EVALUATING = "EVALUATING"
    POSTPROCESSING = "POSTPROCESSING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    UNKNOWN = "UNKNOWN"


class Pattern(str, Enum):
    """IDP processing patterns."""

    PATTERN_1 = "pattern-1"
    PATTERN_2 = "pattern-2"
    PATTERN_3 = "pattern-3"


class RerunStep(str, Enum):
    """Pipeline steps for rerun operations."""

    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"


# ============================================================================
# Deployment Models
# ============================================================================


class DeploymentResult(BaseModel):
    """Result of a stack deployment operation."""

    success: bool = Field(description="Whether the operation succeeded")
    operation: str = Field(description="Type of operation (CREATE, UPDATE)")
    status: str = Field(description="Final stack status")
    stack_name: str = Field(description="CloudFormation stack name")
    stack_id: Optional[str] = Field(default=None, description="CloudFormation stack ID")
    outputs: Dict[str, str] = Field(
        default_factory=dict, description="Stack outputs (URLs, bucket names, etc.)"
    )
    error: Optional[str] = Field(default=None, description="Error message if failed")


class DeletionResult(BaseModel):
    """Result of a stack deletion operation."""

    success: bool = Field(description="Whether the deletion succeeded")
    status: str = Field(description="Final status")
    stack_name: str = Field(description="CloudFormation stack name")
    stack_id: Optional[str] = Field(default=None, description="CloudFormation stack ID")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    cleanup_result: Optional[Dict[str, Any]] = Field(
        default=None, description="Results of force-delete cleanup phase"
    )


# ============================================================================
# Batch Processing Models
# ============================================================================


class BatchResult(BaseModel):
    """Result of a batch processing operation."""

    batch_id: str = Field(description="Unique batch identifier")
    document_ids: List[str] = Field(description="List of document IDs in the batch")
    documents_queued: int = Field(
        alias="queued", description="Number of documents queued"
    )
    documents_uploaded: int = Field(
        alias="uploaded", description="Number of files uploaded"
    )
    documents_failed: int = Field(
        alias="failed", description="Number of documents that failed to queue"
    )
    baselines_uploaded: int = Field(
        default=0, description="Number of baseline files uploaded for evaluation"
    )
    source: str = Field(description="Source path (manifest, directory, or S3 URI)")
    output_prefix: str = Field(description="Output prefix for results")
    timestamp: datetime = Field(description="Batch submission timestamp")

    model_config = ConfigDict(populate_by_name=True)


class DocumentStatusInfo(BaseModel):
    """Status information for a single document."""

    document_id: str = Field(description="Document identifier (S3 key)")
    status: DocumentStatus = Field(description="Current processing status")
    start_time: Optional[datetime] = Field(
        default=None, description="Processing start time"
    )
    end_time: Optional[datetime] = Field(
        default=None, description="Processing end time"
    )
    duration_seconds: Optional[float] = Field(
        default=None, description="Processing duration in seconds"
    )
    num_pages: Optional[int] = Field(default=None, description="Number of pages")
    num_sections: Optional[int] = Field(
        default=None, description="Number of extracted sections"
    )
    error: Optional[str] = Field(default=None, description="Error message if failed")


class BatchStatusResult(BaseModel):
    """Status information for a batch of documents."""

    batch_id: str = Field(description="Batch identifier")
    documents: List[DocumentStatusInfo] = Field(description="Status of each document")
    total: int = Field(description="Total number of documents")
    completed: int = Field(description="Number of completed documents")
    failed: int = Field(description="Number of failed documents")
    in_progress: int = Field(description="Number of documents in progress")
    queued: int = Field(description="Number of queued documents")
    success_rate: float = Field(description="Completion success rate (0-1)")
    all_complete: bool = Field(description="Whether all documents are complete")
    elapsed_seconds: Optional[float] = Field(
        default=None, description="Total elapsed time"
    )


class RerunResult(BaseModel):
    """Result of a rerun operation."""

    documents_queued: int = Field(description="Number of documents queued for rerun")
    documents_failed: int = Field(
        description="Number of documents that failed to queue"
    )
    failed_documents: List[Dict[str, str]] = Field(
        default_factory=list, description="Details of failed documents"
    )
    step: RerunStep = Field(description="Pipeline step being rerun")


# ============================================================================
# Download Models
# ============================================================================


class DownloadResult(BaseModel):
    """Result of a download operation."""

    files_downloaded: int = Field(description="Number of files downloaded")
    documents_downloaded: int = Field(description="Number of documents with downloads")
    output_dir: str = Field(description="Local output directory path")


# ============================================================================
# Manifest Models
# ============================================================================


class ManifestDocument(BaseModel):
    """A document entry in a manifest."""

    document_path: str = Field(description="Path to document (local or S3 URI)")
    baseline_source: Optional[str] = Field(
        default=None, description="Path to baseline for evaluation"
    )


class ManifestResult(BaseModel):
    """Result of manifest generation."""

    output_path: Optional[str] = Field(
        default=None, description="Path to generated manifest file"
    )
    document_count: int = Field(description="Number of documents in manifest")
    baselines_matched: int = Field(
        default=0, description="Number of documents with baselines"
    )
    test_set_created: bool = Field(
        default=False, description="Whether a test set was created"
    )
    test_set_name: Optional[str] = Field(
        default=None, description="Name of created test set"
    )


class ValidationResult(BaseModel):
    """Result of manifest validation."""

    valid: bool = Field(description="Whether the manifest is valid")
    error: Optional[str] = Field(default=None, description="Error message if invalid")
    document_count: Optional[int] = Field(
        default=None, description="Number of documents"
    )
    has_baselines: bool = Field(
        default=False, description="Whether manifest includes baselines"
    )


# ============================================================================
# Batch List Models
# ============================================================================


class BatchInfo(BaseModel):
    """Information about a batch."""

    batch_id: str = Field(description="Batch identifier")
    document_ids: List[str] = Field(description="Document IDs in the batch")
    queued: int = Field(description="Number of documents queued")
    failed: int = Field(description="Number of documents failed")
    timestamp: str = Field(description="Batch creation timestamp")


# ============================================================================
# Workflow Control Models
# ============================================================================


class StopWorkflowsResult(BaseModel):
    """Result of stopping workflows."""

    executions_stopped: Optional[Dict[str, Any]] = Field(
        default=None, description="Details of stopped executions"
    )
    documents_aborted: Optional[Dict[str, Any]] = Field(
        default=None, description="Details of aborted documents"
    )
    queue_purged: bool = Field(default=False, description="Whether queue was purged")


class LoadTestResult(BaseModel):
    """Result of a load test."""

    success: bool = Field(description="Whether load test completed")
    total_files: int = Field(description="Total files submitted")
    duration_minutes: int = Field(description="Test duration in minutes")
    error: Optional[str] = Field(default=None, description="Error if failed")


# ============================================================================
# Configuration Models
# ============================================================================


class ConfigCreateResult(BaseModel):
    """Result of config template creation."""

    yaml_content: str = Field(description="Generated YAML configuration content")
    output_path: Optional[str] = Field(
        default=None, description="Path where config was written"
    )


class ConfigValidationResult(BaseModel):
    """Result of configuration validation."""

    valid: bool = Field(description="Whether configuration is valid")
    errors: List[str] = Field(default_factory=list, description="Validation errors")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    merged_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Merged configuration (if show_merged=True)"
    )


class ConfigDownloadResult(BaseModel):
    """Result of config download."""

    config: Dict[str, Any] = Field(description="Configuration dictionary")
    yaml_content: str = Field(description="Configuration as YAML string")
    output_path: Optional[str] = Field(
        default=None, description="Path where config was written"
    )


class ConfigUploadResult(BaseModel):
    """Result of config upload."""

    success: bool = Field(description="Whether upload succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================================================
# Document Deletion Models
# ============================================================================


class SingleDocumentDeletionResult(BaseModel):
    """Result of deleting a single document."""

    success: bool = Field(description="Whether deletion succeeded")
    object_key: str = Field(description="Document object key (S3 path)")
    deleted: Dict[str, Any] = Field(
        default_factory=dict,
        description="Details of deleted items (input_file, output_files, list_entries, document_record)",
    )
    errors: List[str] = Field(default_factory=list, description="Error messages if any")


class DocumentDeletionResult(BaseModel):
    """Result of a document deletion operation."""

    success: bool = Field(description="Whether all deletions succeeded")
    deleted_count: int = Field(description="Number of documents successfully deleted")
    failed_count: int = Field(description="Number of documents that failed to delete")
    total_count: int = Field(description="Total number of documents attempted")
    dry_run: bool = Field(
        default=False, description="Whether this was a dry run (no actual deletions)"
    )
    results: List[SingleDocumentDeletionResult] = Field(
        default_factory=list, description="Per-document deletion results"
    )


# ============================================================================
# Stack Resource Models
# ============================================================================


class StackResources(BaseModel):
    """Stack resources discovered from CloudFormation."""

    input_bucket: str = Field(alias="InputBucket", description="S3 input bucket name")
    output_bucket: str = Field(
        alias="OutputBucket", description="S3 output bucket name"
    )
    configuration_bucket: Optional[str] = Field(
        alias="ConfigurationBucket", default=None, description="Configuration bucket"
    )
    evaluation_baseline_bucket: Optional[str] = Field(
        alias="EvaluationBaselineBucket", default=None, description="Baseline bucket"
    )
    test_set_bucket: Optional[str] = Field(
        alias="TestSetBucket", default=None, description="Test set bucket"
    )
    document_queue_url: Optional[str] = Field(
        alias="DocumentQueueUrl", default=None, description="SQS queue URL"
    )
    state_machine_arn: Optional[str] = Field(
        alias="StateMachineArn", default=None, description="Step Functions ARN"
    )
    documents_table: Optional[str] = Field(
        alias="DocumentsTable", default=None, description="DynamoDB tracking table"
    )

    model_config = ConfigDict(populate_by_name=True)
