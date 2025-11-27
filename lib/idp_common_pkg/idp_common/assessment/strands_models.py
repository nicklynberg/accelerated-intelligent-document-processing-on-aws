"""
Pydantic models for Strands-based assessment structured output.

These models define the structured data format that Strands agents return
when assessing document extraction confidence with bounding boxes.
"""

from typing import Any

from pydantic import BaseModel, Field

from idp_common.assessment.models import Geometry


class BoundingBox(BaseModel):
    """Bounding box coordinates in normalized 0-1000 scale."""

    x1: int = Field(..., ge=0, le=1000, description="Top-left X coordinate")
    y1: int = Field(..., ge=0, le=1000, description="Top-left Y coordinate")
    x2: int = Field(..., ge=0, le=1000, description="Bottom-right X coordinate")
    y2: int = Field(..., ge=0, le=1000, description="Bottom-right Y coordinate")
    page: int = Field(..., ge=1, description="Page number (1-indexed)")

    def to_geometry(self) -> dict[str, Any]:
        """
        Convert to IDP geometry format compatible with UI.

        Returns:
            Dictionary in UI-compatible format (lowercase, no array wrapper here)
        """
        # Create proper Geometry object
        geometry = Geometry.from_bbox_list(
            [self.x1, self.y1, self.x2, self.y2], self.page
        )

        # Return UI format (will be wrapped in array by caller)
        return geometry.to_ui_format()


class ConfidenceAssessment(BaseModel):
    """Confidence assessment for an attribute value."""

    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")
    reasoning: str = Field(..., description="Explanation for the confidence score")
    bounding_box: BoundingBox | None = Field(
        None, description="Location of value in document"
    )


class AssessmentOutput(BaseModel):
    """
    Structured output for confidence assessment of a single field.

    Each task assesses exactly ONE field (e.g., "name" or "address.street").
    The assessment is directly the ConfidenceAssessment for that field.
    """

    field_name: str = Field(
        ...,
        description="The name/path of the field being assessed (e.g., 'name' or 'address.street')",
    )
    assessment: ConfidenceAssessment = Field(
        ..., description="Confidence assessment for this specific field"
    )
