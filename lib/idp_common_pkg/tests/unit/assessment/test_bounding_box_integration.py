# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for bounding box conversion models.

These tests validate the coordinate conversion from LLM bounding box responses
(in 0-1000 scale) to normalized 0-1 scale for the UI.

Note: Ruler offset adjustment is handled separately in strands_tools.py when
the LLM submits assessments. The models here work with document-space coordinates.
"""

import pytest
from idp_common.assessment.models import (
    BoundingBoxCoordinates,
    FieldAssessmentData,
    Geometry,
)


class TestBoundingBoxCoordinates:
    """Test BoundingBoxCoordinates model."""

    def test_from_corners_basic_conversion(self):
        """Test basic conversion from corner coordinates to normalized bbox."""
        bbox = BoundingBoxCoordinates.from_corners(
            x1=100,
            y1=200,
            x2=300,
            y2=400,
            scale=1000.0,
        )

        assert bbox.left == 0.1
        assert bbox.top == 0.2
        assert bbox.width == 0.2
        assert bbox.height == 0.2

    def test_from_corners_handles_reversed_coordinates(self):
        """Test that coordinates are corrected when reversed."""
        bbox = BoundingBoxCoordinates.from_corners(
            x1=300,
            y1=400,
            x2=100,
            y2=200,  # Reversed
            scale=1000.0,
        )

        # Should be corrected to proper order
        assert bbox.left == 0.1
        assert bbox.top == 0.2
        assert bbox.width == 0.2
        assert bbox.height == 0.2

    def test_from_corners_clamps_to_valid_range(self):
        """Test that values are clamped to 0-1 range."""
        # Coordinates that would exceed bounds
        bbox = BoundingBoxCoordinates.from_corners(
            x1=-50,
            y1=-50,
            x2=1100,
            y2=1100,
            scale=1000.0,
        )

        # Should clamp to valid range
        assert bbox.left >= 0.0
        assert bbox.top >= 0.0
        assert bbox.left + bbox.width <= 1.0
        assert bbox.top + bbox.height <= 1.0

    def test_from_corners_edge_coordinates(self):
        """Test with coordinates at edges of document."""
        # Full document bbox
        bbox = BoundingBoxCoordinates.from_corners(
            x1=0,
            y1=0,
            x2=1000,
            y2=1000,
            scale=1000.0,
        )

        assert bbox.left == 0.0
        assert bbox.top == 0.0
        assert bbox.width == 1.0
        assert bbox.height == 1.0

    def test_from_corners_small_region(self):
        """Test with a small region."""
        bbox = BoundingBoxCoordinates.from_corners(
            x1=500,
            y1=500,
            x2=510,
            y2=510,
            scale=1000.0,
        )

        assert bbox.left == 0.5
        assert bbox.top == 0.5
        assert bbox.width == 0.01
        assert bbox.height == 0.01


class TestGeometry:
    """Test Geometry model."""

    def test_from_bbox_list_valid(self):
        """Test creation from bbox list format."""
        # LLM response format: [x1, y1, x2, y2] in 0-1000 scale
        geom = Geometry.from_bbox_list([100, 200, 300, 400], page_num=1)

        assert geom.page == 1
        assert geom.boundingBox is not None
        assert geom.boundingBox.left == 0.1  # 100/1000
        assert geom.boundingBox.top == 0.2  # 200/1000

    def test_from_bbox_list_different_page(self):
        """Test creation with different page number."""
        geom = Geometry.from_bbox_list([100, 200, 300, 400], page_num=3)

        assert geom.page == 3
        assert geom.boundingBox is not None

    def test_from_bbox_list_invalid_length(self):
        """Test error handling for invalid coordinate count."""
        with pytest.raises(ValueError, match="Expected 4 coordinates"):
            Geometry.from_bbox_list([100, 200, 300], page_num=1)

    def test_to_ui_format(self):
        """Test conversion to UI-compatible format."""
        geom = Geometry.from_bbox_list([100, 200, 300, 400], page_num=2)
        ui_format = geom.to_ui_format()

        assert "boundingBox" in ui_format
        assert "page" in ui_format
        assert ui_format["page"] == 2
        assert "top" in ui_format["boundingBox"]
        assert "left" in ui_format["boundingBox"]
        assert "width" in ui_format["boundingBox"]
        assert "height" in ui_format["boundingBox"]


class TestFieldAssessmentData:
    """Test FieldAssessmentData model."""

    def test_from_llm_response_with_bbox(self):
        """Test creation from LLM response with bounding box."""
        assessment = FieldAssessmentData.from_llm_response(
            confidence=0.95,
            reasoning="Clear text with high OCR confidence",
            confidence_threshold=0.8,
            bbox_coords=[100, 200, 300, 400],
            page_num=1,
        )

        assert assessment.confidence == 0.95
        assert assessment.reasoning == "Clear text with high OCR confidence"
        assert assessment.geometry is not None
        assert len(assessment.geometry) == 1
        assert assessment.geometry[0].page == 1

    def test_from_llm_response_without_bbox(self):
        """Test creation from LLM response without bounding box."""
        assessment = FieldAssessmentData.from_llm_response(
            confidence=0.85,
            reasoning="Good text quality",
            confidence_threshold=0.8,
            bbox_coords=None,
            page_num=None,
        )

        assert assessment.confidence == 0.85
        assert assessment.geometry is None

    def test_to_explainability_format(self):
        """Test conversion to explainability format for frontend."""
        assessment = FieldAssessmentData.from_llm_response(
            confidence=0.95,
            reasoning="Clear text",
            confidence_threshold=0.8,
            bbox_coords=[100, 200, 300, 400],
            page_num=1,
        )

        result = assessment.to_explainability_format()

        assert result["confidence"] == 0.95
        assert result["confidence_reason"] == "Clear text"
        assert result["confidence_threshold"] == 0.8
        assert "geometry" in result
        assert len(result["geometry"]) == 1
        assert "boundingBox" in result["geometry"][0]
        assert result["geometry"][0]["page"] == 1
