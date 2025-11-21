# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Models for document assessment using LLMs.

This module provides data models for assessment results that evaluate
the confidence and accuracy of extraction results.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class AttributeAssessment(BaseModel):
    """Assessment result for a single extracted attribute"""

    attribute_name: str
    confidence: float
    confidence_reason: str
    extracted_value: Any = None


class LegacyAssessmentResult(BaseModel):
    """Legacy result of assessment for a document section (for backwards compatibility)"""

    section_id: str
    document_class: str
    attribute_assessments: list[AttributeAssessment]
    overall_confidence: float = 0.0
    raw_response: str | None = None
    metering: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    output_uri: str | None = None


class DocumentAssessmentResult(BaseModel):
    """Assessment result for an entire document"""

    document_id: str
    section_assessments: list[LegacyAssessmentResult]
    overall_document_confidence: float = 0.0
    total_attributes_assessed: int = 0
    high_confidence_attributes: int = 0
    medium_confidence_attributes: int = 0
    low_confidence_attributes: int = 0
    assessment_summary: str | None = None
    metadata: dict[str, Any] | None = None


# ============================================================================
# Assessment Task Model (unified for all assessment services)
# ============================================================================


class AssessmentTask(BaseModel):
    """
    Single-field assessment task for granular assessment.

    Used by both granular_service.py (creation) and strands_service.py (execution).
    """

    model_config = {"arbitrary_types_allowed": True}

    task_id: str
    task_type: str = Field(description="Always 'attribute' - single field assessment")

    # Path to field as tuple: ("address", "street") or ("items", 0, "price")
    field_path: tuple[str | int, ...]

    # The field name being assessed (last element of path)
    field_name: str

    # Schema for this specific field only
    field_schema: dict[str, Any]

    # Confidence threshold for this field
    confidence_threshold: float

    # Direct reference to parent container in assessment structure (for O(1) insertion)
    # Can be Dict for regular fields or list for array items
    parent_assessment_dict: dict[str, Any] | list[Any]


class AssessmentResult(BaseModel):
    """Result of a single assessment task (used by both granular and strands services)."""

    task_id: str
    success: bool
    assessment_data: dict[str, Any]
    confidence_alerts: list[dict[str, Any]]
    error_message: str | None = None
    processing_time: float = 0.0
    metering: dict[str, Any] | None = None


# ============================================================================
# Models for assessment service.py (data flow and processing)
# ============================================================================


class Geometry(BaseModel):
    """Geometry in IDP format (converted from BoundingBox)."""

    boundingBox: dict[str, float]  # {top, left, width, height}
    page: int


class ConfidenceAlert(BaseModel):
    """Alert for confidence threshold violation."""

    attribute_name: str
    confidence: float
    confidence_threshold: float

    @field_validator("confidence", "confidence_threshold", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number, handle None."""
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            if not v.strip():
                return 0.0
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0
        # Fallback for other types
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0


class DocumentContent(BaseModel):
    """Loaded content from document pages."""

    document_text: str
    page_images: list[Any]
    ocr_text_confidence: str


class ExtractionData(BaseModel):
    """Loaded extraction data from S3."""

    extraction_results: dict[str, Any]  # The inference_result dict
    full_data: dict[str, Any]  # Complete data including metadata


class AssessmentProcessingResult(BaseModel):
    """Result of processing assessment data."""

    enhanced_assessment_data: dict[str, Any]
    confidence_alerts: list[ConfidenceAlert]
    metering: dict[str, Any]
    processing_metadata: dict[
        str, Any
    ]  # Contains assessment_time_seconds, parsing_succeeded, etc.
