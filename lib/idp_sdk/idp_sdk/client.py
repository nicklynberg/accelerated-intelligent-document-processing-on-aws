# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDP SDK Client

Main client class for programmatic access to IDP Accelerator capabilities.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from .exceptions import (
    IDPConfigurationError,
    IDPProcessingError,
    IDPResourceNotFoundError,
    IDPStackError,
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
    DocumentStatusInfo,
    DownloadResult,
    LoadTestResult,
    ManifestResult,
    Pattern,
    RerunResult,
    RerunStep,
    SingleDocumentDeletionResult,
    StackResources,
    StopWorkflowsResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class IDPClient:
    """
    Python SDK client for IDP Accelerator.

    Provides programmatic access to all IDP capabilities including:
    - Stack deployment and management
    - Batch document processing
    - Progress monitoring
    - Configuration management
    - Test set operations

    Examples:
        # For stack-dependent operations
        >>> client = IDPClient(stack_name="my-idp-stack", region="us-west-2")
        >>> result = client.run_inference(source="./documents/")
        >>> status = client.get_status(batch_id=result.batch_id)

        # For stack-independent operations
        >>> client = IDPClient()
        >>> manifest = client.generate_manifest(directory="./docs/")
        >>> config = client.config_create(features="min")

        # Pass stack per-operation
        >>> client = IDPClient()
        >>> client.deploy(stack_name="new-stack", pattern="pattern-2", ...)
    """

    def __init__(
        self,
        stack_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """
        Initialize IDP SDK client.

        Args:
            stack_name: CloudFormation stack name (optional, can be passed per-operation)
            region: AWS region (optional, defaults to boto3 default)
        """
        self._stack_name = stack_name
        self._region = region
        self._resources_cache: Optional[Dict[str, str]] = None

    @property
    def stack_name(self) -> Optional[str]:
        """Current default stack name."""
        return self._stack_name

    @stack_name.setter
    def stack_name(self, value: str):
        """Set default stack name and clear resource cache."""
        self._stack_name = value
        self._resources_cache = None

    @property
    def region(self) -> Optional[str]:
        """Current AWS region."""
        return self._region

    def _require_stack(self, stack_name: Optional[str] = None) -> str:
        """
        Ensure stack_name is available.

        Args:
            stack_name: Override stack name

        Returns:
            Stack name to use

        Raises:
            IDPConfigurationError: If no stack name available
        """
        name = stack_name or self._stack_name
        if not name:
            raise IDPConfigurationError(
                "stack_name is required for this operation. "
                "Either pass it to the method or set it when creating IDPClient."
            )
        return name

    def _get_stack_resources(self, stack_name: Optional[str] = None) -> Dict[str, str]:
        """Get stack resources with caching."""
        from idp_cli.stack_info import StackInfo

        name = self._require_stack(stack_name)

        # Use cache if available and stack name matches
        if self._resources_cache and stack_name is None:
            return self._resources_cache

        stack_info = StackInfo(name, self._region)
        if not stack_info.validate_stack():
            raise IDPStackError(
                f"Stack '{name}' is not in a valid state for operations"
            )

        resources = stack_info.get_resources()

        # Cache only if using default stack
        if stack_name is None:
            self._resources_cache = resources

        return resources

    # =========================================================================
    # Deployment Operations
    # =========================================================================

    def deploy(
        self,
        stack_name: Optional[str] = None,
        pattern: Optional[Union[str, Pattern]] = None,
        admin_email: Optional[str] = None,
        template_url: Optional[str] = None,
        from_code: Optional[str] = None,
        custom_config: Optional[str] = None,
        max_concurrent: Optional[int] = None,
        log_level: Optional[str] = None,
        enable_hitl: Optional[bool] = None,
        pattern_config: Optional[str] = None,
        parameters: Optional[Dict[str, str]] = None,
        wait: bool = True,
        no_rollback: bool = False,
        role_arn: Optional[str] = None,
    ) -> DeploymentResult:
        """
        Deploy or update an IDP CloudFormation stack.

        Args:
            stack_name: CloudFormation stack name (uses default if not provided)
            pattern: IDP pattern (pattern-1, pattern-2, pattern-3) - required for new stacks
            admin_email: Admin user email - required for new stacks
            template_url: URL to CloudFormation template in S3
            from_code: Path to project root for building from source
            custom_config: Path to local config file or S3 URI
            max_concurrent: Maximum concurrent workflows
            log_level: Logging level (DEBUG, INFO, WARN, ERROR)
            enable_hitl: Enable Human-in-the-Loop
            pattern_config: Pattern configuration preset
            parameters: Additional parameters as dict
            wait: Wait for operation to complete (default: True)
            no_rollback: Disable rollback on failure
            role_arn: CloudFormation service role ARN

        Returns:
            DeploymentResult with status and outputs

        Raises:
            IDPConfigurationError: If required parameters missing
            IDPStackError: If deployment fails
        """
        from idp_cli.deployer import StackDeployer, build_parameters

        name = self._require_stack(stack_name)

        # Convert Pattern enum to string if needed
        pattern_str = pattern.value if isinstance(pattern, Pattern) else pattern

        # Build parameters
        additional_params = parameters or {}
        cfn_parameters = build_parameters(
            pattern=pattern_str,
            admin_email=admin_email,
            max_concurrent=max_concurrent,
            log_level=log_level,
            enable_hitl="true" if enable_hitl else None,
            pattern_config=pattern_config,
            custom_config=custom_config,
            additional_params=additional_params,
            region=self._region,
            stack_name=name,
        )

        deployer = StackDeployer(region=self._region)

        try:
            # Handle from_code build
            template_path = None
            if from_code:
                # Import the build function
                import os
                import subprocess
                import sys

                import boto3

                publish_script = os.path.join(from_code, "publish.py")
                if not os.path.isfile(publish_script):
                    raise IDPConfigurationError(f"publish.py not found in {from_code}")

                # Get account ID and build
                sts = boto3.client("sts", region_name=self._region)
                account_id = sts.get_caller_identity()["Account"]
                cfn_bucket_basename = f"idp-accelerator-artifacts-{account_id}"
                cfn_prefix = "idp-sdk"

                cmd = [
                    sys.executable,
                    publish_script,
                    cfn_bucket_basename,
                    cfn_prefix,
                    self._region or "us-west-2",
                ]
                result = subprocess.run(
                    cmd, cwd=from_code, capture_output=True, text=True
                )

                if result.returncode != 0:
                    raise IDPStackError(f"Build failed: {result.stderr}")

                template_path = os.path.join(from_code, ".aws-sam", "idp-main.yaml")

            # Deploy
            if template_path:
                result = deployer.deploy_stack(
                    stack_name=name,
                    template_path=template_path,
                    parameters=cfn_parameters,
                    wait=wait,
                    no_rollback=no_rollback,
                    role_arn=role_arn,
                )
            else:
                result = deployer.deploy_stack(
                    stack_name=name,
                    template_url=template_url,
                    parameters=cfn_parameters,
                    wait=wait,
                    no_rollback=no_rollback,
                    role_arn=role_arn,
                )

            return DeploymentResult(
                success=result.get("success", False),
                operation=result.get("operation", "UNKNOWN"),
                status=result.get("status", "UNKNOWN"),
                stack_name=name,
                stack_id=result.get("stack_id"),
                outputs=result.get("outputs", {}),
                error=result.get("error"),
            )

        except Exception as e:
            raise IDPStackError(f"Deployment failed: {e}") from e

    def delete(
        self,
        stack_name: Optional[str] = None,
        empty_buckets: bool = False,
        force_delete_all: bool = False,
        wait: bool = True,
    ) -> DeletionResult:
        """
        Delete an IDP CloudFormation stack.

        Args:
            stack_name: CloudFormation stack name (uses default if not provided)
            empty_buckets: Empty S3 buckets before deletion
            force_delete_all: Force delete ALL remaining resources
            wait: Wait for deletion to complete

        Returns:
            DeletionResult with status
        """
        from idp_cli.deployer import StackDeployer

        name = self._require_stack(stack_name)
        deployer = StackDeployer(region=self._region)

        try:
            result = deployer.delete_stack(
                stack_name=name,
                empty_buckets=empty_buckets,
                wait=wait,
            )

            cleanup_result = None
            if force_delete_all:
                stack_identifier = result.get("stack_id", name)
                cleanup_result = deployer.cleanup_retained_resources(stack_identifier)

            return DeletionResult(
                success=result.get("success", False),
                status=result.get("status", "UNKNOWN"),
                stack_name=name,
                stack_id=result.get("stack_id"),
                error=result.get("error"),
                cleanup_result=cleanup_result,
            )

        except Exception as e:
            raise IDPStackError(f"Deletion failed: {e}") from e

    # =========================================================================
    # Batch Processing Operations
    # =========================================================================

    def run_inference(
        self,
        source: Optional[str] = None,
        manifest: Optional[str] = None,
        directory: Optional[str] = None,
        s3_uri: Optional[str] = None,
        test_set: Optional[str] = None,
        stack_name: Optional[str] = None,
        batch_id: Optional[str] = None,
        batch_prefix: str = "sdk-batch",
        file_pattern: str = "*.pdf",
        recursive: bool = True,
        number_of_files: Optional[int] = None,
        config_path: Optional[str] = None,
        context: Optional[str] = None,
    ) -> BatchResult:
        """
        Run inference on a batch of documents.

        Specify documents using ONE of: source, manifest, directory, s3_uri, or test_set.
        The 'source' parameter auto-detects the type based on the path.

        Args:
            source: Auto-detect source type (local dir, manifest file, or S3 URI)
            manifest: Path to manifest file (CSV or JSON)
            directory: Local directory containing documents
            s3_uri: S3 URI to documents
            test_set: Test set ID from test set bucket
            stack_name: CloudFormation stack name (uses default if not provided)
            batch_id: Custom batch ID (auto-generated if not provided)
            batch_prefix: Prefix for auto-generated batch ID
            file_pattern: File pattern for directory/S3 scanning
            recursive: Include subdirectories
            number_of_files: Limit number of files to process
            config_path: Path to configuration YAML file
            context: Context description for test runs

        Returns:
            BatchResult with batch_id and document_ids

        Raises:
            IDPConfigurationError: If no source specified
            IDPProcessingError: If processing fails
        """
        from idp_cli.batch_processor import BatchProcessor

        name = self._require_stack(stack_name)

        # Auto-detect source type
        if source:
            import os

            if source.startswith("s3://"):
                s3_uri = source
            elif os.path.isdir(source):
                directory = source
            elif os.path.isfile(source):
                manifest = source
            else:
                raise IDPConfigurationError(
                    f"Source '{source}' not found or unrecognized format"
                )

        # Validate exactly one source
        sources = [manifest, directory, s3_uri, test_set]
        if sum(1 for s in sources if s) != 1:
            raise IDPConfigurationError(
                "Specify exactly one source: manifest, directory, s3_uri, or test_set"
            )

        try:
            processor = BatchProcessor(
                stack_name=name,
                config_path=config_path,
                region=self._region,
            )

            if test_set:
                result = self._process_test_set(
                    processor, test_set, context, number_of_files
                )
            elif manifest:
                result = processor.process_batch(
                    manifest_path=manifest,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                    number_of_files=number_of_files,
                )
            elif directory:
                result = processor.process_batch_from_directory(
                    dir_path=directory,
                    file_pattern=file_pattern,
                    recursive=recursive,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                    number_of_files=number_of_files,
                )
            else:  # s3_uri
                result = processor.process_batch_from_s3_uri(
                    s3_uri=s3_uri,
                    file_pattern=file_pattern,
                    recursive=recursive,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                )

            return BatchResult(
                batch_id=result["batch_id"],
                document_ids=result["document_ids"],
                queued=result.get("queued", 0),
                uploaded=result.get("uploaded", 0),
                failed=result.get("failed", 0),
                baselines_uploaded=result.get("baselines_uploaded", 0),
                source=result.get("source", ""),
                output_prefix=result.get("output_prefix", batch_prefix),
                timestamp=datetime.fromisoformat(
                    result.get("timestamp", datetime.now(timezone.utc).isoformat())
                ),
            )

        except Exception as e:
            raise IDPProcessingError(f"Batch processing failed: {e}") from e

    def _process_test_set(
        self,
        processor,
        test_set: str,
        context: Optional[str],
        number_of_files: Optional[int],
    ) -> Dict[str, Any]:
        """Process a test set (internal helper)."""
        import json

        import boto3

        lambda_client = boto3.client("lambda", region_name=self._region)

        # Find test runner function
        all_functions = []
        paginator = lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            all_functions.extend(page["Functions"])

        stack_name = self._require_stack()
        test_runner_function = next(
            (
                f["FunctionName"]
                for f in all_functions
                if stack_name in f["FunctionName"]
                and "TestRunnerFunction" in f["FunctionName"]
            ),
            None,
        )

        if not test_runner_function:
            raise IDPResourceNotFoundError(
                f"TestRunnerFunction not found for stack {stack_name}"
            )

        # Invoke test runner
        payload = {"arguments": {"input": {"testSetId": test_set}}}
        if context:
            payload["arguments"]["input"]["context"] = context
        if number_of_files:
            payload["arguments"]["input"]["numberOfFiles"] = number_of_files

        response = lambda_client.invoke(
            FunctionName=test_runner_function,
            Payload=json.dumps(payload),
        )

        result = json.loads(response["Payload"].read())

        # Get document IDs from test set
        resources = processor.resources
        test_set_bucket = resources.get("TestSetBucket")
        s3_client = boto3.client("s3", region_name=self._region)

        document_ids = []
        response = s3_client.list_objects_v2(
            Bucket=test_set_bucket, Prefix=f"{test_set}/input/"
        )

        if "Contents" in response:
            batch_id = result["testRunId"]
            for obj in response["Contents"]:
                key = obj["Key"]
                if not key.endswith("/"):
                    filename = key.split("/")[-1]
                    document_ids.append(f"{batch_id}/{filename}")

        return {
            "batch_id": result["testRunId"],
            "document_ids": document_ids,
            "queued": result.get("filesCount", len(document_ids)),
            "uploaded": 0,
            "failed": 0,
            "source": f"test-set:{test_set}",
            "output_prefix": test_set,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def rerun_inference(
        self,
        step: Union[str, RerunStep],
        document_ids: Optional[List[str]] = None,
        batch_id: Optional[str] = None,
        stack_name: Optional[str] = None,
    ) -> RerunResult:
        """
        Rerun processing for existing documents from a specific step.

        Args:
            step: Pipeline step to rerun from (classification or extraction)
            document_ids: List of document IDs to reprocess
            batch_id: Batch ID to get all documents from (alternative to document_ids)
            stack_name: CloudFormation stack name (uses default if not provided)

        Returns:
            RerunResult with queued counts
        """
        from idp_cli.rerun_processor import RerunProcessor

        name = self._require_stack(stack_name)
        step_str = step.value if isinstance(step, RerunStep) else step

        if not document_ids and not batch_id:
            raise IDPConfigurationError("Must specify either document_ids or batch_id")

        try:
            processor = RerunProcessor(stack_name=name, region=self._region)

            if batch_id and not document_ids:
                document_ids = processor.get_batch_document_ids(batch_id)

            result = processor.rerun_documents(
                document_ids=document_ids,
                step=step_str,
                monitor=False,
            )

            return RerunResult(
                documents_queued=result.get("documents_queued", 0),
                documents_failed=result.get("documents_failed", 0),
                failed_documents=result.get("failed_documents", []),
                step=RerunStep(step_str),
            )

        except Exception as e:
            raise IDPProcessingError(f"Rerun failed: {e}") from e

    # =========================================================================
    # Status & Monitoring Operations
    # =========================================================================

    def get_status(
        self,
        batch_id: Optional[str] = None,
        document_id: Optional[str] = None,
        stack_name: Optional[str] = None,
    ) -> BatchStatusResult:
        """
        Get status of a batch or single document.

        Args:
            batch_id: Batch identifier
            document_id: Single document ID
            stack_name: CloudFormation stack name (uses default if not provided)

        Returns:
            BatchStatusResult with status details
        """
        from idp_cli.batch_processor import BatchProcessor
        from idp_cli.progress_monitor import ProgressMonitor

        name = self._require_stack(stack_name)

        if not batch_id and not document_id:
            raise IDPConfigurationError("Must specify either batch_id or document_id")

        processor = BatchProcessor(stack_name=name, region=self._region)

        if batch_id:
            batch_info = processor.get_batch_info(batch_id)
            if not batch_info:
                raise IDPResourceNotFoundError(f"Batch not found: {batch_id}")
            document_ids = batch_info["document_ids"]
            identifier = batch_id
        else:
            document_ids = [document_id]
            identifier = document_id

        monitor = ProgressMonitor(
            stack_name=name,
            resources=processor.resources,
            region=self._region,
        )

        status_data = monitor.get_batch_status(document_ids)
        stats = monitor.calculate_statistics(status_data)

        # Convert to typed models
        # status_data has keys: completed, running, queued, failed (lists of dicts)
        documents = []
        for category in ["completed", "running", "queued", "failed"]:
            for doc in status_data.get(category, []):
                # Convert empty strings to None for optional datetime fields
                start_time = doc.get("start_time") or None
                end_time = doc.get("end_time") or None
                documents.append(
                    DocumentStatusInfo(
                        document_id=doc.get("document_id", ""),
                        status=doc.get("status", "UNKNOWN"),
                        start_time=start_time,
                        end_time=end_time,
                        duration_seconds=doc.get("duration"),
                        num_pages=doc.get("num_pages"),
                        num_sections=doc.get("num_sections"),
                        error=doc.get("error"),
                    )
                )

        return BatchStatusResult(
            batch_id=identifier,
            documents=documents,
            total=stats.get("total", len(documents)),
            completed=stats.get("completed", 0),
            failed=stats.get("failed", 0),
            in_progress=stats.get(
                "running", 0
            ),  # stats uses "running" not "in_progress"
            queued=stats.get("queued", 0),
            success_rate=stats.get("success_rate", 0.0)
            / 100.0,  # Convert percentage to ratio
            all_complete=stats.get("all_complete", False),
        )

    def list_batches(
        self,
        limit: int = 10,
        stack_name: Optional[str] = None,
    ) -> List[BatchInfo]:
        """
        List recent batch processing jobs.

        Args:
            limit: Maximum number of batches to return
            stack_name: CloudFormation stack name (uses default if not provided)

        Returns:
            List of BatchInfo objects
        """
        from idp_cli.batch_processor import BatchProcessor

        name = self._require_stack(stack_name)
        processor = BatchProcessor(stack_name=name, region=self._region)
        batches = processor.list_batches(limit=limit)

        return [
            BatchInfo(
                batch_id=b["batch_id"],
                document_ids=b["document_ids"],
                queued=b.get("queued", 0),
                failed=b.get("failed", 0),
                timestamp=b.get("timestamp", ""),
            )
            for b in batches
        ]

    # =========================================================================
    # Download Operations
    # =========================================================================

    def download_results(
        self,
        batch_id: str,
        output_dir: str,
        file_types: Optional[List[str]] = None,
        stack_name: Optional[str] = None,
    ) -> DownloadResult:
        """
        Download processing results from OutputBucket.

        Args:
            batch_id: Batch identifier
            output_dir: Local directory to download to
            file_types: File types to download (pages, sections, summary, evaluation, or all)
            stack_name: CloudFormation stack name (uses default if not provided)

        Returns:
            DownloadResult with download statistics
        """
        from idp_cli.batch_processor import BatchProcessor

        name = self._require_stack(stack_name)
        processor = BatchProcessor(stack_name=name, region=self._region)

        types_list = file_types or ["all"]
        if "all" in types_list:
            types_list = ["pages", "sections", "summary", "evaluation"]

        result = processor.download_batch_results(
            batch_id=batch_id,
            output_dir=output_dir,
            file_types=types_list,
        )

        return DownloadResult(
            files_downloaded=result.get("files_downloaded", 0),
            documents_downloaded=result.get("documents_downloaded", 0),
            output_dir=result.get("output_dir", output_dir),
        )

    # =========================================================================
    # Document Management Operations
    # =========================================================================

    def delete_documents(
        self,
        document_ids: Optional[List[str]] = None,
        batch_id: Optional[str] = None,
        status_filter: Optional[str] = None,
        stack_name: Optional[str] = None,
        dry_run: bool = False,
        continue_on_error: bool = True,
    ) -> DocumentDeletionResult:
        """
        Permanently delete documents and all their associated data.

        Deletes documents including:
        - Source files from input bucket
        - Processing results from output bucket
        - Tracking records from DynamoDB
        - List entries from tracking table

        Specify documents using ONE of: document_ids or batch_id.

        Args:
            document_ids: List of document IDs (S3 object keys) to delete
            batch_id: Batch ID to delete all documents from
            status_filter: Only delete documents with this status when using batch_id
                          (FAILED, COMPLETED, PROCESSING, QUEUED)
            stack_name: CloudFormation stack name (uses default if not provided)
            dry_run: If True, report what would be deleted without actually deleting
            continue_on_error: If True, continue deleting other documents on error

        Returns:
            DocumentDeletionResult with deletion statistics and per-document results

        Raises:
            IDPConfigurationError: If neither document_ids nor batch_id specified
            IDPProcessingError: If deletion fails

        Examples:
            # Delete specific documents
            >>> result = client.delete_documents(
            ...     document_ids=["batch-123/doc1.pdf", "batch-123/doc2.pdf"]
            ... )

            # Delete all documents in a batch
            >>> result = client.delete_documents(batch_id="cli-batch-20250123")

            # Delete only failed documents in a batch
            >>> result = client.delete_documents(
            ...     batch_id="cli-batch-20250123",
            ...     status_filter="FAILED"
            ... )

            # Dry run to see what would be deleted
            >>> result = client.delete_documents(
            ...     batch_id="cli-batch-20250123",
            ...     dry_run=True
            ... )
        """
        import boto3
        from idp_common.delete_documents import delete_documents, get_documents_by_batch

        name = self._require_stack(stack_name)

        if not document_ids and not batch_id:
            raise IDPConfigurationError("Must specify either document_ids or batch_id")

        if document_ids and batch_id:
            raise IDPConfigurationError(
                "Specify only one of document_ids or batch_id, not both"
            )

        # Get stack resources
        resources = self._get_stack_resources(name)
        input_bucket = resources.get("InputBucket")
        output_bucket = resources.get("OutputBucket")
        documents_table_name = resources.get("DocumentsTable")

        if not input_bucket or not output_bucket or not documents_table_name:
            raise IDPResourceNotFoundError(
                "Required resources not found: InputBucket, OutputBucket, or DocumentsTable"
            )

        # Get DynamoDB table resource
        dynamodb = boto3.resource("dynamodb", region_name=self._region)
        tracking_table = dynamodb.Table(documents_table_name)
        s3_client = boto3.client("s3", region_name=self._region)

        try:
            # Get document IDs from batch if needed
            if batch_id:
                document_ids = get_documents_by_batch(
                    tracking_table=tracking_table,
                    batch_id=batch_id,
                    status_filter=status_filter,
                )

                if not document_ids:
                    return DocumentDeletionResult(
                        success=True,
                        deleted_count=0,
                        failed_count=0,
                        total_count=0,
                        dry_run=dry_run,
                        results=[],
                    )

            # Delete documents
            result = delete_documents(
                object_keys=document_ids,
                tracking_table=tracking_table,
                s3_client=s3_client,
                input_bucket=input_bucket,
                output_bucket=output_bucket,
                dry_run=dry_run,
                continue_on_error=continue_on_error,
            )

            # Convert results to typed models
            single_results = [
                SingleDocumentDeletionResult(
                    success=r.get("success", False),
                    object_key=r.get("object_key", ""),
                    deleted=r.get("deleted", {}),
                    errors=r.get("errors", []),
                )
                for r in result.get("results", [])
            ]

            return DocumentDeletionResult(
                success=result.get("success", False),
                deleted_count=result.get("deleted_count", 0),
                failed_count=result.get("failed_count", 0),
                total_count=result.get("total_count", 0),
                dry_run=result.get("dry_run", dry_run),
                results=single_results,
            )

        except Exception as e:
            raise IDPProcessingError(f"Document deletion failed: {e}") from e

    # =========================================================================
    # Manifest Operations (No stack required)
    # =========================================================================

    def generate_manifest(
        self,
        directory: Optional[str] = None,
        s3_uri: Optional[str] = None,
        baseline_dir: Optional[str] = None,
        output: Optional[str] = None,
        file_pattern: str = "*.pdf",
        recursive: bool = True,
        test_set: Optional[str] = None,
        stack_name: Optional[str] = None,
    ) -> ManifestResult:
        """
        Generate a manifest file from directory or S3 URI.

        Args:
            directory: Local directory to scan
            s3_uri: S3 URI to scan
            baseline_dir: Baseline directory for automatic matching
            output: Output manifest file path (CSV)
            file_pattern: File pattern (default: *.pdf)
            recursive: Include subdirectories
            test_set: Test set name (creates folder in test set bucket)
            stack_name: Required with test_set

        Returns:
            ManifestResult with manifest info
        """
        import csv
        import fnmatch
        import glob as glob_module
        import os

        import boto3

        if not directory and not s3_uri:
            raise IDPConfigurationError("Must specify either directory or s3_uri")

        if test_set and not stack_name:
            raise IDPConfigurationError("stack_name is required when using test_set")

        documents = []
        baseline_map = {}

        # Scan for documents
        if directory:
            dir_path = os.path.abspath(directory)
            if recursive:
                search_pattern = os.path.join(dir_path, "**", file_pattern)
            else:
                search_pattern = os.path.join(dir_path, file_pattern)

            for file_path in glob_module.glob(search_pattern, recursive=recursive):
                if os.path.isfile(file_path):
                    documents.append({"document_path": file_path})
        else:
            # S3 scanning
            if not s3_uri.startswith("s3://"):
                raise IDPConfigurationError("Invalid S3 URI")

            uri_parts = s3_uri[5:].split("/", 1)
            bucket = uri_parts[0]
            prefix = uri_parts[1] if len(uri_parts) > 1 else ""

            s3 = boto3.client("s3", region_name=self._region)
            paginator = s3.get_paginator("list_objects_v2")

            if prefix and not prefix.endswith("/"):
                prefix = prefix + "/"

            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):
                        continue
                    if not recursive and "/" in key[len(prefix) :]:
                        continue
                    filename = os.path.basename(key)
                    if not fnmatch.fnmatch(filename, file_pattern):
                        continue
                    documents.append({"document_path": f"s3://{bucket}/{key}"})

        # Match baselines
        if baseline_dir and directory:
            baseline_path = os.path.abspath(baseline_dir)
            for item in os.listdir(baseline_path):
                item_path = os.path.join(baseline_path, item)
                if os.path.isdir(item_path):
                    baseline_map[item] = item_path

        # Upload to test set if specified
        test_set_created = False
        if test_set:
            name = self._require_stack(stack_name)
            resources = self._get_stack_resources(name)
            test_set_bucket = resources.get("TestSetBucket")

            if not test_set_bucket:
                raise IDPResourceNotFoundError("TestSetBucket not found")

            s3_client = boto3.client("s3", region_name=self._region)

            # Upload documents and baselines
            for doc in documents:
                doc_path = doc["document_path"]
                filename = os.path.basename(doc_path)
                s3_key = f"{test_set}/input/{filename}"
                s3_client.upload_file(doc_path, test_set_bucket, s3_key)
                doc["document_path"] = f"s3://{test_set_bucket}/{s3_key}"

            for filename, baseline_path in baseline_map.items():
                for root, dirs, files in os.walk(baseline_path):
                    for f in files:
                        local_file = os.path.join(root, f)
                        rel_path = os.path.relpath(local_file, baseline_path)
                        s3_key = f"{test_set}/baseline/{filename}/{rel_path}"
                        s3_client.upload_file(local_file, test_set_bucket, s3_key)
                baseline_map[filename] = (
                    f"s3://{test_set_bucket}/{test_set}/baseline/{filename}/"
                )

            test_set_created = True

        # Write manifest
        if output:
            with open(output, "w", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["document_path", "baseline_source"]
                )
                writer.writeheader()
                for doc in documents:
                    filename = os.path.basename(doc["document_path"])
                    baseline_source = baseline_map.get(filename, "")
                    writer.writerow(
                        {
                            "document_path": doc["document_path"],
                            "baseline_source": baseline_source,
                        }
                    )

        return ManifestResult(
            output_path=output,
            document_count=len(documents),
            baselines_matched=len(baseline_map),
            test_set_created=test_set_created,
            test_set_name=test_set if test_set_created else None,
        )

    def validate_manifest(self, manifest_path: str) -> ValidationResult:
        """
        Validate a manifest file without processing.

        Args:
            manifest_path: Path to manifest file (CSV or JSON)

        Returns:
            ValidationResult with validation status
        """
        from idp_cli.manifest_parser import validate_manifest

        is_valid, error = validate_manifest(manifest_path)

        # Count documents if valid
        document_count = None
        has_baselines = False
        if is_valid:
            from idp_cli.manifest_parser import parse_manifest

            documents = parse_manifest(manifest_path)
            document_count = len(documents)
            has_baselines = any(d.get("baseline_source") for d in documents)

        return ValidationResult(
            valid=is_valid,
            error=error,
            document_count=document_count,
            has_baselines=has_baselines,
        )

    # =========================================================================
    # Workflow Control Operations
    # =========================================================================

    def stop_workflows(
        self,
        stack_name: Optional[str] = None,
        skip_purge: bool = False,
        skip_stop: bool = False,
    ) -> StopWorkflowsResult:
        """
        Stop all running workflows for a stack.

        Args:
            stack_name: CloudFormation stack name (uses default if not provided)
            skip_purge: Skip purging the SQS queue
            skip_stop: Skip stopping Step Function executions

        Returns:
            StopWorkflowsResult with stop details
        """
        from idp_cli.stop_workflows import WorkflowStopper

        name = self._require_stack(stack_name)

        stopper = WorkflowStopper(stack_name=name, region=self._region)
        results = stopper.stop_all(skip_purge=skip_purge, skip_stop=skip_stop)

        return StopWorkflowsResult(
            executions_stopped=results.get("executions_stopped"),
            documents_aborted=results.get("documents_aborted"),
            queue_purged=not skip_purge,
        )

    def load_test(
        self,
        source_file: str,
        stack_name: Optional[str] = None,
        rate: int = 100,
        duration: int = 1,
        schedule_file: Optional[str] = None,
        dest_prefix: str = "load-test",
    ) -> LoadTestResult:
        """
        Run load test by copying files to input bucket.

        Args:
            source_file: Source file to copy (local path or s3://bucket/key)
            stack_name: CloudFormation stack name (uses default if not provided)
            rate: Files per minute (default: 100)
            duration: Duration in minutes (default: 1)
            schedule_file: CSV schedule file (overrides rate and duration)
            dest_prefix: Destination prefix in input bucket

        Returns:
            LoadTestResult with test results
        """
        from idp_cli.load_test import LoadTester

        name = self._require_stack(stack_name)
        tester = LoadTester(stack_name=name, region=self._region)

        try:
            if schedule_file:
                result = tester.run_scheduled_load(
                    source_file=source_file,
                    schedule_file=schedule_file,
                    dest_prefix=dest_prefix,
                )
            else:
                result = tester.run_constant_load(
                    source_file=source_file,
                    rate=rate,
                    duration=duration,
                    dest_prefix=dest_prefix,
                )

            return LoadTestResult(
                success=result.get("success", False),
                total_files=result.get("total_files", 0),
                duration_minutes=duration,
                error=result.get("error"),
            )

        except Exception as e:
            return LoadTestResult(
                success=False,
                total_files=0,
                duration_minutes=duration,
                error=str(e),
            )

    # =========================================================================
    # Configuration Operations (No stack required for create/validate)
    # =========================================================================

    def config_create(
        self,
        features: str = "min",
        pattern: str = "pattern-2",
        output: Optional[str] = None,
        include_prompts: bool = False,
        include_comments: bool = True,
    ) -> ConfigCreateResult:
        """
        Generate an IDP configuration template.

        No stack required for this operation.

        Args:
            features: Feature set - 'min', 'core', 'all', or comma-separated list
            pattern: Pattern to use for defaults (pattern-1, pattern-2, pattern-3)
            output: Output file path (optional)
            include_prompts: Include full prompt templates
            include_comments: Include explanatory header comments

        Returns:
            ConfigCreateResult with YAML content
        """
        from idp_common.config.merge_utils import generate_config_template

        # Parse features
        if "," in features:
            feature_list = [f.strip() for f in features.split(",")]
        else:
            feature_list = features

        yaml_content = generate_config_template(
            features=feature_list,
            pattern=pattern,
            include_prompts=include_prompts,
            include_comments=include_comments,
        )

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(yaml_content)

        return ConfigCreateResult(
            yaml_content=yaml_content,
            output_path=output,
        )

    def config_validate(
        self,
        config_file: str,
        pattern: str = "pattern-2",
        show_merged: bool = False,
    ) -> ConfigValidationResult:
        """
        Validate a configuration file against system defaults.

        No stack required for this operation.

        Args:
            config_file: Path to configuration file to validate
            pattern: Pattern to validate against
            show_merged: Include the full merged configuration

        Returns:
            ConfigValidationResult with validation status
        """
        from pathlib import Path

        import yaml
        from idp_common.config.merge_utils import load_yaml_file, validate_config

        try:
            user_config = load_yaml_file(Path(config_file))
        except yaml.YAMLError as e:
            return ConfigValidationResult(
                valid=False,
                errors=[f"YAML syntax error: {e}"],
            )
        except Exception as e:
            return ConfigValidationResult(
                valid=False,
                errors=[f"Failed to load file: {e}"],
            )

        result = validate_config(user_config, pattern=pattern)

        return ConfigValidationResult(
            valid=result["valid"],
            errors=result.get("errors", []),
            warnings=result.get("warnings", []),
            merged_config=result.get("merged_config") if show_merged else None,
        )

    def config_download(
        self,
        stack_name: Optional[str] = None,
        output: Optional[str] = None,
        format: str = "full",
        pattern: Optional[str] = None,
    ) -> ConfigDownloadResult:
        """
        Download configuration from a deployed IDP stack.

        Args:
            stack_name: CloudFormation stack name (uses default if not provided)
            output: Output file path (optional)
            format: 'full' or 'minimal' (only differences from defaults)
            pattern: Pattern for minimal diff (auto-detected if not specified)

        Returns:
            ConfigDownloadResult with configuration
        """
        import boto3
        import yaml

        name = self._require_stack(stack_name)

        # Get ConfigurationTable from stack
        cfn = boto3.client("cloudformation", region_name=self._region)
        paginator = cfn.get_paginator("list_stack_resources")
        config_table = None

        for page in paginator.paginate(StackName=name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("LogicalResourceId") == "ConfigurationTable":
                    config_table = resource.get("PhysicalResourceId")
                    break
            if config_table:
                break

        if not config_table:
            raise IDPResourceNotFoundError("ConfigurationTable not found in stack")

        # Use ConfigurationReader
        from idp_common.config import ConfigurationReader

        reader = ConfigurationReader(table_name=config_table)
        config_data = reader.get_merged_configuration(as_model=False)

        # For minimal format, compute diff
        if format == "minimal":
            from idp_common.config.merge_utils import (
                get_diff_dict,
                load_system_defaults,
            )

            if not pattern:
                classification_method = config_data.get("classification", {}).get(
                    "classificationMethod", ""
                )
                if classification_method == "bda":
                    pattern = "pattern-1"
                elif classification_method == "udop":
                    pattern = "pattern-3"
                else:
                    pattern = "pattern-2"

            defaults = load_system_defaults(pattern)
            config_data = get_diff_dict(defaults, config_data)

        yaml_content = yaml.dump(
            config_data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(f"# Configuration downloaded from stack: {name}\n")
                f.write(f"# Format: {format}\n\n")
                f.write(yaml_content)

        return ConfigDownloadResult(
            config=config_data,
            yaml_content=yaml_content,
            output_path=output,
        )

    def config_upload(
        self,
        config_file: str,
        stack_name: Optional[str] = None,
        validate: bool = True,
        pattern: Optional[str] = None,
    ) -> ConfigUploadResult:
        """
        Upload a configuration file to a deployed IDP stack.

        Args:
            config_file: Path to configuration file (YAML or JSON)
            stack_name: CloudFormation stack name (uses default if not provided)
            validate: Validate config before uploading
            pattern: Pattern for validation (auto-detected if not specified)

        Returns:
            ConfigUploadResult with upload status
        """
        import json
        import os

        import boto3
        import yaml

        name = self._require_stack(stack_name)

        # Load config file
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                content = f.read()

            if config_file.endswith(".json"):
                user_config = json.loads(content)
            else:
                user_config = yaml.safe_load(content)
        except Exception as e:
            return ConfigUploadResult(
                success=False, error=f"Failed to load config: {e}"
            )

        # Validate if requested
        if validate:
            result = self.config_validate(config_file, pattern=pattern or "pattern-2")
            if not result.valid:
                return ConfigUploadResult(
                    success=False,
                    error=f"Validation failed: {'; '.join(result.errors)}",
                )

        # Get ConfigurationTable from stack
        cfn = boto3.client("cloudformation", region_name=self._region)
        paginator = cfn.get_paginator("list_stack_resources")
        config_table = None

        for page in paginator.paginate(StackName=name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("LogicalResourceId") == "ConfigurationTable":
                    config_table = resource.get("PhysicalResourceId")
                    break
            if config_table:
                break

        if not config_table:
            return ConfigUploadResult(
                success=False, error="ConfigurationTable not found"
            )

        # Upload using ConfigurationManager
        try:
            os.environ["CONFIGURATION_TABLE_NAME"] = config_table
            from idp_common.config.configuration_manager import ConfigurationManager

            manager = ConfigurationManager()
            config_json = json.dumps(user_config)
            success = manager.handle_update_custom_configuration(config_json)

            return ConfigUploadResult(
                success=success, error=None if success else "Upload failed"
            )

        except Exception as e:
            return ConfigUploadResult(success=False, error=str(e))

    # =========================================================================
    # Stack Resources
    # =========================================================================

    def get_resources(self, stack_name: Optional[str] = None) -> StackResources:
        """
        Get stack resources.

        Args:
            stack_name: CloudFormation stack name (uses default if not provided)

        Returns:
            StackResources with bucket names, ARNs, etc.
        """
        resources = self._get_stack_resources(stack_name)
        return StackResources(**resources)
