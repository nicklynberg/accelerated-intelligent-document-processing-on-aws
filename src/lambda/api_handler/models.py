"""Request and Response models for the Jobs API."""

from typing import Dict, Optional

from pydantic import BaseModel


# Request Models
class Metadata(BaseModel):
    source: str


class Files(BaseModel):
    pdfFileName: str
    jsonFileName: str


class PostJobRequest(BaseModel):
    documentType: str
    files: str  # Filename with extension (.pdf or .json)
    metadata: Optional[Metadata] = None


# Response Models
class UploadInfo(BaseModel):
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
    downloadUrl: str
    expiresInSeconds: int


class GetJobResponse(BaseModel):
    jobId: str
    status: str
    timestamps: Timestamps
    progress: Progress
    result: Optional[Result] = None
    error: Optional[str] = None
