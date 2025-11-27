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


class BoundingBoxCoordinates(BaseModel):
    """Normalized bounding box coordinates (0-1 scale)."""

    top: float = Field(..., ge=0.0, le=1.0, description="Top coordinate (normalized)")
    left: float = Field(..., ge=0.0, le=1.0, description="Left coordinate (normalized)")
    width: float = Field(..., ge=0.0, le=1.0, description="Width (normalized)")
    height: float = Field(..., ge=0.0, le=1.0, description="Height (normalized)")

    @classmethod
    def from_corners(
        cls,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        scale: float = 1000.0,
    ) -> "BoundingBoxCoordinates":
        """
        Create from corner coordinates in document space.

        Args:
            x1, y1: Top-left corner in 0-scale range
            x2, y2: Bottom-right corner in 0-scale range
            scale: Normalization scale (default 1000.0)

        Returns:
            BoundingBoxCoordinates with normalized 0-1 values
        """
        # Ensure coordinates are in correct order
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        # Normalize to 0-1 scale
        left = x1 / scale
        top = y1 / scale
        width = (x2 - x1) / scale
        height = (y2 - y1) / scale

        # Clamp to valid range
        left = min(max(left, 0.0), 1.0)
        top = min(max(top, 0.0), 1.0)
        width = min(width, 1.0 - left)
        height = min(height, 1.0 - top)

        return cls(top=top, left=left, width=width, height=height)


class Geometry(BaseModel):
    """
    Standard IDP geometry format compatible with UI expectations.

    This is the single source of truth for geometry data structure.
    Frontend expects: geometry[0].boundingBox.{left, top, width, height}
    """

    boundingBox: BoundingBoxCoordinates = Field(
        ...,
        description="Normalized bounding box coordinates",
        serialization_alias="boundingBox",  # Ensure lowercase in JSON
    )
    page: int = Field(..., ge=1, description="Page number (1-indexed)")
    vertices: list[dict[str, float]] | None = Field(
        None, description="Optional polygon vertices for complex shapes"
    )

    @classmethod
    def from_bbox_list(cls, bbox_coords: list[float], page_num: int) -> "Geometry":
        """
        Create from LLM bbox response format [x1, y1, x2, y2].

        Args:
            bbox_coords: List of 4 coordinates in 0-1000 scale
            page_num: Page number (1-indexed)

        Returns:
            Geometry object

        Raises:
            ValueError: If bbox_coords is not exactly 4 values
        """
        if len(bbox_coords) != 4:
            raise ValueError(f"Expected 4 coordinates, got {len(bbox_coords)}")

        x1, y1, x2, y2 = bbox_coords
        bbox = BoundingBoxCoordinates.from_corners(x1, y1, x2, y2, scale=1000.0)

        return cls(boundingBox=bbox, page=page_num, vertices=None)

    def to_ui_format(self) -> dict[str, Any]:
        """
        Convert to UI-compatible format.

        Returns:
            Dict with geometry data: {"boundingBox": {...}, "page": 1}
        """
        result: dict[str, Any] = {
            "boundingBox": {
                "top": self.boundingBox.top,
                "left": self.boundingBox.left,
                "width": self.boundingBox.width,
                "height": self.boundingBox.height,
            },
            "page": self.page,
        }
        if self.vertices is not None:
            result["vertices"] = self.vertices
        return result


class FieldAssessmentData(BaseModel):
    """
    Standard assessment data for a single field.
    Ensures consistent structure across all assessment services.
    """

    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., description="Confidence reasoning")
    confidence_threshold: float = Field(..., ge=0.0, le=1.0)
    geometry: list[Geometry] | None = Field(
        None,
        description="Bounding box locations (always wrapped in list for UI compatibility)",
    )

    @classmethod
    def from_llm_response(
        cls,
        confidence: float,
        reasoning: str,
        confidence_threshold: float,
        bbox_coords: list[float] | None = None,
        page_num: int | None = None,
    ) -> "FieldAssessmentData":
        """Create from LLM response data."""
        geometry = None
        if bbox_coords is not None and page_num is not None:
            geom = Geometry.from_bbox_list(bbox_coords, page_num)
            geometry = [geom]  # Always wrap in list

        return cls(
            confidence=confidence,
            reasoning=reasoning,
            confidence_threshold=confidence_threshold,
            geometry=geometry,
        )

    def to_explainability_format(self) -> dict[str, Any]:
        """Convert to explainability_info format for frontend."""
        result: dict[str, Any] = {
            "confidence": self.confidence,
            "confidence_reason": self.reasoning,
            "confidence_threshold": self.confidence_threshold,
        }

        if self.geometry:
            result["geometry"] = [g.to_ui_format() for g in self.geometry]

        return result


class ConfidenceAlert(BaseModel):
    """Alert for confidence threshold violation."""

    attribute_name: str = Field(serialization_alias="attributeName")
    confidence: float
    confidence_threshold: float = Field(serialization_alias="confidenceThreshold")

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
