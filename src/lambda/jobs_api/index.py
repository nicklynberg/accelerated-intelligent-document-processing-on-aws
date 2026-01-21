from fastapi import FastAPI, HTTPException
from mangum import Mangum
from pydantic import BaseModel
from typing import Optional, Dict, Any

app = FastAPI()


class Metadata(BaseModel):
    source: str


class Files(BaseModel):
    pdfFileName: str
    jsonFileName: str


class UploadInfo(BaseModel):
    bucket: str
    keyPrefix: str
    uploadUrl: str
    expiresInSeconds: int
    requiredHeaders: Dict[str, str]


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


class PostJobRequest(BaseModel):
    documentType: str
    metadata: Metadata
    files: Files


class PostJobResponse(BaseModel):
    jobId: str
    upload: UploadInfo


class GetJobResponse(BaseModel):
    jobId: str
    status: str
    timestamps: Timestamps
    progress: Progress
    result: Optional[Result] = None
    error: Optional[str] = None


@app.post("/jobs", response_model=PostJobResponse)
async def create_job(job: PostJobRequest):
    """Create a new job"""
    # TODO: Implement job creation logic
    job_id = "job-12345"  # Placeholder
    return PostJobResponse(
        jobId=job_id,
        upload=UploadInfo(
            bucket="idp-input-bucket",
            keyPrefix=f"jobs/{job_id}/input/",
            uploadUrl="https://s3-presigned-url-placeholder",
            expiresInSeconds=604800,
            requiredHeaders={
                "x-amz-server-side-encryption": "aws:kms"
            }
        )
    )


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    """Get job status by ID"""
    # TODO: Implement job retrieval logic
    # - Query DynamoDB TrackingTable by job_id
    if not job_id:
        raise HTTPException(status_code=400, detail="Job ID is required")
    
    return {
        "job_id": job_id,
        "status": "running",
        "documentType": "Package",
        "metadata": {}
    }


handler = Mangum(app)
