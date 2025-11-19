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
from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.models.bedrock import BedrockModel
from strands.types.content import ContentBlock, Message

from idp_common.assessment.models import AssessmentResult, AssessmentTask
from idp_common.assessment.strands_models import AssessmentOutput
from idp_common.assessment.strands_tools import create_strands_tools
from idp_common.utils.bedrock_utils import (
    async_exponential_backoff_retry,
)

logger = Logger(service="assessment", level=os.getenv("LOG_LEVEL", "INFO"))


async def assess_attribute_with_strands(
    task: AssessmentTask,
    extraction_results: dict[str, Any],
    page_images: list[bytes],
    sorted_page_ids: list[str],
    model_id: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    document_schema: dict[str, Any],
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
        tools = base_tools
        # 2. Build enhanced system prompt with schema and extraction (for caching)
        enhanced_system_prompt = _build_system_prompt_with_context(
            system_prompt, document_schema, extraction_results, len(page_images)
        )

        # 3. Build minimal task-specific prompt (just field path and threshold)
        task_prompt = _build_task_prompt(task)

        # 4. Create Bedrock model config (following agentic_idp.py pattern)
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

        # 5. Initialize Strands agent
        agent = Agent(
            model=BedrockModel(**model_config),
            tools=tools,
            system_prompt=enhanced_system_prompt,
            state={
                "task": task.model_dump(),
                "extraction_results": extraction_results,
                "assessment_output": None,
            },
            conversation_manager=SummarizingConversationManager(
                summary_ratio=0.8, preserve_recent_messages=1
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
                "field_name": task.field_name,
            },
        )

        @async_exponential_backoff_retry(
            max_retries=30,
            initial_delay=5,
            exponential_base=2,
            jitter=0.5,
            max_delay=900,
        )
        async def invoke_agent_with_retry():
            return await agent.invoke_async([user_message])

        response = await invoke_agent_with_retry()
        logger.debug("Agent response received", extra={"task_id": task.task_id})

        # 7. Extract assessment from agent state
        assessment_dict = agent.state.get("assessment_output")
        if not assessment_dict:
            raise ValueError(
                "Agent did not produce assessment output. Agent may not have called submit_assessment tool."
            )

        # Validate to Pydantic model
        assessment_output = AssessmentOutput(**assessment_dict)

        # Validate that agent assessed the expected field
        # The agent may return:
        # - Just the field name: "Street"
        # - Full path with dots: "VendorAddress.Street"
        # - Full path with array indices: "Items[0].Description"
        # We accept any of these as long as the expected field_name appears
        expected_field = task.field_name
        assessed_field = assessment_output.field_name

        # Check if fields match:
        # 1. Exact match
        # 2. Expected field is at the end after a dot: "VendorAddress.Street" ends with ".Street"
        # 3. Expected field is at the end after bracket: "Items[0].Description" ends with ".Description"
        if not (
            assessed_field == expected_field
            or assessed_field.endswith(f".{expected_field}")
            or assessed_field.endswith(f"]{expected_field}")
            or f".{expected_field}" in assessed_field
            or f"]{expected_field}" in assessed_field
        ):
            raise ValueError(
                f"Agent assessed wrong field: expected '{expected_field}', "
                f"got '{assessed_field}'"
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


def _build_system_prompt_with_context(
    base_system_prompt: str,
    document_schema: dict[str, Any],
    extraction_results: dict[str, Any],
    num_images: int,
) -> str:
    """
    Build system prompt with full schema and extraction results for prompt caching.

    This puts the static/cacheable content (schema, extraction, general instructions)
    in the system prompt, which benefits from prompt caching.

    Args:
        base_system_prompt: Base assessment system prompt
        document_schema: Full JSON schema for the document class
        extraction_results: Complete extraction results
        num_images: Number of available page images

    Returns:
        Enhanced system prompt with schema and extraction context
    """
    return f"""{base_system_prompt}

## Document Schema

Below is the full JSON schema for this document type. This defines all fields, their types, and confidence thresholds.

```json
{json.dumps(document_schema, indent=2)}
```

## Complete Extraction Results

Below are the complete extraction results for the document being assessed. When assessing a specific field, locate its value in this structure.

```json
{json.dumps(extraction_results, indent=2)}
```

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

**Important**: You MUST call `submit_assessment` to complete each task.
"""


def _build_task_prompt(task: AssessmentTask) -> str:
    """
    Build minimal task-specific prompt for assessing a single field.

    This is minimal (just field path and threshold) to maximize the benefit
    of caching the system prompt which contains the schema and extraction.

    Args:
        task: Assessment task for one specific field

    Returns:
        Minimal task prompt string
    """
    # Convert field_path tuple to string representation
    # e.g., ("address", "street") -> "address.street"
    # e.g., ("items", 0, "price") -> "items[0].price"
    path_parts = []
    for part in task.field_path:
        if isinstance(part, int):
            path_parts[-1] = f"{path_parts[-1]}[{part}]"
        else:
            path_parts.append(str(part))
    field_path_str = ".".join(path_parts)

    return f"""# Assessment Task

Assess the confidence of this field:

**Field Path**: `{field_path_str}`
**Confidence Threshold**: {task.confidence_threshold}

Locate the value for `{field_path_str}` in the extraction results provided in the system context, verify it against the document images, and submit your assessment.

You MUST assess ONLY this field - do not assess any other fields.
"""


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
