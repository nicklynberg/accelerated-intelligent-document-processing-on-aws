# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""DynamoDB service for batch job operations."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from idp_common.dynamodb.client import DynamoDBClient

logger = logging.getLogger(__name__)


class JobDynamoDBService:
    """Service for managing batch job records in DynamoDB."""

    def __init__(
        self,
        dynamodb_client: Optional[DynamoDBClient] = None,
        table_name: Optional[str] = None,
    ):
        self.client = dynamodb_client or DynamoDBClient(table_name=table_name)

    def create_job_record(
        self,
        job_id: str,
        files: Optional[Dict[str, str]] = None,
        expires_after: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a job metadata record.

        Args:
            job_id: Job identifier (e.g., api-requests/{uuid})
            files: Map of filenames to status
            expires_after: Optional TTL timestamp
            metadata: Optional metadata dict

        Returns:
            The job_id
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        item = {
            "PK": f"job#{job_id}",
            "SK": "metadata",
            "Files": files or {},
            "CreatedAt": timestamp,
            "UpdatedAt": timestamp,
        }

        if expires_after:
            item["ExpiresAfter"] = expires_after

        if metadata:
            item["Metadata"] = json.dumps(metadata)

        self.client.put_item(item)
        logger.info(f"Created job record: {job_id}")

        return job_id

    def get_job_record(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job record by job_id."""
        key = {"PK": f"job#{job_id}", "SK": "metadata"}
        return self.client.get_item(key)

    def update_job_files(self, job_id: str, files: Dict[str, str]) -> None:
        """Update the Files map on a job record."""
        timestamp = datetime.now(timezone.utc).isoformat()
        self.client.update_item(
            key={"PK": f"job#{job_id}", "SK": "metadata"},
            update_expression="SET Files = :files, UpdatedAt = :ts",
            expression_attribute_names={},
            expression_attribute_values={":files": files, ":ts": timestamp},
        )
        logger.info(f"Updated job files: {job_id}")

    def update_file_status(
        self, job_id: str, filename: str, status: str
    ) -> Optional[Dict[str, str]]:
        """
        Update a single file's status in the job record.

        Returns:
            The updated Files map, or None if job not found
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        response = self.client.table.update_item(
            Key={"PK": f"job#{job_id}", "SK": "metadata"},
            UpdateExpression="SET Files.#filename = :status, UpdatedAt = :ts",
            ExpressionAttributeNames={"#filename": filename},
            ExpressionAttributeValues={":status": status, ":ts": timestamp},
            ReturnValues="ALL_NEW",
        )
        item = response.get("Attributes")
        return item.get("Files") if item else None
