import os
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError

from models import (
    GetJobResponse,
    PostJobRequest,
    PostJobResponse,
    Progress,
    Timestamps,
    UploadInfo,
)

logger = Logger()
app = APIGatewayRestResolver(enable_validation=True)


# Request/Response Models

@app.post("/jobs")
def create_job(job: PostJobRequest) -> PostJobResponse:
    """Create a new job"""
    # TODO: Implement job creation logic
    # - Generate job_id
    # - Store in DynamoDB TrackingTable
    # - Generate presigned URL for file upload
    
    job_id = "job-12345"  # Placeholder
    bucket = os.environ.get("INPUT_BUCKET_NAME", "idp-input-bucket")
    
    return PostJobResponse(
        jobId=job_id,
        upload=UploadInfo(
            bucket=bucket,
            keyPrefix=f"jobs/{job_id}/input/",
            uploadUrl="https://s3-presigned-url-placeholder",
            expiresInSeconds=604800,
            requiredHeaders={
                "x-amz-server-side-encryption": "aws:kms"
            }
        )
    )


@app.get("/jobs/<job_id>")
def get_job(job_id: str) -> GetJobResponse:
    """Get job status by ID"""
    # TODO: Implement job retrieval logic
    # - Query DynamoDB TrackingTable by job_id
    # Placeholder response
    return GetJobResponse(
        jobId=job_id,
        status="IN_PROGRESS",
        timestamps=Timestamps(
            createdAt="2026-01-09T14:12:43Z",
            updatedAt="2026-01-09T14:14:30Z"
        ),
        progress=Progress(
            stage="QUEUED",
            percent=10
        ),
        result=None,
        error=None
    )


def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
