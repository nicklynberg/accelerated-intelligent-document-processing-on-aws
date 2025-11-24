"""
Parallel executor for Strands-based assessment tasks.

This module provides asyncio-based parallel execution of assessment tasks
with concurrency control via semaphores.
"""

import asyncio
import os
import time
from typing import Any, cast

from aws_lambda_powertools import Logger

from idp_common.assessment.models import AssessmentResult, AssessmentTask
from idp_common.assessment.strands_service import assess_attribute_with_strands
from idp_common.utils import merge_metering_data

logger = Logger(service="assessment", level=os.getenv("LOG_LEVEL", "INFO"))


async def execute_tasks_async(
    tasks: list[AssessmentTask],
    extraction_results: dict[str, Any],
    page_images: list[bytes],
    sorted_page_ids: list[str],
    model_id: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    document_schema: dict[str, Any],
    max_concurrent: int = 5,
    max_retries: int = 7,
    connect_timeout: float = 10.0,
    read_timeout: float = 300.0,
) -> tuple[list[AssessmentResult], dict[str, Any]]:
    """
    Execute assessment tasks in parallel using asyncio.

    Args:
        tasks: List of assessment tasks to execute
        extraction_results: Full extraction results
        page_images: List of page images (with grid overlay)
        sorted_page_ids: List of page IDs
        model_id: Model to use
        system_prompt: System prompt
        temperature: Model temperature
        max_tokens: Max tokens
        document_schema: Full document JSON schema
        max_concurrent: Maximum concurrent tasks (default 5)
        max_retries: Maximum retry attempts
        connect_timeout: Connection timeout in seconds
        read_timeout: Read timeout in seconds

    Returns:
        Tuple of (results, combined_metering)
    """
    logger.info(
        f"Starting parallel execution of {len(tasks)} assessment tasks with max_concurrent={max_concurrent}"
    )

    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    async def execute_with_semaphore(task: AssessmentTask) -> AssessmentResult:
        """Execute task with semaphore to limit concurrency."""
        async with semaphore:
            logger.debug(
                f"Executing task {task.task_id} (type: {task.task_type})",
                extra={"task_id": task.task_id, "task_type": task.task_type},
            )
            return await assess_attribute_with_strands(
                task=task,
                extraction_results=extraction_results,
                page_images=page_images,
                sorted_page_ids=sorted_page_ids,
                model_id=model_id,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                document_schema=document_schema,
                max_retries=max_retries,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            )

    # Execute all tasks concurrently (with semaphore limit)
    # Use return_exceptions=True to capture failures without stopping others
    results = await asyncio.gather(
        *[execute_with_semaphore(task) for task in tasks],
        return_exceptions=True,
    )

    # Process results and handle exceptions
    processed_results: list[AssessmentResult] = []
    combined_metering: dict[str, Any] = {}

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            # Convert exception to failed AssessmentResult
            logger.error(
                f"Task {tasks[i].task_id} failed with exception",
                extra={
                    "task_id": tasks[i].task_id,
                    "exception": str(result),
                    "exception_type": type(result).__name__,
                },
            )
            processed_results.append(
                AssessmentResult(
                    task_id=tasks[i].task_id,
                    success=False,
                    assessment_data={},
                    confidence_alerts=[],
                    error_message=str(result),
                    processing_time=0.0,
                )
            )
        else:
            # result is AssessmentResult here (not Exception)
            assessment_result = cast(AssessmentResult, result)
            processed_results.append(assessment_result)
            # Merge metering data
            if assessment_result.metering:
                combined_metering = merge_metering_data(
                    combined_metering, assessment_result.metering
                )

    # Log summary
    successful_tasks = sum(1 for r in processed_results if r.success)
    failed_tasks = len(processed_results) - successful_tasks

    logger.info(
        f"Completed {len(processed_results)} tasks: {successful_tasks} successful, {failed_tasks} failed",
        extra={
            "total_tasks": len(processed_results),
            "successful": successful_tasks,
            "failed": failed_tasks,
        },
    )

    return processed_results, combined_metering


def execute_assessment_tasks_parallel(
    tasks: list[AssessmentTask],
    extraction_results: dict[str, Any],
    page_images: list[bytes],
    sorted_page_ids: list[str],
    model_id: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    document_schema: dict[str, Any],
    max_concurrent: int = 5,
    max_retries: int = 7,
    connect_timeout: float = 10.0,
    read_timeout: float = 300.0,
) -> tuple[list[AssessmentResult], dict[str, Any], float]:
    """
    Execute assessment tasks in parallel (synchronous wrapper).

    This is the main entry point called from process_document_section.
    It wraps the async executor and provides synchronous interface.

    Args:
        tasks: List of assessment tasks
        extraction_results: Full extraction results
        page_images: List of page images (with grid overlay already applied)
        sorted_page_ids: List of page IDs in sorted order
        model_id: Model ID
        system_prompt: System prompt
        temperature: Temperature
        max_tokens: Max tokens
        document_schema: Full document JSON schema
        max_concurrent: Max concurrent tasks (default 5)
        max_retries: Maximum retry attempts
        connect_timeout: Connection timeout in seconds
        read_timeout: Read timeout in seconds

    Returns:
        Tuple of (results, metering, duration)
    """
    logger.info(
        f"Starting parallel assessment execution for {len(tasks)} tasks",
        extra={"num_tasks": len(tasks), "max_concurrent": max_concurrent},
    )

    start_time = time.time()

    # Run async executor
    # Use asyncio.run() for clean event loop management
    try:
        results, metering = asyncio.run(
            execute_tasks_async(
                tasks=tasks,
                extraction_results=extraction_results,
                page_images=page_images,
                sorted_page_ids=sorted_page_ids,
                model_id=model_id,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                document_schema=document_schema,
                max_concurrent=max_concurrent,
                max_retries=max_retries,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            )
        )
    except RuntimeError as e:
        # Handle case where event loop already exists (shouldn't happen in Lambda)
        if "There is no current event loop" in str(e) or "asyncio.run()" in str(e):
            logger.warning(
                "Event loop already exists, using get_event_loop",
                extra={"error": str(e)},
            )
            loop = asyncio.get_event_loop()
            results, metering = loop.run_until_complete(
                execute_tasks_async(
                    tasks=tasks,
                    extraction_results=extraction_results,
                    page_images=page_images,
                    sorted_page_ids=sorted_page_ids,
                    model_id=model_id,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    document_schema=document_schema,
                    max_concurrent=max_concurrent,
                    max_retries=max_retries,
                    connect_timeout=connect_timeout,
                    read_timeout=read_timeout,
                )
            )
        else:
            raise

    duration = time.time() - start_time

    logger.info(
        f"Parallel assessment execution completed in {duration:.2f}s",
        extra={"duration_seconds": duration, "num_tasks": len(tasks)},
    )

    return results, metering, duration
