"""
Strands tools for confidence assessment with image viewing and grid overlay.

This module provides tools for Strands agents to view document pages and
mark bounding boxes during confidence assessment tasks.
"""

import os
from typing import Any

from aws_lambda_powertools import Logger
from pydantic import BaseModel, Field
from strands import Agent, tool

from idp_common.assessment.strands_models import AssessmentOutput, BoundingBox
from idp_common.utils.grid_overlay import add_ruler_and_draw_boxes, add_ruler_edges
from idp_common.utils.strands_agent_tools.todo_list import (
    create_todo_list,
    update_todo,
    view_todo_list,
)

logger = Logger(service="assessment", level=os.getenv("LOG_LEVEL", "INFO"))


class ViewImageInput(BaseModel):
    """Input model for view_image tool."""

    image_index: int = Field(
        ..., ge=0, description="Index of the page image to view (0-based)"
    )
    bounding_box: BoundingBox | None = Field(
        None, description="Optional bounding box to highlight on the image"
    )
    label: str | None = Field(None, description="Optional label for the bounding box")


@tool
def submit_assessment(assessment: AssessmentOutput, agent: Agent) -> str:
    """Submit the final assessment for a field."""
    # Validate assessment structure and return helpful errors
    validated_assessment = AssessmentOutput.model_validate(assessment)

    # Store in agent state - coordinates are in 0-1000 document space
    # The ruler shows 0-1000 scale mapping to the document, so LLM coordinates
    # are already in document space and need no adjustment
    agent.state.set("assessment_output", validated_assessment.model_dump(mode="json"))

    logger.info(
        "Assessment submitted successfully",
        extra={"assessment": validated_assessment.model_dump(mode="json")},
    )

    return "Assessment submitted successfully. You can now finish the task."


def create_view_image_tool(page_images: list[bytes], sorted_page_ids: list[str]) -> Any:
    """
    Create a view_image tool that has access to page images.

    Args:
        page_images: List of raw page image bytes (without ruler overlay)
        sorted_page_ids: List of page IDs in sorted order

    Returns:
        A Strands tool function for viewing images
    """

    @tool
    def view_image(input_data: ViewImageInput, agent: Agent) -> dict[str, Any]:
        """
        View a specific page image, optionally highlighting a bounding box area.

        Use this tool to examine document pages when assessing confidence.
        You can specify a bounding box to highlight a specific region.

        Args:
            input_data: Dictionary with:
                - image_index (int): Index of page to view (0-based)
                - bounding_box (dict, optional): Bounding box with x1, y1, x2, y2, page
                - label (str, optional): Label for the bounding box

        Returns:
            ImageContent object that the LLM can see

        Example:
            view_image({
                "image_index": 0,
                "bounding_box": {"x1": 100, "y1": 200, "x2": 300, "y2": 250, "page": 1},
                "label": "Account Number"
            }, agent)
        """
        # Validate input - let ValidationError propagate
        view_input = ViewImageInput.model_validate(input_data)

        # Validate image index exists
        if view_input.image_index >= len(page_images):
            raise ValueError(
                f"Invalid image_index {view_input.image_index}. "
                f"Valid range: 0-{len(page_images) - 1}"
            )

        # Get the raw image (no ruler overlay yet)
        raw_img_bytes = page_images[view_input.image_index]
        page_id = sorted_page_ids[view_input.image_index]

        # Add ruler and optionally draw bounding box
        if view_input.bounding_box:
            # Convert BoundingBox to dict format
            bbox_dict = {
                "bbox": [
                    view_input.bounding_box.x1,
                    view_input.bounding_box.y1,
                    view_input.bounding_box.x2,
                    view_input.bounding_box.y2,
                ],
                "label": view_input.label or "Highlighted Region",
                "color": "red",
            }

            # Add ruler overlay and draw bounding box in one step
            img_bytes = add_ruler_and_draw_boxes(raw_img_bytes, [bbox_dict])

            logger.debug(
                "Added ruler and drew bounding box on image",
                extra={
                    "image_index": view_input.image_index,
                    "bbox": bbox_dict["bbox"],
                },
            )
        else:
            # Just add ruler overlay (no bounding box)
            img_bytes = add_ruler_edges(raw_img_bytes)

        logger.info(
            "Returning image to agent",
            extra={
                "image_index": view_input.image_index,
                "page_id": page_id,
                "has_bbox": view_input.bounding_box is not None,
                "image_size_bytes": len(img_bytes),
            },
        )

        return {
            "status": "success",
            "content": [
                {
                    "image": {
                        "format": "png",
                        "source": {
                            "bytes": img_bytes,
                        },
                    }
                }
            ],
        }

    return view_image


def create_strands_tools(
    page_images: list[bytes], sorted_page_ids: list[str]
) -> list[Any]:
    """
    Create all tools needed for Strands-based assessment.

    Args:
        page_images: List of page image bytes (with grid overlay already applied)
        sorted_page_ids: List of page IDs in sorted order

    Returns:
        List of Strands tool functions
    """
    return [
        create_view_image_tool(page_images, sorted_page_ids),
        create_todo_list,
        update_todo,
        view_todo_list,
        submit_assessment,
    ]
