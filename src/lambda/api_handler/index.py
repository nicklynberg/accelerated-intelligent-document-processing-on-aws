import os
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.event_handler.exceptions import (
    BadRequestError,
    InternalServerError
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError

from idp_common.docs_service import create_document_service
from idp_common.job_service import create_job_service

from models import (
    GetJobResponse,
    PostJobRequest,
    PostJobResponse,
    Result,
    Timestamps,
    UploadInfo,
)

logger = Logger()
app = APIGatewayRestResolver(enable_validation=True)

# Initialize AWS clients
s3_client = boto3.client("s3", config=boto3.session.Config(signature_version="s3v4"))

# Environment variables
STAGING_BUCKET = os.environ.get("STAGING_BUCKET_NAME", "")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET_NAME", "")
DATA_RETENTION_DAYS = int(os.environ.get("DATA_RETENTION_IN_DAYS", "30"))
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", "4294967296"))  # 4GB
PRESIGNED_URL_EXPIRY_SECONDS = int(os.environ.get("PRESIGNED_URL_EXPIRY_SECONDS", "900"))  # 15 minutes

# Initialize services
document_service = create_document_service()
job_service = create_job_service()


def get_content_type(filename: str) -> str:
    """Determine content type from file extension."""
    if filename.lower().endswith(".zip"):
        return "application/zip"
    raise ValueError("Unsupported file type. Only .zip files are supported")


def compute_job_status(files: dict[str, str]) -> str:
    """Compute overall job status from file statuses."""
    if not files:
        return "PENDING_UPLOAD"

    statuses = set(files.values())
    terminal = {"COMPLETED", "FAILED", "ABORTED"}

    if not all(s in terminal for s in statuses):
        return "IN_PROGRESS"
    if all(s == "COMPLETED" for s in statuses):
        return "SUCCEEDED"
    if all(s == "FAILED" for s in statuses):
        return "FAILED"
    if all(s == "ABORTED" for s in statuses):
        return "ABORTED"
    return "PARTIALLY_SUCCEEDED"


@app.post("/jobs")
def create_job(job: PostJobRequest) -> PostJobResponse:
    """Create a new job and generate presigned URL for file upload."""
    try:
        job_id = str(uuid.uuid4())
        logger.info(f"Creating job with ID: {job_id}")

        content_type = get_content_type(job.fileName)
        object_key = f"jobs/{job_id}/{job.fileName}"

        # Calculate TTL for DynamoDB record
        current_time = datetime.now(timezone.utc)
        expires_after = int((current_time + timedelta(days=DATA_RETENTION_DAYS)).timestamp())

        # Create job record
        metadata_dict = job.metadata.model_dump() if job.metadata else None
        job_service.create_job_record(
            job_id=job_id,
            files={},
            expires_after=expires_after,
            metadata=metadata_dict,
        )

        # Generate presigned POST URL
        presigned_post = s3_client.generate_presigned_post(
            Bucket=STAGING_BUCKET,
            Key=object_key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, MAX_FILE_SIZE_BYTES],
            ],
            ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
        )

        logger.info(f"Generated presigned POST URL for {object_key}")

        return PostJobResponse(
            jobId=job_id,
            upload=UploadInfo(
                uploadUrl=presigned_post["url"],
                expiresInSeconds=PRESIGNED_URL_EXPIRY_SECONDS,
                requiredHeaders=presigned_post["fields"],
            ),
        )

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}", exc_info=True)
        raise BadRequestError(str(e))
    except ClientError as e:
        logger.error(f"AWS service error: {str(e)}", exc_info=True)
        raise InternalServerError(str(e))
    except Exception as e:
        logger.error(f"Unexpected error creating job: {str(e)}", exc_info=True)
        raise InternalServerError(str(e))


@app.get("/jobs/<job_id>")
def get_job(job_id: str) -> GetJobResponse:
    """Get job status by ID."""
    try:
        job_record = job_service.get_job_record(job_id)

        if not job_record:
            raise ValueError(f"Job {job_id} not found")

        files = job_record.get("Files", {})

        # Enrich IN_PROGRESS files with actual document status
        files = enrich_file_statuses(job_id, files)

        # Determine overall status from file statuses
        job_status = compute_job_status(files)

        # Create/Upload zipfile when processing is complete
        result = None
        if job_status in ["SUCCEEDED", "PARTIALLY_SUCCEEDED"]:
            download_url = generate_presigned_url(job_id)
            result = Result(downloadUrl=download_url, expiresInSeconds=PRESIGNED_URL_EXPIRY_SECONDS)

        return GetJobResponse(
            jobId=job_id,
            status=job_status,
            timestamps=Timestamps(
                createdAt=job_record.get("CreatedAt", ""),
                updatedAt=job_record.get("UpdatedAt", ""),
            ),
            files=files,
            result=result
        )
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}", exc_info=True)
        raise BadRequestError(str(e))
    except ClientError as e:
        logger.error(f"AWS service error: {str(e)}", exc_info=True)
        raise InternalServerError(str(e))
    except Exception as e:
        logger.error(f"Unexpected error getting job: {str(e)}", exc_info=True)
        raise

def generate_presigned_url(job_id: str):
    object_key = f"jobs/{job_id}/results.zip"
    return s3_client.generate_presigned_url(
        "get_object", Params={"Bucket": OUTPUT_BUCKET, "Key": object_key}, ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS)


def enrich_file_statuses(job_id: str, files: dict[str, str]) -> dict[str, str]:
    """Enrich IN_PROGRESS files with actual document status from tracking table."""
    processing_files = [f for f, status in files.items() if status == "IN_PROGRESS"]
    if not processing_files:
        return files

    enriched = dict(files)
    for i in range(0, len(processing_files), 100):
        chunk = processing_files[i:i + 100]
        doc_ids = [f"jobs/{job_id}/{f}" for f in chunk]
        docs = document_service.batch_get_documents(doc_ids)

        for doc in docs:
            filename = doc.get("document_id", "").split("/")[-1]
            if filename and filename in enriched:
                enriched[filename] = doc.get("status", "IN_PROGRESS")

    return enriched

def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
