import os
from typing import Dict, Any, Optional
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools import Logger
from pydantic import BaseModel

logger = Logger()
app = APIGatewayRestResolver(enable_validation=True)


# Request/Response Models
class Metadata(BaseModel):
    source: str


class Files(BaseModel):
    pdfFileName: str
    jsonFileName: str


class PostJobRequest(BaseModel):
    documentType: str
    metadata: Metadata
    files: Files


class UploadInfo(BaseModel):
    bucket: str
    keyPrefix: str
    uploadUrl: str
    expiresInSeconds: int
    requiredHeaders: Dict[str, str]


class PostJobResponse(BaseModel):
    jobId: str
    upload: UploadInfo


class Timestamps(BaseModel):
    createdAt: str
    updatedAt: str


class Progress(BaseModel):
    stage: str
    percent: int


class Result(BaseModel):
    bucket: str
    key: str
    downloadUrl: str
    expiresInSeconds: int


class GetJobResponse(BaseModel):
    jobId: str
    status: str
    timestamps: Timestamps
    progress: Progress
    result: Optional[Result] = None
    error: Optional[str] = None


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
