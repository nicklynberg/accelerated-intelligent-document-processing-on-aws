# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Models for document extraction using LLMs.

This module provides data models for extraction results.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


@dataclass
class ExtractedAttribute:
    """A single extracted attribute from a document"""

    name: str
    value: Any
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    """Result of extraction for a document section"""

    section_id: str
    document_class: str
    attributes: List[ExtractedAttribute]
    raw_response: Optional[str] = None
    metering: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    output_uri: Optional[str] = None


@dataclass
class PageInfo:
    """Information about a page used in extraction"""

    page_id: str
    text_uri: Optional[str] = None
    image_uri: Optional[str] = None
    raw_text_uri: Optional[str] = None


class DocumentClassInfo(BaseModel):
    """Document classification information"""

    type: str = Field(description="Document class/type")


class SplitDocumentInfo(BaseModel):
    """Information about document splitting"""

    page_indices: List[int] = Field(
        default_factory=list, description="Page indices in the split document"
    )


class ExtractionMetadata(BaseModel):
    """Metadata about the extraction process"""

    parsing_succeeded: bool = Field(
        default=True, description="Whether parsing succeeded"
    )
    extraction_time_seconds: Optional[float] = Field(
        default=None, description="Time taken for extraction"
    )
    skipped_due_to_empty_attributes: Optional[bool] = Field(
        default=None,
        description="Whether extraction was skipped due to empty attributes",
    )
    assessment_time_seconds: Optional[float] = Field(
        default=None, description="Time taken for assessment"
    )
    granular_assessment_used: Optional[bool] = Field(
        default=None, description="Whether granular assessment was used"
    )
    assessment_tasks_total: Optional[int] = Field(
        default=None, description="Total number of assessment tasks"
    )
    assessment_tasks_successful: Optional[int] = Field(
        default=None, description="Number of successful assessment tasks"
    )
    assessment_tasks_failed: Optional[int] = Field(
        default=None, description="Number of failed assessment tasks"
    )


class ExtractionData(BaseModel):
    """
    Complete extraction data structure stored in S3.

    This model represents the JSON structure written to S3 containing
    extraction results, assessment information, and metadata.
    """

    document_class: DocumentClassInfo = Field(
        description="Document classification information"
    )
    split_document: SplitDocumentInfo = Field(
        default_factory=SplitDocumentInfo,
        description="Information about document splitting",
    )
    inference_result: Dict[str, Any] = Field(
        default_factory=dict, description="Extracted data from the document"
    )
    explainability_info: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Assessment/explainability information"
    )
    metadata: ExtractionMetadata = Field(
        default_factory=ExtractionMetadata,
        description="Extraction and assessment metadata",
    )

    class Config:
        # Allow extra fields for forward compatibility
        extra = "allow"
