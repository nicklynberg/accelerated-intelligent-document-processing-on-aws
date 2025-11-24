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
from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.models.bedrock import BedrockModel
from strands.types.content import CachePoint, ContentBlock, Message
from strands.types.media import ImageContent, ImageSource

from idp_common.assessment.models import (
    AssessmentResult,
    AssessmentTask,
    FieldAssessmentData,
)
from idp_common.assessment.strands_models import AssessmentOutput
from idp_common.assessment.strands_tools import create_strands_tools
from idp_common.bedrock import build_model_config
from idp_common.utils.bedrock_utils import async_exponential_backoff_retry

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

    # 1. Create tools (image viewer + todo list + submit assessment)
    tools = create_strands_tools(page_images, sorted_page_ids)

    # 2. Build enhanced system prompt with schema and extraction (for caching)
    enhanced_system_prompt = _build_system_prompt_with_context(
        system_prompt, document_schema, extraction_results, len(page_images)
    )

    # 3. Build minimal task-specific prompt (just field path and threshold)
    task_prompt = _build_task_prompt(task, page_images)

    # 4. Create Bedrock model config using shared utility
    model_config = build_model_config(
        model_id=model_id,
        max_tokens=max_tokens,
        max_retries=max_retries,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )
    # Add temperature (not handled by build_model_config)
    model_config["temperature"] = temperature

    # 5. Initialize Strands agent
    agent = Agent(
        model=BedrockModel(**model_config),
        tools=tools,
        system_prompt=enhanced_system_prompt,
        state={
            "task": task.model_dump(),
            "assessment_output": None,  # Will be populated by submit_assessment tool
        },
        conversation_manager=SummarizingConversationManager(
            summary_ratio=0.8, preserve_recent_messages=1
        ),
    )

    # 6. Create user message and run agent with retry
    user_message = Message(role="user", content=task_prompt)

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

    try:
        response = await invoke_agent_with_retry()
        logger.debug("Agent response received", extra={"task_id": task.task_id})
    except Exception as e:
        logger.error(
            "Agent invocation failed",
            extra={"task_id": task.task_id, "error": str(e)},
        )
        return AssessmentResult(
            task_id=task.task_id,
            success=False,
            assessment_data={},
            confidence_alerts=[],
            error_message=f"Agent invocation failed: {str(e)}",
            processing_time=time.time() - start_time,
        )

    # 7. Extract and validate assessment from agent state
    assessment_dict = agent.state.get("assessment_output")
    if not assessment_dict:
        return AssessmentResult(
            task_id=task.task_id,
            success=False,
            assessment_data={},
            confidence_alerts=[],
            error_message="Agent did not produce assessment output. Agent may not have called submit_assessment tool.",
            processing_time=time.time() - start_time,
        )

    try:
        assessment_output = AssessmentOutput(**assessment_dict)
    except Exception as e:
        return AssessmentResult(
            task_id=task.task_id,
            success=False,
            assessment_data={},
            confidence_alerts=[],
            error_message=f"Invalid assessment output format: {str(e)}",
            processing_time=time.time() - start_time,
        )

    # Validate that agent assessed the expected field
    if not _field_names_match(task.field_name, assessment_output.field_name):
        return AssessmentResult(
            task_id=task.task_id,
            success=False,
            assessment_data={},
            confidence_alerts=[],
            error_message=f"Agent assessed wrong field: expected '{task.field_name}', got '{assessment_output.field_name}'",
            processing_time=time.time() - start_time,
        )

    # 8. Extract metering from response
    metering = _extract_metering(response, model_id)

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


def _field_names_match(expected: str, actual: str) -> bool:
    """
    Check if field names match, handling nested paths with dots and array indices.

    Examples:
        - "address.street" matches "address.street"
        - "items[0].price" matches "items[0].price"
        - "address" matches "address"

    Args:
        expected: Expected field name/path
        actual: Actual field name/path from agent

    Returns:
        True if field names match
    """
    return expected == actual


def _extract_metering(response: Any, model_id: str) -> dict[str, Any]:
    """
    Extract metering data from Strands AgentResult response.

    Args:
        response: AgentResult from agent.invoke_async() (has metrics attribute)
        model_id: Model ID for metering key

    Returns:
        Metering dict with token usage, or empty dict if no metrics
    """
    metering = {}
    # AgentResult has metrics attribute at runtime (from Strands)
    if (
        hasattr(response, "metrics")
        and response.metrics
        and hasattr(response.metrics, "accumulated_usage")
        and response.metrics.accumulated_usage
    ):  # type: ignore[attr-defined]
        token_usage = {
            "inputTokens": response.metrics.accumulated_usage.get("inputTokens", 0),  # type: ignore[attr-defined]
            "outputTokens": response.metrics.accumulated_usage.get("outputTokens", 0),  # type: ignore[attr-defined]
            "totalTokens": response.metrics.accumulated_usage.get("totalTokens", 0),  # type: ignore[attr-defined]
            "cacheReadInputTokens": response.metrics.accumulated_usage.get(  # type: ignore[attr-defined]
                "cacheReadInputTokens", 0
            ),
            "cacheWriteInputTokens": response.metrics.accumulated_usage.get(  # type: ignore[attr-defined]
                "cacheWriteInputTokens", 0
            ),
        }
        metering[f"assessment/bedrock/{model_id}"] = token_usage

    return metering


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


def _convert_field_path_to_string(field_path: tuple[str | int, ...]) -> str:
    """
    Convert field path tuple to dot notation string.

    Examples:
        ("address", "street") → "address.street"
        ("items", 0, "price") → "items[0].price"
        ("orders", 2, "line_items", 1, "quantity") → "orders[2].line_items[1].quantity"

    Args:
        field_path: Tuple of field names (str) and array indices (int)

    Returns:
        Dot notation path string with array indices in brackets
    """
    path_parts = []
    for part in field_path:
        if isinstance(part, int):
            # Append array index to previous part: "items" → "items[0]"
            path_parts[-1] = f"{path_parts[-1]}[{part}]"
        else:
            # Add new field name
            path_parts.append(str(part))

    return ".".join(path_parts)


def _build_task_prompt(
    task: AssessmentTask, page_images: list[bytes]
) -> list[ContentBlock]:
    """
    Build minimal task-specific prompt for assessing a single field.

    This is minimal (just field path and threshold) to maximize the benefit
    of caching the system prompt which contains the schema and extraction.

    Args:
        task: Assessment task for one specific field
        page_images: List of page images to include in the prompt

    Returns:
        List of content blocks with images and task text
    """
    field_path_str = _convert_field_path_to_string(task.field_path)

    # Create image content blocks
    image_blocks = [
        ContentBlock(image=ImageContent(format="png", source=ImageSource(bytes=img)))
        for img in page_images
    ]

    # Create task instruction block
    task_block = ContentBlock(
        text=f"""# Assessment Task

        Assess the confidence of this field:

        **Field Path**: `{field_path_str}`
        **Confidence Threshold**: {task.confidence_threshold}

        Locate the value for `{field_path_str}` in the extraction results provided in the system context, verify it against the document images, and submit your assessment.

        You MUST assess ONLY this field - do not assess any other fields.
        """
    )

    # Add cache point after task instructions
    cache_block = ContentBlock(cachePoint=CachePoint(type="default"))

    return [*image_blocks, task_block, cache_block]


def _convert_to_assessment_result(
    task: AssessmentTask,
    output: AssessmentOutput,
    metering: dict[str, Any],
    processing_time: float,
) -> AssessmentResult:
    """
    Convert Strands AssessmentOutput to AssessmentResult with standardized geometry format.

    The assessment_data is returned as a flat dict (not wrapped by field name) because
    the aggregation step uses task.field_path for insertion into the final structure.
    """
    field_name = output.field_name
    assessment = output.assessment

    # Create standardized field assessment data
    field_data = FieldAssessmentData.from_llm_response(
        confidence=assessment.confidence,
        value=assessment.value,
        reasoning=assessment.reasoning,
        confidence_threshold=task.confidence_threshold,
        bbox_coords=(
            [
                assessment.bounding_box.x1,
                assessment.bounding_box.y1,
                assessment.bounding_box.x2,
                assessment.bounding_box.y2,
            ]
            if assessment.bounding_box
            else None
        ),
        page_num=assessment.bounding_box.page if assessment.bounding_box else None,
    )

    # Return assessment data directly (not wrapped by field name)
    # The aggregation step uses task.field_path for proper insertion
    assessment_data = field_data.to_explainability_format()

    # Check for confidence threshold violations
    confidence_alerts = []
    if assessment.confidence < task.confidence_threshold:
        confidence_alerts.append(
            {
                "attribute_name": field_name,
                "confidence": assessment.confidence,
                "confidence_threshold": task.confidence_threshold,
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
