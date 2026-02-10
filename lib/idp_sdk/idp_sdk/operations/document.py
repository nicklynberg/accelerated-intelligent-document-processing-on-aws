# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Document operations for IDP SDK."""

import os
from datetime import datetime, timezone
from typing import List, Optional, Union

import boto3
from botocore.exceptions import ClientError

from idp_sdk.exceptions import (
    IDPProcessingError,
    IDPResourceNotFoundError,
)
from idp_sdk.models import (
    DocumentDeletionResult,
    DocumentDownloadResult,
    DocumentRerunResult,
    DocumentStatus,
    DocumentUploadResult,
    RerunStep,
)


class DocumentOperation:
    """Single document operations."""

    def __init__(self, client):
        self._client = client

    def upload(
        self,
        file_path: str,
        document_id: Optional[str] = None,
        stack_name: Optional[str] = None,
    ) -> DocumentUploadResult:
        """Upload and process a single document.

        Args:
            file_path: Path to local file to upload
            document_id: Optional custom document ID (defaults to filename without extension)
            stack_name: Optional stack name override

        Returns:
            DocumentUploadResult with document_id and status
        """
        name = self._client._require_stack(stack_name)
        resources = self._client._get_stack_resources(name)

        if not os.path.isfile(file_path):
            raise IDPProcessingError(f"File not found: {file_path}")

        # Generate document ID if not provided
        filename = os.path.basename(file_path)
        if not document_id:
            document_id = os.path.splitext(filename)[0]

        # Generate unique batch prefix for single document
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        batch_id = f"single-doc-{timestamp}"
        s3_key = f"{batch_id}/{filename}"

        try:
            # Upload to InputBucket
            s3_client = boto3.client("s3", region_name=self._client._region)
            input_bucket = resources["InputBucket"]
            s3_client.upload_file(Filename=file_path, Bucket=input_bucket, Key=s3_key)

            return DocumentUploadResult(
                document_id=s3_key,
                status="queued",
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            raise IDPProcessingError(f"Failed to upload document: {e}") from e

    def get_status(
        self, document_id: str, stack_name: Optional[str] = None
    ) -> DocumentStatus:
        """Get single document status.

        Args:
            document_id: Document identifier (S3 key)
            stack_name: Optional stack name override

        Returns:
            DocumentStatus with processing information
        """
        from idp_sdk.core.batch_processor import BatchProcessor
        from idp_sdk.core.progress_monitor import ProgressMonitor

        name = self._client._require_stack(stack_name)
        processor = BatchProcessor(stack_name=name, region=self._client._region)
        monitor = ProgressMonitor(
            stack_name=name, resources=processor.resources, region=self._client._region
        )

        status_data = monitor.get_batch_status([document_id])

        # Find document in status data
        for category in ["completed", "running", "queued", "failed"]:
            for doc in status_data.get(category, []):
                if doc.get("document_id") == document_id:
                    return DocumentStatus(
                        document_id=doc.get("document_id", ""),
                        status=doc.get("status", "UNKNOWN"),
                        start_time=doc.get("start_time"),
                        end_time=doc.get("end_time"),
                        duration_seconds=doc.get("duration"),
                        num_pages=doc.get("num_pages"),
                        num_sections=doc.get("num_sections"),
                        error=doc.get("error"),
                    )

        raise IDPResourceNotFoundError(f"Document not found: {document_id}")

    def download_results(
        self,
        document_id: str,
        output_dir: str,
        file_types: Optional[List[str]] = None,
        stack_name: Optional[str] = None,
    ) -> DocumentDownloadResult:
        """Download processing results for a single document.

        Args:
            document_id: Document identifier (S3 key)
            output_dir: Local directory to download results to
            file_types: List of file types to download (pages, sections, summary, evaluation)
            stack_name: Optional stack name override

        Returns:
            DocumentDownloadResult with download statistics
        """
        name = self._client._require_stack(stack_name)
        resources = self._client._get_stack_resources(name)
        output_bucket = resources["OutputBucket"]

        types_list = file_types or ["pages", "sections", "summary", "evaluation"]

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)

        s3_client = boto3.client("s3", region_name=self._client._region)
        files_downloaded = 0

        try:
            # List all files for this document
            paginator = s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=output_bucket, Prefix=f"{document_id}/")

            for page in pages:
                for obj in page.get("Contents", []):
                    s3_key = obj["Key"]

                    # Filter by file type if specified
                    if file_types and "all" not in file_types:
                        if not any(
                            f"/{file_type}/" in s3_key
                            or s3_key.endswith(f"/{file_type}.json")
                            for file_type in types_list
                        ):
                            continue

                    # Download file
                    local_path = os.path.join(output_dir, s3_key)
                    local_dir = os.path.dirname(local_path)
                    os.makedirs(local_dir, exist_ok=True)

                    s3_client.download_file(
                        Bucket=output_bucket, Key=s3_key, Filename=local_path
                    )
                    files_downloaded += 1

            return DocumentDownloadResult(
                document_id=document_id,
                files_downloaded=files_downloaded,
                output_dir=output_dir,
            )
        except Exception as e:
            raise IDPProcessingError(f"Failed to download results: {e}") from e

    def download_source(
        self,
        document_id: str,
        output_path: str,
        stack_name: Optional[str] = None,
    ) -> str:
        """Download original document source file.

        Args:
            document_id: Document identifier (S3 key)
            output_path: Local file path to save document
            stack_name: Optional stack name override

        Returns:
            Local file path where document was saved
        """
        name = self._client._require_stack(stack_name)
        resources = self._client._get_stack_resources(name)
        input_bucket = resources["InputBucket"]

        try:
            s3_client = boto3.client("s3", region_name=self._client._region)

            # Create output directory if needed
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # Download file
            s3_client.download_file(
                Bucket=input_bucket, Key=document_id, Filename=output_path
            )

            return output_path
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                raise IDPResourceNotFoundError(f"Document not found: {document_id}")
            raise IDPProcessingError(f"Failed to download source: {e}") from e
        except Exception as e:
            raise IDPProcessingError(f"Failed to download source: {e}") from e

    def rerun(
        self,
        document_id: str,
        step: Union[str, RerunStep],
        stack_name: Optional[str] = None,
    ) -> DocumentRerunResult:
        """Rerun processing for a single document from a specific step.

        Args:
            document_id: Document identifier (S3 key)
            step: Pipeline step to rerun from (e.g., 'classification', 'extraction')
            stack_name: Optional stack name override

        Returns:
            DocumentRerunResult with rerun status
        """
        from idp_sdk.core.rerun_processor import RerunProcessor

        name = self._client._require_stack(stack_name)
        step_str = step.value if isinstance(step, RerunStep) else step

        try:
            processor = RerunProcessor(stack_name=name, region=self._client._region)
            result = processor.rerun_documents(
                document_ids=[document_id], step=step_str, monitor=False
            )

            queued = result.get("documents_queued", 0) > 0

            return DocumentRerunResult(
                document_id=document_id,
                step=RerunStep(step_str),
                queued=queued,
            )
        except Exception as e:
            raise IDPProcessingError(f"Rerun failed: {e}") from e

    def delete(
        self, document_id: str, stack_name: Optional[str] = None, dry_run: bool = False
    ) -> DocumentDeletionResult:
        """Delete a single document and all associated data.

        Args:
            document_id: Document identifier (S3 key)
            stack_name: Optional stack name override
            dry_run: If True, only simulate deletion without actually deleting

        Returns:
            DocumentDeletionResult with deletion details
        """
        import boto3
        from idp_common.delete_documents import delete_documents

        name = self._client._require_stack(stack_name)
        resources = self._client._get_stack_resources(name)

        input_bucket = resources.get("InputBucket")
        output_bucket = resources.get("OutputBucket")
        documents_table_name = resources.get("DocumentsTable")

        if not input_bucket or not output_bucket or not documents_table_name:
            raise IDPResourceNotFoundError(
                "Required resources not found: InputBucket, OutputBucket, or DocumentsTable"
            )

        dynamodb = boto3.resource("dynamodb", region_name=self._client._region)
        tracking_table = dynamodb.Table(documents_table_name)
        s3_client = boto3.client("s3", region_name=self._client._region)

        try:
            result = delete_documents(
                object_keys=[document_id],
                tracking_table=tracking_table,
                s3_client=s3_client,
                input_bucket=input_bucket,
                output_bucket=output_bucket,
                dry_run=dry_run,
                continue_on_error=False,
            )

            if result.get("results"):
                single_result = result["results"][0]
                return DocumentDeletionResult(
                    success=single_result.get("success", False),
                    object_key=single_result.get("object_key", document_id),
                    deleted=single_result.get("deleted", {}),
                    errors=single_result.get("errors", []),
                )

            return DocumentDeletionResult(
                success=False,
                object_key=document_id,
                deleted={},
                errors=["No deletion result returned"],
            )
        except Exception as e:
            raise IDPProcessingError(f"Document deletion failed: {e}") from e
