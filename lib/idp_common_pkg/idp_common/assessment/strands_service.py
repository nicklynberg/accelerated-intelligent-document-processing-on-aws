"""
Core assessment service using Strands agents with interactive tools.

This module provides the main assessment functions that use Strands agents
to assess extraction confidence with bounding boxes and interactive image viewing.
"""

import json
import os
import time
from typing import Any

from aws_lambda_powertools import Logger
from botocore.config import Config
from pydantic import BaseModel
from strands import Agent, tool
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.models.bedrock import BedrockModel
from strands.types.content import ContentBlock, Message

from idp_common.assessment.strands_models import AssessmentOutput
from idp_common.assessment.strands_tools import create_strands_tools

logger = Logger(service="assessment", level=os.getenv("LOG_LEVEL", "INFO"))


# Pydantic versions of AssessmentTask/Result for Strands compatibility
# Note: granular_service has dataclass versions - these are separate for Strands
class AssessmentTask(BaseModel):
    """Assessment task definition."""

    task_id: str
    task_type: str
    attributes: list[str]
    task_schema: dict[str, Any]
    confidence_thresholds: dict[str, float]


class AssessmentResult(BaseModel):
    """Assessment result."""

    task_id: str
    success: bool
    assessment_data: dict[str, Any]
    confidence_alerts: list[dict[str, Any]]
    error_message: str | None = None
    processing_time: float = 0.0
    metering: dict[str, Any] | None = None


def create_submit_assessment_tool():
    """
    Create a tool for submitting assessment results.

    Returns:
        A Strands tool function for submitting assessments
    """

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
        validated_assessment = AssessmentOutput(**assessment)  # pyright: ignore[reportCallIssue]

        # Store in agent state
        agent.state.set("assessment_output", validated_assessment.model_dump())

        logger.info(
            "Assessment submitted successfully",
            extra={"assessment": validated_assessment.model_dump()},
        )

        return "Assessment submitted successfully. You can now finish the task."

    return submit_assessment


async def assess_attribute_with_strands(
    task: AssessmentTask,
    extraction_results: dict[str, Any],
    page_images: list[bytes],
    sorted_page_ids: list[str],
    model_id: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    max_retries: int = 7,
    connect_timeout: float = 10.0,
    read_timeout: float = 300.0,
) -> AssessmentResult:
    """
    Assess attributes using Strands agent with interactive tools.

    Args:
        task: Assessment task to process
        base_content: Base prompt content (includes images)
        extraction_results: Full extraction results
        page_images: List of page images (with grid overlay already applied)
        sorted_page_ids: List of page IDs in sorted order
        model_id: Bedrock model ID
        system_prompt: System prompt for assessment
        temperature: Model temperature
        max_tokens: Max tokens for response
        max_retries: Maximum retry attempts for API calls
        connect_timeout: Connection timeout in seconds
        read_timeout: Read timeout in seconds

    Returns:
        AssessmentResult with structured assessment data
    """
    start_time = time.time()

    try:
        # 1. Create tools (image viewer + todo list + submit assessment)
        base_tools = create_strands_tools(page_images, sorted_page_ids)
        submit_tool = create_submit_assessment_tool()
        tools = base_tools + [submit_tool]

        # 2. Build task-specific prompt
        task_prompt = _build_task_prompt(task, extraction_results, len(page_images))

        # 3. Create Bedrock model config (following agentic_idp.py pattern)
        boto_config = Config(
            retries={
                "max_attempts": max_retries,
                "mode": "adaptive",
            },
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )

        model_config = {
            "model_id": model_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "boto_client_config": boto_config,
        }

        # 4. Initialize Strands agent
        agent = Agent(
            model=BedrockModel(**model_config),
            tools=tools,
            system_prompt=system_prompt,
            state={
                "task": task.model_dump(),
                "extraction_results": extraction_results,
                "assessment_output": None,
            },
            conversation_manager=SummarizingConversationManager(
                summary_ratio=0.8, preserve_recent_messages=2
            ),
        )

        # 5. Create user message with task prompt
        user_message = Message(role="user", content=[ContentBlock(text=task_prompt)])

        # 6. Run agent
        logger.info(
            "Starting Strands assessment",
            extra={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "attributes": task.attributes,
            },
        )

        response = await agent.invoke_async([user_message])

        logger.debug("Agent response received", extra={"task_id": task.task_id})

        # 7. Extract assessment from agent state
        assessment_dict = agent.state.get("assessment_output")
        if not assessment_dict:
            raise ValueError(
                "Agent did not produce assessment output. Agent may not have called submit_assessment tool."
            )

        # Validate to Pydantic model
        assessment_output = AssessmentOutput(**assessment_dict)

        # Validate that agent assessed exactly the expected field
        expected_field = task.attributes[0]  # Task assesses exactly one field
        if assessment_output.field_name != expected_field:
            raise ValueError(
                f"Agent assessed wrong field: expected '{expected_field}', "
                f"got '{assessment_output.field_name}'"
            )

        # 8. Extract metering from response
        metering = {}
        if response.metrics and response.metrics.accumulated_usage:
            token_usage = {
                "inputTokens": response.metrics.accumulated_usage.get("inputTokens", 0),
                "outputTokens": response.metrics.accumulated_usage.get(
                    "outputTokens", 0
                ),
                "totalTokens": response.metrics.accumulated_usage.get("totalTokens", 0),
                "cacheReadInputTokens": response.metrics.accumulated_usage.get(
                    "cacheReadInputTokens", 0
                ),
                "cacheWriteInputTokens": response.metrics.accumulated_usage.get(
                    "cacheWriteInputTokens", 0
                ),
            }
            metering[f"assessment/bedrock/{model_id}"] = token_usage

        # 9. Convert to AssessmentResult format
        result = _convert_to_assessment_result(
            task,
            assessment_output,
            metering,
            time.time() - start_time,
        )

        logger.info(
            "Assessment completed successfully",
            extra={
                "task_id": task.task_id,
                "processing_time": result.processing_time,
                "success": result.success,
            },
        )

        return result

    except Exception as e:
        # Return failed result
        logger.error(
            "Assessment failed",
            extra={
                "task_id": task.task_id,
                "error": str(e),
                "processing_time": time.time() - start_time,
            },
        )

        return AssessmentResult(
            task_id=task.task_id,
            success=False,
            assessment_data={},
            confidence_alerts=[],
            error_message=str(e),
            processing_time=time.time() - start_time,
        )


def _build_task_prompt(
    task: AssessmentTask,
    extraction_results: dict[str, Any],
    num_images: int,
) -> str:
    """
    Build prompt for assessing a single field.

    Includes:
    - Clear field path (e.g., "address.street" or "items[2].price")
    - Full extraction results for context
    - Schema and threshold for the specific field
    - Instructions for using images and tools

    Args:
        task: Assessment task for one specific field
        extraction_results: Complete extraction results (arbitrarily nested)
        num_images: Number of available page images

    Returns:
        Formatted prompt string
    """
    # Get the single field being assessed
    field_path = task.attributes[
        0
    ]  # e.g., "name" or "address.street" or "items[0].price"
    threshold = list(task.confidence_thresholds.values())[0]

    prompt = f"""# Confidence Assessment Task

You are assessing the confidence of a SINGLE extracted field from a document.

## Field to Assess
**Field Path**: `{field_path}`
**Confidence Threshold**: {threshold}

## Complete Extraction Results
(Full document context - locate the value for `{field_path}`)
{json.dumps(extraction_results, indent=2)}

## Field Schema
{json.dumps(task.task_schema, indent=2)}

## Your Task
Assess ONLY the field `{field_path}`. Do not assess any other fields.

## Available Document Images

You have access to {num_images} document page images (indices 0-{num_images - 1}).
Each image has ruler markings along the edges showing the 0-1000 coordinate scale.

Use the `view_image` tool to:
1. View images to locate the extracted values
2. Draw bounding boxes to verify coordinates
3. Check if values are clearly visible and readable

## Assessment Process

1. **Plan**: Use `create_todo_list` to organize your assessment steps
2. **Locate**: Use `view_image` to find each value in the document
3. **Coordinate**: Determine precise bounding box coordinates using ruler markings (0-1000 scale)
4. **Assess**: Evaluate confidence based on:
   - Text clarity and OCR quality
   - Value correctness compared to what you see in the image
   - Bounding box accuracy
5. **Submit**: Use `submit_assessment` tool with your final assessment

## Bounding Box Format

Bounding boxes use normalized 0-1000 coordinates:
- x1, y1: Top-left corner
- x2, y2: Bottom-right corner
- page: Page number (1-indexed)

Example: {{"x1": 150, "y1": 220, "x2": 380, "y2": 245, "page": 1}}

## Output Schema

Your assessment must match the {task.task_type} schema.
Use the `submit_assessment` tool when ready with a complete assessment dict.

**Important**: You MUST call `submit_assessment` to complete this task.
"""
    return prompt


def _convert_to_assessment_result(
    task: AssessmentTask,
    output: AssessmentOutput,
    metering: dict[str, Any],
    processing_time: float,
) -> AssessmentResult:
    """Convert Strands AssessmentOutput to AssessmentResult."""

    # Single field assessment
    field_name = output.field_name
    assessment = output.assessment

    # Build assessment data with confidence score
    assessment_data = {
        field_name: {
            "confidence": assessment.confidence,
            "value": assessment.value,
            "reasoning": assessment.reasoning,
        }
    }

    # Add geometry if bounding box provided
    if assessment.bounding_box:
        assessment_data[field_name]["Geometry"] = assessment.bounding_box.to_geometry()

    # Check for confidence threshold violations
    confidence_alerts = []
    if not assessment.meets_threshold:
        confidence_alerts.append(
            {
                "attribute_name": field_name,
                "confidence": assessment.confidence,
                "confidence_threshold": assessment.threshold,
            }
        )

    return AssessmentResult(
        task_id=task.task_id,
        success=True,
        assessment_data=assessment_data,
        confidence_alerts=confidence_alerts,
        processing_time=processing_time,
        metering=metering,
    )
