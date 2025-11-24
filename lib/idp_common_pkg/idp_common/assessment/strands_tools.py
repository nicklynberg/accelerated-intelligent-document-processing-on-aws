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
from idp_common.utils.grid_overlay import draw_bounding_boxes
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
    """
    Submit your final confidence assessment.

    Use this tool when you have:
    1. Located the values in the document images
    2. Determined precise bounding box coordinates using ruler markings
    3. Assessed the confidence based on clarity and accuracy

    Args:
        assessment: Dictionary with:
            - assessments: dict mapping attribute names to ConfidenceAssessment
            - alerts: list of any threshold alerts (optional)

    Returns:
        Success confirmation message or validation error details
    """
    # Validate assessment structure and return helpful errors
    validated_assessment = AssessmentOutput.model_validate(assessment)

    # Store in agent state
    agent.state.set("assessment_output", validated_assessment.model_dump())

    logger.info(
        "Assessment submitted successfully",
        extra={"assessment": validated_assessment.model_dump()},
    )

    return "Assessment submitted successfully. You can now finish the task."


def create_view_image_tool(page_images: list[bytes], sorted_page_ids: list[str]) -> Any:
    """
    Create a view_image tool that has access to page images.

    Args:
        page_images: List of page image bytes (with grid overlay already applied)
        sorted_page_ids: List of page IDs in sorted order

    Returns:
        A Strands tool function for viewing images
    """

    @tool
    def view_image(input_data: ViewImageInput, agent: Agent) -> dict:
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

        # Get the base image (already has grid overlay)
        img_bytes = page_images[view_input.image_index]
        page_id = sorted_page_ids[view_input.image_index]

        # If bounding box is specified, draw it on the image
        if view_input.bounding_box:
            # Convert BoundingBox to dict format for draw_bounding_boxes
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

            # Draw the bounding box on the image (which already has ruler)
            # Let drawing errors propagate - if we can't draw, something is wrong
            img_bytes = draw_bounding_boxes(
                img_bytes,
                [bbox_dict],
                has_ruler=True,
                ruler_width=30,
            )

            logger.debug(
                "Drew bounding box on image",
                extra={
                    "image_index": view_input.image_index,
                    "bbox": bbox_dict["bbox"],
                },
            )

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
