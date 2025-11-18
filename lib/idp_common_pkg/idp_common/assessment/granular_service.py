# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Granular assessment service for evaluating document extraction confidence using Strands agents.

This module provides a scalable approach to assessment by:
1. Breaking down assessments into single-field focused tasks
2. Leveraging Strands agents with tool-based interaction
3. Using parallel async execution for performance
4. Maintaining assessment structure that mirrors extraction results
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from idp_common import image, metrics, s3, utils
from idp_common.assessment.strands_executor import execute_assessment_tasks_parallel
from idp_common.config.models import IDPConfig
from idp_common.config.schema_constants import (
    SCHEMA_ITEMS,
    SCHEMA_PROPERTIES,
    SCHEMA_TYPE,
    TYPE_ARRAY,
    TYPE_OBJECT,
    X_AWS_IDP_CONFIDENCE_THRESHOLD,
    X_AWS_IDP_DOCUMENT_TYPE,
)
from idp_common.extraction.models import ExtractionData, ExtractionMetadata
from idp_common.models import Document, Status
from idp_common.utils import check_token_limit
from idp_common.utils.grid_overlay import add_ruler_edges

logger = logging.getLogger(__name__)


@dataclass
class AssessmentTask:
    """Single-field assessment task for Strands executor."""

    task_id: str
    task_type: str  # Always "attribute" - single field assessment

    # Path to field as tuple: ("address", "street") or ("items", 0, "price")
    field_path: Tuple[Union[str, int], ...]

    # The field name being assessed (last element of path)
    field_name: str

    # Schema for this specific field only
    field_schema: Dict[str, Any]

    # Confidence threshold for this field
    confidence_threshold: float

    # Direct reference to parent container in assessment structure (for O(1) insertion)
    # Can be Dict for regular fields or List for array items
    parent_assessment_dict: Union[Dict[str, Any], List[Any]]


@dataclass
class AssessmentResult:
    """Result of a single assessment task."""

    task_id: str
    success: bool
    assessment_data: Dict[str, Any]
    confidence_alerts: List[Dict[str, Any]]
    error_message: Optional[str] = None
    processing_time: float = 0.0
    metering: Optional[Dict[str, Any]] = None


def _safe_float_conversion(value: Any, default: float = 0.0) -> float:
    """
    Safely convert a value to float, handling strings and None values.

    Args:
        value: Value to convert to float
        default: Default value if conversion fails

    Returns:
        Float value or default if conversion fails
    """
    if value is None:
        return default

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        # Handle empty strings
        if not value.strip():
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(
                f"Could not convert string '{value}' to float, using default {default}"
            )
            return default

    # Handle other types by attempting conversion
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning(
            f"Could not convert {type(value)} '{value}' to float, using default {default}"
        )
        return default


def _get_value_at_path(data: Dict[str, Any], path: Tuple[Union[str, int], ...]) -> Any:
    """
    Navigate nested data structure using tuple path.

    Args:
        data: Nested dictionary/list structure
        path: Tuple of keys/indices like ("address", "street") or ("items", 0, "price")

    Returns:
        Value at the specified path, or None if path doesn't exist

    Examples:
        >>> data = {"address": {"street": "123 Main St"}}
        >>> _get_value_at_path(data, ("address", "street"))
        "123 Main St"

        >>> data = {"items": [{"price": 10.99}, {"price": 20.99}]}
        >>> _get_value_at_path(data, ("items", 0, "price"))
        10.99
    """
    current = data
    for key in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            if isinstance(key, int) and 0 <= key < len(current):
                current = current[key]
            else:
                return None
        else:
            return None
    return current


class GranularAssessmentService:
    """Enhanced assessment service with granular, cached, and parallel processing."""

    def __init__(
        self,
        region: str | None = None,
        config: Dict[str, Any] | IDPConfig | None = None,
        cache_table: str | None = None,
    ):
        """
        Initialize the granular assessment service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary or IDPConfig model
            cache_table: Optional DynamoDB table name for caching assessment task results
        """
        # Convert dict to IDPConfig if needed
        if config is not None and isinstance(config, dict):
            config_model: IDPConfig = IDPConfig(**config)
        elif config is None:
            config_model = IDPConfig()
        else:
            config_model = config

        self.config = config_model
        self.region = region or os.environ.get("AWS_REGION")

        # Assessment configuration (granular is now always enabled)
        self.max_workers = self.config.assessment.max_workers

        # Ensure safe minimum value
        self.max_workers = max(1, self.max_workers)

        # Auto-determine parallel processing
        # Parallel processing is enabled when max_workers > 1
        self.enable_parallel = self.max_workers > 1

        # Initialize caching for assessment tasks (similar to classification service)
        self.cache_table_name = cache_table or os.environ.get("TRACKING_TABLE")
        self.cache_table = None
        if self.cache_table_name:
            import boto3

            dynamodb = boto3.resource("dynamodb", region_name=self.region)
            self.cache_table = dynamodb.Table(self.cache_table_name)  # type: ignore[attr-defined]
            logger.info(
                f"Granular assessment caching enabled using table: {self.cache_table_name}"
            )
        else:
            logger.info("Granular assessment caching disabled")

        # Define throttling exceptions that should trigger retries
        self.throttling_exceptions = [
            "ThrottlingException",
            "ProvisionedThroughputExceededException",
            "ServiceQuotaExceededException",
            "TooManyRequestsException",
            "RequestLimitExceeded",
        ]

        # Get model_id from typed config for logging
        model_id = self.config.assessment.model
        logger.info(f"Initialized granular assessment service with model {model_id}")
        logger.info(
            f"Assessment config: max_workers={self.max_workers}, "
            f"parallel={self.enable_parallel}, "
            f"caching={'enabled' if self.cache_table else 'disabled'}"
        )

    def _get_class_schema(self, class_label: str) -> Dict[str, Any]:
        """
        Get JSON Schema for a specific document class.

        Args:
            class_label: The document class name

        Returns:
            JSON Schema dict for the class, or empty dict if not found
        """
        # Type-safe access to classes
        classes = self.config.classes
        for schema in classes:
            if schema.get(X_AWS_IDP_DOCUMENT_TYPE, "").lower() == class_label.lower():
                return schema
        return {}

    def _get_confidence_threshold_by_path(
        self, properties: Dict[str, Any], path: str, default: float = 0.9
    ) -> float:
        """
        Get confidence threshold for a property path (e.g., 'CompanyAddress.Street').
        Traverses JSON Schema following the path segments.

        Args:
            properties: JSON Schema properties dict
            path: Dot-separated path to the property
            default: Default threshold if not found

        Returns:
            Confidence threshold for the property
        """
        parts = path.split(".")
        current = properties

        for i, part in enumerate(parts):
            if part not in current:
                return default

            prop_schema = current[part]

            # Check for threshold at this level
            threshold_value = prop_schema.get(X_AWS_IDP_CONFIDENCE_THRESHOLD)
            if threshold_value is not None:
                return _safe_float_conversion(threshold_value, default)

            # Navigate deeper for nested paths
            if i < len(parts) - 1:
                prop_type = prop_schema.get(SCHEMA_TYPE)
                if prop_type == TYPE_OBJECT:
                    current = prop_schema.get(SCHEMA_PROPERTIES, {})
                elif prop_type == TYPE_ARRAY:
                    # For array items, get the items schema properties
                    items_schema = prop_schema.get(SCHEMA_ITEMS, {})
                    current = items_schema.get(SCHEMA_PROPERTIES, {})
                else:
                    # Can't navigate further
                    return default

        return default

    def _create_assessment_tasks(
        self,
        extraction_results: Dict[str, Any],
        properties: Dict[str, Any],
        default_confidence_threshold: float,
    ) -> Tuple[List[AssessmentTask], Dict[str, Any]]:
        """
        Create assessment tasks and pre-build assessment structure.

        This function recursively traverses the schema and extraction results to:
        1. Build an assessment structure that mirrors the extraction results
        2. Create one task per leaf field (no batching - one field at a time)
        3. Store direct parent dict references in tasks for O(1) insertion

        Args:
            extraction_results: The extraction results to assess
            properties: JSON Schema properties dict
            default_confidence_threshold: Default confidence threshold

        Returns:
            Tuple of (tasks, assessment_structure)
            - tasks: List of AssessmentTask objects
            - assessment_structure: Dict mirroring extraction_results shape
        """
        tasks: List[AssessmentTask] = []
        assessment_structure: Dict[str, Any] = {}
        task_counter = [0]  # Use list for mutable counter in nested function

        def _traverse(
            schema_props: Dict[str, Any],
            extraction_data: Dict[str, Any],
            current_path: Tuple[Union[str, int], ...],
            parent_dict: Dict[str, Any],
        ) -> None:
            """
            Recursively traverse schema and extraction data to build tasks and structure.

            Args:
                schema_props: Current level schema properties
                extraction_data: Current level extraction data
                current_path: Tuple path to current location
                parent_dict: Parent dict in assessment structure for insertion
            """
            for prop_name, prop_schema in schema_props.items():
                if prop_name not in extraction_data:
                    continue  # Skip properties not in extraction results

                prop_type = prop_schema.get(SCHEMA_TYPE)
                prop_value = extraction_data[prop_name]
                field_path = current_path + (prop_name,)

                if prop_type == TYPE_OBJECT and isinstance(prop_value, dict):
                    # Create nested dict in assessment structure
                    nested_dict: Dict[str, Any] = {}
                    parent_dict[prop_name] = nested_dict

                    # Recurse into nested object
                    nested_props = prop_schema.get(SCHEMA_PROPERTIES, {})
                    _traverse(nested_props, prop_value, field_path, nested_dict)

                elif prop_type == TYPE_ARRAY and isinstance(prop_value, list):
                    # Create list in assessment structure
                    assessment_list: List[Any] = []
                    parent_dict[prop_name] = assessment_list

                    # Process each array item
                    items_schema = prop_schema.get(SCHEMA_ITEMS, {})
                    item_type = items_schema.get(SCHEMA_TYPE)

                    for idx, item_value in enumerate(prop_value):
                        item_path = field_path + (idx,)

                        if item_type == TYPE_OBJECT and isinstance(item_value, dict):
                            # Create dict for this array item
                            item_dict: Dict[str, Any] = {}
                            assessment_list.append(item_dict)

                            # Recurse into array item properties
                            item_props = items_schema.get(SCHEMA_PROPERTIES, {})
                            _traverse(item_props, item_value, item_path, item_dict)

                        else:
                            # Leaf field in array - create task
                            threshold = self._get_confidence_threshold_by_path(
                                properties,
                                ".".join(str(p) for p in field_path),
                                default_confidence_threshold,
                            )

                            task = AssessmentTask(
                                task_id=f"task_{task_counter[0]}",
                                task_type="attribute",
                                field_path=item_path,
                                field_name=prop_name,
                                field_schema=items_schema,
                                confidence_threshold=threshold,
                                parent_assessment_dict=assessment_list,  # type: ignore
                            )
                            tasks.append(task)
                            task_counter[0] += 1

                            # Pre-allocate slot in list (will be replaced by assessment obj)
                            assessment_list.append(None)

                else:
                    # Leaf field - create task
                    threshold = self._get_confidence_threshold_by_path(
                        properties,
                        ".".join(str(p) for p in field_path),
                        default_confidence_threshold,
                    )

                    task = AssessmentTask(
                        task_id=f"task_{task_counter[0]}",
                        task_type="attribute",
                        field_path=field_path,
                        field_name=prop_name,
                        field_schema=prop_schema,
                        confidence_threshold=threshold,
                        parent_assessment_dict=parent_dict,
                    )
                    tasks.append(task)
                    task_counter[0] += 1

                    # Pre-allocate placeholder in dict (will be replaced by assessment obj)
                    parent_dict[prop_name] = None

        # Start recursive traversal from root
        _traverse(properties, extraction_results, (), assessment_structure)

        logger.info(f"Created {len(tasks)} assessment tasks (one per leaf field)")

        return tasks, assessment_structure

    def _get_cache_key(
        self, document_id: str, workflow_execution_arn: str, section_id: str
    ) -> str:
        """
        Generate cache key for assessment tasks.

        Args:
            document_id: Document ID
            workflow_execution_arn: Workflow execution ARN
            section_id: Section ID

        Returns:
            Cache key string
        """
        workflow_id = (
            workflow_execution_arn.split(":")[-1]
            if workflow_execution_arn
            else "unknown"
        )
        return f"assesscache#{document_id}#{workflow_id}#{section_id}"

    def _get_cached_assessment_tasks(
        self, document_id: str, workflow_execution_arn: str, section_id: str
    ) -> Dict[str, AssessmentResult]:
        """
        Retrieve cached assessment task results for a document section.

        Args:
            document_id: Document ID
            workflow_execution_arn: Workflow execution ARN
            section_id: Section ID

        Returns:
            Dictionary mapping task_id to cached AssessmentResult, empty dict if no cache
        """
        logger.info(
            f"Attempting to retrieve cached assessment tasks for document {document_id} section {section_id}"
        )

        if not self.cache_table:
            return {}

        cache_key = self._get_cache_key(document_id, workflow_execution_arn, section_id)

        try:
            response = self.cache_table.get_item(Key={"PK": cache_key, "SK": "tasks"})

            if "Item" not in response:
                logger.info(
                    f"No cache entry found for document {document_id} section {section_id}"
                )
                return {}

            # Parse cached data from JSON
            cached_data = response["Item"]
            logger.debug(f"Cached data keys: {list(cached_data.keys())}")
            task_results = {}

            # Extract task results from JSON attribute
            if "task_results" in cached_data:
                try:
                    import json

                    task_data_list = json.loads(cached_data["task_results"])

                    for task_data in task_data_list:
                        task_id = task_data["task_id"]
                        task_results[task_id] = AssessmentResult(
                            task_id=task_id,
                            success=task_data["success"],
                            assessment_data=task_data["assessment_data"],
                            confidence_alerts=task_data["confidence_alerts"],
                            error_message=task_data.get("error_message"),
                            processing_time=task_data.get("processing_time", 0.0),
                            metering=task_data.get("metering"),
                        )

                    if task_results:
                        logger.info(
                            f"Retrieved {len(task_results)} cached assessment task results for document {document_id} section {section_id} (PK: {cache_key})"
                        )

                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse cached assessment task results JSON for document {document_id} section {section_id}: {e}"
                    )

            return task_results

        except Exception as e:
            logger.warning(
                f"Failed to retrieve cached assessment tasks for document {document_id} section {section_id}: {e}"
            )
            return {}

    def _cache_successful_assessment_tasks(
        self,
        document_id: str,
        workflow_execution_arn: str,
        section_id: str,
        task_results: List[AssessmentResult],
    ) -> None:
        """
        Cache successful assessment task results to DynamoDB as a JSON-serialized list.

        Args:
            document_id: Document ID
            workflow_execution_arn: Workflow execution ARN
            section_id: Section ID
            task_results: List of successful assessment task results
        """
        if not self.cache_table or not task_results:
            return

        cache_key = self._get_cache_key(document_id, workflow_execution_arn, section_id)

        try:
            # Filter out failed task results and prepare data for JSON serialization
            successful_tasks = []
            for task_result in task_results:
                # Only cache successful tasks
                if task_result.success:
                    task_data = {
                        "task_id": task_result.task_id,
                        "success": task_result.success,
                        "assessment_data": task_result.assessment_data,
                        "confidence_alerts": task_result.confidence_alerts,
                        "error_message": task_result.error_message,
                        "processing_time": task_result.processing_time,
                        "metering": task_result.metering,
                    }
                    successful_tasks.append(task_data)

            if len(successful_tasks) == 0:
                logger.debug(
                    f"No successful assessment task results to cache for document {document_id} section {section_id}"
                )
                return

            # Prepare item structure with JSON-serialized task results
            import json
            from datetime import datetime, timedelta, timezone

            item = {
                "PK": cache_key,
                "SK": "tasks",
                "cached_at": str(int(time.time())),
                "document_id": document_id,
                "workflow_execution_arn": workflow_execution_arn,
                "section_id": section_id,
                "task_results": json.dumps(successful_tasks),
                "ExpiresAfter": int(
                    (datetime.now(timezone.utc) + timedelta(days=1)).timestamp()
                ),
            }

            # Store in DynamoDB using Table resource with JSON serialization
            self.cache_table.put_item(Item=item)

            logger.info(
                f"Cached {len(successful_tasks)} successful assessment task results for document {document_id} section {section_id} (PK: {cache_key})"
            )

        except Exception as e:
            logger.warning(
                f"Failed to cache assessment task results for document {document_id} section {section_id}: {e}"
            )

    def _is_throttling_exception(self, exception: Exception) -> bool:
        """
        Check if an exception is a throttling-related error that should trigger retries.

        Args:
            exception: Exception to check

        Returns:
            True if exception indicates throttling, False otherwise
        """
        if hasattr(exception, "response") and "Error" in exception.response:  # pyright: ignore[reportAttributeAccessIssue]
            error_code = exception.response["Error"]["Code"]  # pyright: ignore[reportAttributeAccessIssue]
            return error_code in self.throttling_exceptions

        # Check exception class name and message for throttling indicators
        exception_name = type(exception).__name__
        exception_message = str(exception).lower()

        return exception_name in self.throttling_exceptions or any(
            throttle_term.lower() in exception_message
            for throttle_term in self.throttling_exceptions
        )

    def _aggregate_assessment_results(
        self,
        tasks: List[AssessmentTask],
        results: List[AssessmentResult],
        assessment_structure: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Aggregate individual task results into assessment structure using direct parent insertion.

        Args:
            tasks: List of assessment tasks
            results: List of assessment results
            assessment_structure: Pre-built assessment structure from _create_assessment_tasks

        Returns:
            Tuple of (assessment_structure, confidence_alerts, aggregated_metering)
        """
        all_confidence_alerts = []
        aggregated_metering = {}

        # Create a mapping from task_id to result
        result_map = {result.task_id: result for result in results}

        # Process each task result - direct O(1) insertion using parent reference
        for task in tasks:
            result = result_map.get(task.task_id)
            if not result or not result.success:
                logger.warning(f"Task {task.task_id} failed or missing result")
                continue

            # Aggregate metering data
            if result.metering:
                aggregated_metering = utils.merge_metering_data(
                    aggregated_metering, result.metering
                )

            # Add confidence alerts
            all_confidence_alerts.extend(result.confidence_alerts)

            # Get assessment data from result - should be a single assessment object
            # The Strands agent returns the assessment in result.assessment_data
            assessment_obj = result.assessment_data

            if not isinstance(assessment_obj, dict):
                logger.warning(
                    f"Task {task.task_id}: expected dict assessment, got {type(assessment_obj)}"
                )
                continue

            # Add confidence_threshold to the assessment object
            assessment_obj["confidence_threshold"] = task.confidence_threshold

            # Direct insertion using parent reference - O(1) operation!
            parent = task.parent_assessment_dict
            field_name = task.field_name

            if isinstance(parent, dict):
                # Regular field - insert into parent dict
                parent[field_name] = assessment_obj
            elif isinstance(parent, list):
                # Array item - get index from field_path
                # field_path is like ("items", 0, "price") - second-to-last is the index
                if len(task.field_path) >= 2 and isinstance(task.field_path[-2], int):
                    idx = task.field_path[-2]
                    # Replace the None placeholder we created during structure building
                    if idx < len(parent):
                        parent[idx] = assessment_obj
                    else:
                        logger.warning(
                            f"Task {task.task_id}: index {idx} out of range for list of length {len(parent)}"
                        )
                else:
                    logger.warning(
                        f"Task {task.task_id}: cannot determine array index from path {task.field_path}"
                    )
            else:
                logger.warning(
                    f"Task {task.task_id}: unexpected parent type {type(parent)}"
                )

        return assessment_structure, all_confidence_alerts, aggregated_metering

    def _get_text_confidence_data(self, page) -> str:
        """
        Get text confidence data for a page from pre-generated text confidence files.

        Args:
            page: Page object containing OCR URIs

        Returns:
            JSON string of text confidence data, or empty string if unavailable
        """
        # First try to use the pre-generated text confidence file
        if hasattr(page, "text_confidence_uri") and page.text_confidence_uri:
            try:
                text_confidence_data = s3.get_json_content(page.text_confidence_uri)
                return json.dumps(text_confidence_data, indent=2)
            except Exception as e:
                logger.warning(
                    f"Failed to read text confidence data for page {page.page_id}: {str(e)}"
                )
                raise

        # Text confidence URI not available
        logger.error(
            f"Text confidence data unavailable for page {page.page_id}. "
            f"The text_confidence_uri field is missing or empty."
        )
        return "Text Confidence Data Unavailable"

    def _convert_bbox_to_geometry(
        self, bbox_coords: List[float], page_num: int
    ) -> Dict[str, Any]:
        """
        Convert [x1,y1,x2,y2] coordinates to geometry format.

        Args:
            bbox_coords: List of 4 coordinates [x1, y1, x2, y2] in 0-1000 scale
            page_num: Page number where the bounding box appears

        Returns:
            Dictionary in geometry format compatible with pattern-1 UI
        """
        if len(bbox_coords) != 4:
            raise ValueError(f"Expected 4 coordinates, got {len(bbox_coords)}")

        x1, y1, x2, y2 = bbox_coords

        # Ensure coordinates are in correct order
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        # Convert from normalized 0-1000 scale to 0-1
        left = x1 / 1000.0
        top = y1 / 1000.0
        width = (x2 - x1) / 1000.0
        height = (y2 - y1) / 1000.0

        return {
            "boundingBox": {"top": top, "left": left, "width": width, "height": height},
            "page": page_num,
        }

    def _process_single_assessment_geometry(
        self, attr_assessment: Dict[str, Any], attr_name: str = ""
    ) -> Dict[str, Any]:
        """
        Process geometry data for a single assessment (with confidence key).

        Args:
            attr_assessment: Single assessment dictionary with confidence data
            attr_name: Name of attribute for logging

        Returns:
            Enhanced assessment with geometry converted to proper format
        """
        enhanced_attr = attr_assessment.copy()

        # Check if this assessment includes bbox data
        if "bbox" in attr_assessment or "page" in attr_assessment:
            # Both bbox and page are required for valid geometry
            if "bbox" in attr_assessment and "page" in attr_assessment:
                try:
                    bbox_coords = attr_assessment["bbox"]
                    page_num = attr_assessment["page"]

                    # Validate bbox coordinates
                    if isinstance(bbox_coords, list) and len(bbox_coords) == 4:
                        # Convert to geometry format
                        geometry = self._convert_bbox_to_geometry(bbox_coords, page_num)
                        enhanced_attr["geometry"] = [geometry]

                        logger.debug(
                            f"Converted bounding box for {attr_name}: {bbox_coords} -> geometry format"
                        )
                    else:
                        logger.warning(
                            f"Invalid bounding box format for {attr_name}: {bbox_coords}"
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to process bounding box for {attr_name}: {str(e)}"
                    )
                    raise
            else:
                # If only one of bbox/page exists, log a warning about incomplete data
                if "bbox" in attr_assessment and "page" not in attr_assessment:
                    logger.warning(
                        f"Found bbox without page for {attr_name} - removing incomplete bbox data"
                    )
                elif "page" in attr_assessment and "bbox" not in attr_assessment:
                    logger.warning(
                        f"Found page without bbox for {attr_name} - removing incomplete page data"
                    )

            # Always remove raw bbox/page data from output (whether processed or incomplete)
            enhanced_attr.pop("bbox", None)
            enhanced_attr.pop("page", None)

        return enhanced_attr

    def _extract_geometry_from_assessment(
        self, assessment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract geometry data from assessment response and convert to proper format.
        Now supports recursive processing of nested group attributes.

        Args:
            assessment_data: Dictionary containing assessment results from LLM

        Returns:
            Enhanced assessment data with geometry information converted to proper format
        """
        enhanced_assessment = {}

        for attr_name, attr_assessment in assessment_data.items():
            if isinstance(attr_assessment, dict):
                # Check if this is a direct confidence assessment
                if "confidence" in attr_assessment:
                    # This is a direct assessment - process its geometry
                    enhanced_assessment[attr_name] = (
                        self._process_single_assessment_geometry(
                            attr_assessment, attr_name
                        )
                    )
                else:
                    # This is a group attribute (no direct confidence) - recursively process nested attributes
                    logger.debug(f"Processing group attribute: {attr_name}")
                    enhanced_assessment[attr_name] = (
                        self._extract_geometry_from_assessment(attr_assessment)
                    )

            elif isinstance(attr_assessment, list):
                # Handle list attributes - process each item recursively
                enhanced_list = []
                for i, item_assessment in enumerate(attr_assessment):
                    if isinstance(item_assessment, dict):
                        # Recursively process each list item
                        enhanced_item = self._extract_geometry_from_assessment(
                            item_assessment
                        )
                        enhanced_list.append(enhanced_item)
                    else:
                        # Non-dict items pass through unchanged
                        enhanced_list.append(item_assessment)
                enhanced_assessment[attr_name] = enhanced_list
            else:
                # Other types pass through unchanged
                enhanced_assessment[attr_name] = attr_assessment

        return enhanced_assessment

    def process_document_section(self, document: Document, section_id: str) -> Document:
        """
        Process a single section from a Document object to assess extraction confidence using granular approach.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process

        Returns:
            Document: Updated Document object with assessment results appended to extraction results
        """
        # Check if assessment is enabled in typed configuration
        if not self.config.assessment.enabled:
            logger.info("Assessment is disabled via configuration")
            return document

        if not document.sections:
            logger.error("Document has no sections to process")
            document.errors.append("Document has no sections to process")
            return document

        # Find the section with the given ID
        section = None
        for s in document.sections:
            if s.section_id == section_id:
                section = s
                break

        if not section:
            error_msg = f"Section {section_id} not found in document"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document

        # Check if section has extraction results to assess
        if not section.extraction_result_uri:
            error_msg = f"Section {section_id} has no extraction results to assess"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document

        # Extract information about the section
        class_label = section.classification

        # Check if the section has required pages
        if not section.page_ids:
            error_msg = f"Section {section_id} has no page IDs"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document

        # Sort pages by page number
        sorted_page_ids = sorted(section.page_ids, key=int)
        start_page = int(sorted_page_ids[0])
        end_page = int(sorted_page_ids[-1])
        logger.info(
            f"Granular assessing {len(sorted_page_ids)} pages, class {class_label}: {start_page}-{end_page}"
        )

        # Track metrics
        metrics.put_metric("InputDocumentsForGranularAssessment", 1)
        metrics.put_metric(
            "InputDocumentPagesForGranularAssessment", len(section.page_ids)
        )

        try:
            # Read existing extraction results
            t0 = time.time()
            extraction_data_dict = s3.get_json_content(section.extraction_result_uri)
            extraction_data = ExtractionData.model_validate(extraction_data_dict)
            extraction_results = extraction_data.inference_result

            # Skip assessment if no extraction results found
            if not extraction_results:
                logger.warning(f"No extraction results found for section {section_id}")
                return document

            t1 = time.time()
            logger.info(f"Time taken to read extraction results: {t1 - t0:.2f} seconds")

            # Read document text from all pages in order
            document_texts = []
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    error_msg = f"Page {page_id} not found in document"
                    logger.error(error_msg)
                    document.errors.append(error_msg)
                    continue

                page = document.pages[page_id]
                text_path = page.parsed_text_uri
                page_text = s3.get_text_content(text_path)
                document_texts.append(page_text)

            document_text = "\n".join(document_texts)
            t2 = time.time()
            logger.info(f"Time taken to read text content: {t2 - t1:.2f} seconds")

            # Read page images with configurable dimensions (type-safe access)
            target_width = self.config.assessment.image.target_width
            target_height = self.config.assessment.image.target_height

            page_images = []
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    continue

                page = document.pages[page_id]
                image_uri = page.image_uri
                # Just pass the values directly - prepare_image handles empty strings/None
                image_content = image.prepare_image(
                    image_uri, target_width, target_height
                )
                page_images.append(image_content)

            t3 = time.time()
            logger.info(f"Time taken to read images: {t3 - t2:.2f} seconds")

            # Read text confidence data for confidence information
            ocr_text_confidence = ""
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    continue

                page = document.pages[page_id]
                text_confidence_data_str = self._get_text_confidence_data(page)
                if text_confidence_data_str:
                    ocr_text_confidence += (
                        f"\n--- Page {page_id} Text Confidence Data ---\n"
                    )
                    ocr_text_confidence += text_confidence_data_str

            t4 = time.time()
            logger.info(f"Time taken to read raw OCR results: {t4 - t3:.2f} seconds")

            # Get schema for this document class
            class_schema = self._get_class_schema(class_label)
            if not class_schema:
                raise ValueError(f"No schema found for document class: {class_label}")

            # Get properties from JSON Schema
            properties = class_schema.get(SCHEMA_PROPERTIES, {})

            # Get confidence thresholds (type-safe, already float from Pydantic)
            default_confidence_threshold = (
                self.config.assessment.default_confidence_threshold
            )

            # Create assessment tasks and pre-built assessment structure
            tasks, assessment_structure = self._create_assessment_tasks(
                extraction_results, properties, default_confidence_threshold
            )

            if not tasks:
                logger.warning(f"No assessment tasks created for section {section_id}")
                return document

            # Check for cached assessment task results
            cached_task_results = self._get_cached_assessment_tasks(
                document.id, document.workflow_execution_arn, section_id
            )
            all_task_results = list(cached_task_results.values())
            combined_metering = {}

            # Determine which tasks need processing
            tasks_to_process = []
            for task in tasks:
                if task.task_id not in cached_task_results:
                    tasks_to_process.append(task)
                else:
                    # Task already cached - merge its metering data
                    cached_result = cached_task_results[task.task_id]
                    if cached_result.metering:
                        combined_metering = utils.merge_metering_data(
                            combined_metering, cached_result.metering
                        )

            if tasks_to_process:
                logger.info(
                    f"Found {len(cached_task_results)} cached assessment task results, processing {len(tasks_to_process)} remaining tasks"
                )

                # Apply grid overlay to page images for assessment
                grid_page_images = []
                for page_img in page_images:
                    grid_img = add_ruler_edges(page_img)
                    grid_page_images.append(grid_img)

                # Execute tasks using Strands-based parallel executor
                logger.info(
                    f"Processing {len(tasks_to_process)} assessment tasks with Strands executor (max_concurrent={self.max_workers})"
                )

                request_start_time = time.time()

                # Call Strands executor - handles both parallel and sequential based on max_concurrent
                task_results, task_metering, processing_time = (
                    execute_assessment_tasks_parallel(
                        tasks=tasks_to_process,
                        extraction_results=extraction_results,
                        page_images=grid_page_images,
                        sorted_page_ids=sorted_page_ids,
                        model_id=self.config.assessment.model,
                        system_prompt=self.config.assessment.system_prompt,
                        temperature=self.config.assessment.temperature,
                        max_tokens=self.config.assessment.max_tokens,
                        max_concurrent=self.max_workers,
                    )
                )

                # Merge results and metering
                all_task_results.extend(task_results)
                combined_metering = utils.merge_metering_data(
                    combined_metering, task_metering
                )

                logger.info(
                    f"Strands executor completed {len(task_results)} tasks in {processing_time:.2f}s"
                )

                # Track failed tasks for metadata
                failed_task_exceptions = {}
                for result in task_results:
                    if not result.success and result.error_message:
                        # Create a simple exception object for compatibility
                        failed_task_exceptions[result.task_id] = Exception(
                            result.error_message
                        )

                # Store failed task exceptions in document metadata for caller to access
                if failed_task_exceptions:
                    logger.info(
                        f"Processing {len(failed_task_exceptions)} failed assessment task exceptions for document {document.id} section {section_id}"
                    )

                    # Store the first throttling exception as the primary failure cause
                    throttling_exceptions = {
                        task_id: exc
                        for task_id, exc in failed_task_exceptions.items()
                        if self._is_throttling_exception(exc)
                    }

                    first_exception = next(iter(failed_task_exceptions.values()))
                    primary_exception = (
                        next(iter(throttling_exceptions.values()))
                        if throttling_exceptions
                        else first_exception
                    )

                    document.metadata = document.metadata or {}
                    document.metadata["failed_assessment_tasks"] = {
                        task_id: {
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                            "exception_class": exc.__class__.__module__
                            + "."
                            + exc.__class__.__name__,
                            "is_throttling": self._is_throttling_exception(exc),
                        }
                        for task_id, exc in failed_task_exceptions.items()
                    }
                    # Store the primary exception for easy access by caller
                    document.metadata["primary_exception"] = primary_exception

                # Check for any failed tasks (both exceptions and unsuccessful results)
                failed_results = [r for r in all_task_results if not r.success]
                any_failures = bool(failed_task_exceptions or failed_results)

                # Cache successful tasks only when there are failures (for retry optimization)
                if any_failures:
                    successful_results = [r for r in all_task_results if r.success]
                    if successful_results:
                        logger.info(
                            f"Caching {len(successful_results)} successful assessment task results for document {document.id} section {section_id} due to {len(failed_results)} failed results + {len(failed_task_exceptions)} failed exceptions (retry scenario)"
                        )
                        self._cache_successful_assessment_tasks(
                            document.id,
                            document.workflow_execution_arn,
                            section_id,
                            successful_results,
                        )
                    else:
                        logger.warning(
                            f"No successful assessment task results to cache for document {document.id} section {section_id} - all tasks failed"
                        )
                else:
                    # All new tasks succeeded - no need to cache since there won't be retries
                    logger.info(
                        f"All new assessment tasks succeeded for document {document.id} section {section_id} - skipping cache (no retry needed)"
                    )
            else:
                logger.info(
                    f"All {len(cached_task_results)} assessment task results found in cache"
                )
                request_start_time = (
                    time.time()
                )  # For consistency in timing calculations

            # Use all_task_results instead of results for aggregation
            results = all_task_results

            total_duration = time.time() - request_start_time
            logger.info(
                f"Time taken for granular assessment: {total_duration:.2f} seconds"
            )

            # Aggregate results into pre-built assessment structure
            (
                enhanced_assessment_data,
                confidence_threshold_alerts,
                aggregated_metering,
            ) = self._aggregate_assessment_results(tasks, results, assessment_structure)

            # Calculate success metrics
            successful_tasks = [r for r in results if r.success]
            failed_tasks = [r for r in results if not r.success]

            logger.info(
                f"Assessment completed: {len(successful_tasks)}/{len(tasks)} tasks successful"
            )

            # Handle failures - check if we should trigger state machine retries
            if failed_tasks:
                error_message = self._handle_parsing_errors(
                    document, failed_tasks, document_text, extraction_results
                )
                if error_message:
                    logger.error(f"Error: {error_message}")
                    # Errors are to be analyzed
                    # document.status = Status.FAILED
                    # document.errors.append(error_message)

                # Add task errors to document errors
                task_errors = [t.error_message for t in failed_tasks if t.error_message]
                if task_errors:
                    error_msg = self._convert_error_list_to_string(task_errors)
                    logger.error(f"Task Error: {error_msg}")
                    # Errors are to be analyzed
                    # document.status = Status.FAILED
                    # document.errors.append(error_msg)

                # Check if we should trigger state machine retries for throttling exceptions
                # This mirrors the classification service pattern
                if (
                    hasattr(document, "metadata")
                    and document.metadata
                    and "primary_exception" in document.metadata
                ):
                    primary_exception = document.metadata["primary_exception"]
                    if self._is_throttling_exception(primary_exception):
                        logger.error(
                            f"Re-raising throttling exception to trigger state machine retry: {type(primary_exception).__name__}"
                        )
                        # Update document status in AppSync before raising exception
                        # (this will be handled by the Lambda function)

                        # Re-raise the throttling exception to trigger state machine retries
                        raise primary_exception
                    else:
                        logger.warning(
                            f"Primary exception is not throttling-related: {type(primary_exception).__name__}. "
                            f"Document will be marked as failed without retry."
                        )

            # Update the existing extraction result with enhanced assessment data (typed)
            extraction_data.explainability_info = [enhanced_assessment_data]
            extraction_data.metadata.assessment_time_seconds = total_duration
            extraction_data.metadata.granular_assessment_used = True
            extraction_data.metadata.assessment_tasks_total = len(tasks)
            extraction_data.metadata.assessment_tasks_successful = len(successful_tasks)
            extraction_data.metadata.assessment_tasks_failed = len(failed_tasks)

            # Write the updated result back to S3
            bucket, key = utils.parse_s3_uri(section.extraction_result_uri)
            s3.write_content(
                extraction_data.model_dump(mode="json"),
                bucket,
                key,
                content_type="application/json",
            )

            # Update the section in the document with confidence threshold alerts
            for doc_section in document.sections:
                if doc_section.section_id == section_id:
                    doc_section.confidence_threshold_alerts = (
                        confidence_threshold_alerts
                    )
                    break

            # Update document with metering data
            document.metering = utils.merge_metering_data(
                document.metering, aggregated_metering or {}
            )
            t5 = time.time()
            logger.info(
                f"Total granular assessment time for section {section_id}: {t5 - t0:.2f} seconds"
            )
        except Exception as e:
            # Error is processed in the final results step
            error_msg = f"Error processing granular assessment for section {section_id}: {str(e)}"
            logger.error(error_msg)
            document.status = Status.FAILED
            document.errors.append(error_msg)

            # Check if this is a throttling exception and populate metadata for retry handling
            if self._is_throttling_exception(e):
                logger.info(
                    f"Populating metadata for throttling exception: {type(e).__name__}"
                )
                document.metadata = document.metadata or {}
                document.metadata["failed_assessment_tasks"] = {
                    "granular_processing": {
                        "exception_type": type(e).__name__,
                        "exception_message": str(e),
                        "exception_class": e.__class__.__module__
                        + "."
                        + e.__class__.__name__,
                        "is_throttling": True,
                    }
                }
                document.metadata["primary_exception"] = e

        # Additional check: if document status is FAILED and contains throttling errors,
        # populate metadata even if no exceptions were thrown
        if (
            document.status == Status.FAILED
            and document.errors
            and not hasattr(document, "metadata")
            or not document.metadata
            or "failed_assessment_tasks" not in document.metadata
        ):
            # Check if any errors contain throttling keywords
            throttling_keywords = [
                "throttlingexception",
                "provisionedthroughputexceededexception",
                "servicequotaexceededexception",
                "toomanyrequestsexception",
                "requestlimitexceeded",
                "too many tokens",
                "please wait before trying again",
                "reached max retries",
            ]

            has_throttling_error = False
            throttling_error_msg = None
            for error_msg in document.errors:
                error_lower = str(error_msg).lower()
                if any(keyword in error_lower for keyword in throttling_keywords):
                    has_throttling_error = True
                    throttling_error_msg = error_msg
                    break

            if has_throttling_error:
                logger.info(
                    f"Populating metadata for throttling error found in document.errors: {throttling_error_msg}"
                )
                document.metadata = document.metadata or {}
                document.metadata["failed_assessment_tasks"] = {
                    "document_level_error": {
                        "exception_type": "ThrottlingError",
                        "exception_message": throttling_error_msg,
                        "exception_class": "DocumentLevelThrottlingError",
                        "is_throttling": True,
                    }
                }

        return document

    def assess_document(self, document: Document) -> Document:
        """
        Assess extraction confidence for all sections in a document using granular approach.

        Args:
            document: Document object with extraction results

        Returns:
            Document: Updated Document object with assessment results
        """
        logger.info(f"Starting granular assessment for document {document.id}")

        for section in document.sections:
            if section.extraction_result_uri:
                logger.info(f"Granular assessing section {section.section_id}")
                document = self.process_document_section(document, section.section_id)
            else:
                logger.warning(
                    f"Section {section.section_id} has no extraction results to assess"
                )

        logger.info(f"Completed granular assessment for document {document.id}")
        return document

    def _handle_parsing_errors(
        self,
        document: Document,
        failed_tasks: List[str],
        document_text: str,
        extraction_results: Dict,
    ) -> Optional[str]:
        """Handle multiple parsing errors with user-friendly messaging."""
        # Check for token limit issues
        token_warning = check_token_limit(
            document_text, extraction_results, self.config
        )
        logger.info(f"Token Warning: {token_warning}")
        error_count = len(failed_tasks)
        base_msg = f"Assessment failed for {error_count} tasks. "
        if token_warning:
            return base_msg + token_warning
        else:
            return None

    def is_parsing_error(self, error_message: str) -> bool:
        """Check if an error message is related to parsing issues."""
        parsing_errors = ["parsing"]
        return any(error.lower() in error_message.lower() for error in parsing_errors)

    def _convert_error_list_to_string(self, errors) -> str:
        """Convert list of error messages to a single user-friendly string."""
        if not errors:
            return ""

        # Handle single string input
        if isinstance(errors, str):
            return errors

        # Ensure we have a list of strings
        if not isinstance(errors, list):
            return str(errors)

        # Count different types of errors
        parsing_errors = [e for e in errors if "parsing" in e.lower()]
        other_errors = [e for e in errors if "parsing" not in e.lower()]

        if len(parsing_errors) > 10:
            # Too many parsing errors - summarize
            return (
                f"Multiple parsing errors occurred {len(parsing_errors)} parsing errors, "
                f"{len(other_errors)} other errors. This suggests document complexity or token limit issues."
            )
        elif len(errors) > 5:
            # Multiple errors - show first few and summarize
            first_errors = "; ".join(errors[:1])
            return f"{first_errors} and {len(errors) - 1} more errors"
        else:
            # Few errors - show all
            return "; ".join(errors)
