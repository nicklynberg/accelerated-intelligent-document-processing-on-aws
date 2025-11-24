# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Assessment service for evaluating document extraction confidence using LLMs.

This module provides a service for assessing the confidence and accuracy of
extraction results by analyzing them against source documents using LLMs,
with support for text and image content.

The service supports both:
1. Original approach: Single inference for all attributes in a section
2. Granular approach: Multiple focused inferences with caching and parallelization
"""

import json
import logging
import os
import time
from typing import Any

from idp_common import bedrock, image, metrics, s3, utils
from idp_common.assessment.geometry_utils import extract_geometry_from_nested_dict
from idp_common.assessment.models import (
    ConfidenceAlert,
    DocumentContent,
    ExtractionData,
)
from idp_common.bedrock import format_prompt
from idp_common.config.models import IDPConfig
from idp_common.config.schema_constants import (
    SCHEMA_DESCRIPTION,
    SCHEMA_ITEMS,
    SCHEMA_PROPERTIES,
    SCHEMA_TYPE,
    TYPE_ARRAY,
    TYPE_OBJECT,
    TYPE_STRING,
    X_AWS_IDP_CONFIDENCE_THRESHOLD,
    X_AWS_IDP_DOCUMENT_TYPE,
    X_AWS_IDP_LIST_ITEM_DESCRIPTION,
)
from idp_common.models import Document
from idp_common.ocr.service import OcrService
from idp_common.utils import extract_json_from_text

logger = logging.getLogger(__name__)


class AssessmentService:
    """
    Service for assessing extraction result confidence using LLMs.

    This service evaluates extraction results by analyzing them against source documents,
    providing confidence scores and optional bounding box information for each extracted field.

    The class is organized into the following sections:
    1. INITIALIZATION - Setup and configuration
    2. SCHEMA & CONFIGURATION - Schema lookup and property formatting
    3. CONFIDENCE THRESHOLD HANDLING - Threshold validation and alert generation
    4. PROMPT BUILDING - Template processing and content preparation
    5. DATA LOADING - Loading document content and OCR data
    6. GEOMETRY PROCESSING - Bounding box conversion and validation
    7. PUBLIC API - Main entry points for assessment
    """

    # ============================================================================
    # INITIALIZATION
    # ============================================================================

    def __init__(
        self,
        region: str | None = None,
        config: dict[str, Any] | IDPConfig | None = None,
    ):
        """
        Initialize the assessment service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary or IDPConfig model
        """
        # Convert config to IDPConfig if needed
        if config is None:
            config_model = IDPConfig()
        elif isinstance(config, IDPConfig):
            config_model = config
        elif isinstance(config, dict):
            config_model = IDPConfig(**config)
        else:
            # Fallback: attempt conversion for other types
            try:
                config_model = IDPConfig(**config)
            except Exception as e:
                logger.error(f"Failed to convert config to IDPConfig: {e}")
                raise ValueError(
                    f"Invalid config type: {type(config)}. Expected None, dict, or IDPConfig instance."
                )

        self.config = config_model
        self.region = region or os.environ.get("AWS_REGION")

        # Get model_id from typed config for logging
        model_id = self.config.assessment.model
        logger.info(f"Initialized assessment service with model {model_id}")

    # ============================================================================
    # SCHEMA & CONFIGURATION
    # ============================================================================

    def _get_class_schema(self, class_label: str) -> dict[str, Any]:
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

    def _format_property_descriptions(self, schema: dict[str, Any]) -> str:
        """
        Format property descriptions from JSON Schema for the prompt.

        Args:
            schema: JSON Schema dict for the document class

        Returns:
            Formatted property descriptions as a string
        """
        properties = schema.get(SCHEMA_PROPERTIES, {})
        formatted_lines = []

        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get(SCHEMA_TYPE)
            description = prop_schema.get(SCHEMA_DESCRIPTION, "")

            if prop_type == TYPE_OBJECT:
                formatted_lines.append(f"{prop_name}  \t[ {description} ]")
                nested_props = prop_schema.get(SCHEMA_PROPERTIES, {})
                for nested_name, nested_schema in nested_props.items():
                    nested_desc = nested_schema.get(SCHEMA_DESCRIPTION, "")
                    formatted_lines.append(f"  - {nested_name}  \t[ {nested_desc} ]")

            elif prop_type == TYPE_ARRAY:
                formatted_lines.append(f"{prop_name}  \t[ {description} ]")
                items_schema = prop_schema.get(SCHEMA_ITEMS, {})

                item_desc = prop_schema.get(X_AWS_IDP_LIST_ITEM_DESCRIPTION, "")
                if item_desc:
                    formatted_lines.append(f"  Each item: {item_desc}")

                if items_schema.get(SCHEMA_TYPE) == TYPE_OBJECT:
                    item_props = items_schema.get(SCHEMA_PROPERTIES, {})
                    for item_name, item_schema in item_props.items():
                        item_prop_desc = item_schema.get(SCHEMA_DESCRIPTION, "")
                        formatted_lines.append(
                            f"  - {item_name}  \t[ {item_prop_desc} ]"
                        )
            else:
                formatted_lines.append(f"{prop_name}  \t[ {description} ]")

        return "\n".join(formatted_lines)

    # ============================================================================
    # CONFIDENCE THRESHOLD HANDLING
    # ============================================================================

    def _enhance_dict_assessment(
        self, assessment_dict: dict[str, Any], threshold: float
    ) -> dict[str, Any]:
        """
        Enhance an assessment dictionary by adding confidence thresholds to confidence assessments.

        Args:
            assessment_dict: Dictionary containing assessment data
            threshold: Confidence threshold to add

        Returns:
            Enhanced assessment dictionary
        """
        # Safety check: ensure assessment_dict is actually a dictionary
        if not isinstance(assessment_dict, dict):
            logger.warning(
                f"Expected dictionary for assessment enhancement, got {type(assessment_dict)}. "
                f"Creating default assessment structure."
            )
            return {
                "confidence": 0.5,
                "confidence_reason": f"LLM returned unexpected type {type(assessment_dict)} instead of dictionary. Using default confidence.",
                "confidence_threshold": threshold,
            }

        # Check if this dictionary itself is a confidence assessment
        if "confidence" in assessment_dict:
            # This is a direct confidence assessment - add threshold
            return {
                **assessment_dict,
                "confidence_threshold": threshold,
            }

        # Otherwise, check nested values for confidence assessments
        enhanced = {}
        for key, value in assessment_dict.items():
            if isinstance(value, dict) and "confidence" in value:
                # This is a nested confidence assessment - add threshold
                enhanced[key] = {
                    **value,
                    "confidence_threshold": threshold,
                }
            elif isinstance(value, dict):
                # Recursively process nested dictionaries
                enhanced[key] = self._enhance_dict_assessment(value, threshold)
            else:
                # Not a confidence assessment - pass through unchanged
                enhanced[key] = value
        return enhanced

    def _get_confidence_threshold(
        self, prop_schema: dict[str, Any], default: float
    ) -> float:
        """
        Get confidence threshold from property schema with validation.

        Args:
            prop_schema: Property schema dictionary
            default: Default threshold if not specified in schema

        Returns:
            Validated float threshold value
        """
        value = prop_schema.get(X_AWS_IDP_CONFIDENCE_THRESHOLD, default)
        # Use ConfidenceAlert's validator to parse the float safely
        return ConfidenceAlert(
            attribute_name="", confidence=0.0, confidence_threshold=value
        ).confidence_threshold

    def _check_confidence_alerts(
        self,
        assessment_data: dict[str, Any],
        attr_name: str,
        threshold: float,
        alerts_list: list[ConfidenceAlert],
    ) -> None:
        """
        Check assessment data for confidence threshold violations and add alerts.

        Args:
            assessment_data: Dictionary containing assessment data
            attr_name: Name of the attribute being assessed
            threshold: Confidence threshold to check against
            alerts_list: List to append alerts to (modified in place)
        """
        # Safety check: ensure assessment_data is actually a dictionary
        if not isinstance(assessment_data, dict):
            logger.warning(
                f"Expected dictionary for confidence alert checking, got {type(assessment_data)} for attribute '{attr_name}'. "
                f"Skipping confidence alert check."
            )
            return

        # First check if this assessment_data itself is a direct confidence assessment
        if "confidence" in assessment_data:
            alert = ConfidenceAlert(
                attribute_name=attr_name,
                confidence=assessment_data.get("confidence", 0.0),
                confidence_threshold=threshold,
            )
            if alert.confidence < alert.confidence_threshold:
                alerts_list.append(alert)

        # Then check for nested sub-attributes (for group/complex attributes)
        for sub_attr_name, sub_assessment in assessment_data.items():
            if isinstance(sub_assessment, dict) and "confidence" in sub_assessment:
                full_attr_name = (
                    f"{attr_name}.{sub_attr_name}"
                    if "." not in attr_name
                    else f"{attr_name}.{sub_attr_name}"
                )
                alert = ConfidenceAlert(
                    attribute_name=full_attr_name,
                    confidence=sub_assessment.get("confidence", 0.0),
                    confidence_threshold=threshold,
                )
                if alert.confidence < alert.confidence_threshold:
                    alerts_list.append(alert)

    # ============================================================================
    # PROMPT BUILDING
    # ============================================================================

    def _prepare_prompt_from_template(
        self,
        prompt_template: str,
        substitutions: dict[str, str],
        required_placeholders: list[str] | None = None,
    ) -> str:
        """
        Prepare prompt from template by replacing placeholders with values.

        Args:
            prompt_template: The prompt template with placeholders
            substitutions: Dictionary of placeholder values
            required_placeholders: List of placeholder names that must be present in the template

        Returns:
            String with placeholders replaced by values

        Raises:
            ValueError: If a required placeholder is missing from the template
        """
        return format_prompt(prompt_template, substitutions, required_placeholders)

    def _build_content_with_or_without_image_placeholder(
        self,
        prompt_template: str,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        extraction_results: str,
        ocr_text_confidence: str = "",
        image_content: Any = None,
    ) -> list[dict[str, Any]]:
        """
        Build content array, automatically deciding whether to use image placeholder processing.

        Args:
            prompt_template: The prompt template that may contain {DOCUMENT_IMAGE}
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            extraction_results: JSON string of extraction results to assess
            ocr_text_confidence: Raw OCR results with confidence scores
            image_content: Optional image content to insert

        Returns:
            List of content items with text and image content properly ordered
        """
        if "{DOCUMENT_IMAGE}" in prompt_template:
            return self._build_content_with_image_placeholder(
                prompt_template,
                document_text,
                class_label,
                attribute_descriptions,
                extraction_results,
                ocr_text_confidence,
                image_content,
            )
        else:
            return self._build_content_without_image_placeholder(
                prompt_template,
                document_text,
                class_label,
                attribute_descriptions,
                extraction_results,
                ocr_text_confidence,
                image_content,
            )

    def _build_content_with_image_placeholder(
        self,
        prompt_template: str,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        extraction_results: str,
        ocr_text_confidence: str,
        image_content: Any = None,
    ) -> list[dict[str, Any]]:
        """
        Build content array with image inserted at DOCUMENT_IMAGE placeholder if present.

        Args:
            prompt_template: The prompt template that may contain {DOCUMENT_IMAGE}
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            extraction_results: JSON string of extraction results to assess
            ocr_text_confidence: Raw OCR results with confidence scores
            image_content: Optional image content to insert

        Returns:
            List of content items with text and image content properly ordered
        """
        # Split the prompt at the DOCUMENT_IMAGE placeholder
        parts = prompt_template.split("{DOCUMENT_IMAGE}")

        if len(parts) != 2:
            raise ValueError(
                f"Invalid DOCUMENT_IMAGE placeholder usage: found {len(parts) - 1} occurrences, "
                f"but exactly 1 is required. The DOCUMENT_IMAGE placeholder must appear exactly once in the template."
            )

        # Process the parts before and after the image placeholder
        before_image = self._prepare_prompt_from_template(
            parts[0],
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
                "EXTRACTION_RESULTS": extraction_results,
                "OCR_TEXT_CONFIDENCE": ocr_text_confidence,
            },
            required_placeholders=[],  # Don't enforce required placeholders for partial templates
        )

        after_image = self._prepare_prompt_from_template(
            parts[1],
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
                "EXTRACTION_RESULTS": extraction_results,
                "OCR_TEXT_CONFIDENCE": ocr_text_confidence,
            },
            required_placeholders=[],  # Don't enforce required placeholders for partial templates
        )

        # Build content array with image in the middle
        content = []

        # Add the part before the image
        if before_image.strip():
            content.append({"text": before_image})

        # Add the image if available
        if image_content:
            if isinstance(image_content, list):
                # Multiple images - no limit with latest Bedrock API
                logger.info(
                    f"Attaching {len(image_content)} images to assessment prompt"
                )
                for img in image_content:
                    content.append(image.prepare_bedrock_image_attachment(img))
            else:
                # Single image
                content.append(image.prepare_bedrock_image_attachment(image_content))

        # Add the part after the image
        if after_image.strip():
            content.append({"text": after_image})

        return content

    def _build_content_without_image_placeholder(
        self,
        prompt_template: str,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        extraction_results: str,
        ocr_text_confidence: str,
        image_content: Any = None,
    ) -> list[dict[str, Any]]:
        """
        Build content array without DOCUMENT_IMAGE placeholder (text-only processing).

        Args:
            prompt_template: The prompt template
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            extraction_results: JSON string of extraction results to assess
            ocr_text_confidence: Raw OCR results with confidence scores
            image_content: Ignored - images are only attached when DOCUMENT_IMAGE placeholder is present

        Returns:
            List of content items with text content only
        """
        # Prepare the full prompt
        task_prompt = self._prepare_prompt_from_template(
            prompt_template,
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
                "EXTRACTION_RESULTS": extraction_results,
                "OCR_TEXT_CONFIDENCE": ocr_text_confidence,
            },
            required_placeholders=[],
        )

        # Return text content only - no images unless DOCUMENT_IMAGE placeholder is used
        return [{"text": task_prompt}]

    # ============================================================================
    # DATA LOADING
    # ============================================================================

    def _load_extraction_data(self, section) -> ExtractionData:
        """
        Load extraction results from S3.

        Args:
            section: Section object containing extraction_result_uri

        Returns:
            ExtractionData with extraction_results and full_data

        Raises:
            ValueError: If no extraction results found
        """
        extraction_data = s3.get_json_content(section.extraction_result_uri)
        extraction_results = extraction_data.get("inference_result", {})

        if not extraction_results:
            raise ValueError(
                f"No extraction results found for section {section.section_id}"
            )

        return ExtractionData(
            extraction_results=extraction_results, full_data=extraction_data
        )

    def _load_document_content(self, document: Document, section) -> DocumentContent:
        """
        Load document text, images, and OCR confidence for all pages in section.

        Args:
            document: Document object containing pages
            section: Section object with page_ids

        Returns:
            DocumentContent with document_text, page_images, and ocr_text_confidence
        """
        # Sort pages by page number
        sorted_page_ids = sorted(section.page_ids, key=int)

        # Read document text from all pages in order
        document_texts = []
        for page_id in sorted_page_ids:
            if page_id not in document.pages:
                logger.warning(f"Page {page_id} not found in document")
                continue

            page = document.pages[page_id]
            text_path = page.parsed_text_uri
            if text_path:
                page_text = s3.get_text_content(text_path)
                document_texts.append(page_text)

        document_text = "\n".join(document_texts)

        # Read page images with configurable dimensions
        target_width = self.config.assessment.image.target_width
        target_height = self.config.assessment.image.target_height

        page_images = []
        for page_id in sorted_page_ids:
            if page_id not in document.pages:
                continue

            page = document.pages[page_id]
            image_uri = page.image_uri
            if image_uri:
                image_content = image.prepare_image(
                    image_uri, target_width, target_height
                )
                page_images.append(image_content)

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

        return DocumentContent(
            document_text=document_text,
            page_images=page_images,
            ocr_text_confidence=ocr_text_confidence,
        )

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

        # Fallback: use raw OCR data if text confidence is not available (for backward compatibility)
        if page.raw_text_uri:
            try:
                ocr_service = OcrService()
                raw_ocr_data = s3.get_json_content(page.raw_text_uri)
                text_confidence_data = ocr_service._generate_text_confidence_data(
                    raw_ocr_data
                )
                return json.dumps(text_confidence_data, indent=2)
            except Exception as e:
                logger.warning(
                    f"Failed to generate text confidence data for page {page.page_id}: {str(e)}"
                )

        return ""

    # ============================================================================
    # GEOMETRY PROCESSING (uses shared utilities from geometry_utils)
    # ============================================================================

    # ============================================================================
    # RESULT PROCESSING
    # ============================================================================

    def _process_assessment_response(
        self,
        assessment_text: str,
        extraction_results: dict[str, Any],
        class_schema: dict[str, Any],
    ) -> tuple[dict[str, Any], list[ConfidenceAlert], bool]:
        """
        Process raw assessment response from LLM.

        Args:
            assessment_text: Raw text response from LLM
            extraction_results: Original extraction results
            class_schema: JSON Schema for the document class

        Returns:
            Tuple of (enhanced_assessment_data, confidence_alerts, parsing_succeeded)
        """
        # Parse response into JSON
        assessment_data = {}
        parsing_succeeded = True

        try:
            assessment_data = json.loads(extract_json_from_text(assessment_text))
        except Exception as e:
            logger.error(
                f"Error parsing assessment LLM output - invalid JSON?: {assessment_text} - {e}"
            )
            logger.info("Using default confidence scores.")
            # Create default assessments for all extracted attributes
            assessment_data = {}
            for attr_name in extraction_results.keys():
                assessment_data[attr_name] = {
                    "confidence": 0.5,
                    "confidence_reason": "Unable to parse assessment response - default score assigned",
                }
            parsing_succeeded = False

        # Process bounding boxes automatically if bbox data is present
        try:
            logger.debug("Checking for bounding box data in assessment response")
            assessment_data = extract_geometry_from_nested_dict(assessment_data)
        except Exception as e:
            logger.warning(f"Failed to extract geometry data: {str(e)}")

        # Enhance assessment data with confidence thresholds and create alerts
        enhanced_assessment_data, confidence_alerts = (
            self._enhance_and_check_thresholds(assessment_data, class_schema)
        )

        return enhanced_assessment_data, confidence_alerts, parsing_succeeded

    def _enhance_and_check_thresholds(
        self, assessment_data: dict[str, Any], class_schema: dict[str, Any]
    ) -> tuple[dict[str, Any], list[ConfidenceAlert]]:
        """
        Enhance assessment data with thresholds and generate alerts.

        Args:
            assessment_data: Raw assessment data from LLM
            class_schema: JSON Schema for the document class

        Returns:
            Tuple of (enhanced_assessment_data, confidence_alerts)
        """
        default_confidence_threshold = (
            self.config.assessment.default_confidence_threshold
        )

        enhanced_assessment_data = {}
        confidence_threshold_alerts: list[ConfidenceAlert] = []
        properties = class_schema.get(SCHEMA_PROPERTIES, {})

        for attr_name, attr_assessment in assessment_data.items():
            prop_schema = properties.get(attr_name, {})
            attr_threshold = self._get_confidence_threshold(
                prop_schema, default_confidence_threshold
            )

            # Get property type
            prop_type_json = prop_schema.get(SCHEMA_TYPE, TYPE_STRING)
            if prop_type_json == TYPE_OBJECT:
                attr_type = "group"
            elif prop_type_json == TYPE_ARRAY:
                attr_type = "list"
            else:
                attr_type = "simple"

            # Process based on type
            if isinstance(attr_assessment, dict):
                enhanced_assessment_data[attr_name] = self._enhance_dict_assessment(
                    attr_assessment, attr_threshold
                )
                self._check_confidence_alerts(
                    attr_assessment,
                    attr_name,
                    attr_threshold,
                    confidence_threshold_alerts,
                )

            elif isinstance(attr_assessment, list) and attr_type == "list":
                enhanced_list = []
                for i, item_assessment in enumerate(attr_assessment):
                    if isinstance(item_assessment, dict):
                        enhanced_item = self._enhance_dict_assessment(
                            item_assessment, attr_threshold
                        )
                        enhanced_list.append(enhanced_item)
                        self._check_confidence_alerts(
                            item_assessment,
                            f"{attr_name}[{i}]",
                            attr_threshold,
                            confidence_threshold_alerts,
                        )
                    else:
                        # Unexpected format within list
                        logger.warning(
                            f"List item {i} in attribute '{attr_name}' is not a dictionary. Using default confidence."
                        )
                        default_item = {
                            "confidence": 0.5,
                            "confidence_reason": f"List item {i} in '{attr_name}' has unexpected format.",
                            "confidence_threshold": attr_threshold,
                        }
                        enhanced_list.append(default_item)

                        if 0.5 < attr_threshold:
                            alert = ConfidenceAlert(
                                attribute_name=f"{attr_name}[{i}]",
                                confidence=0.5,
                                confidence_threshold=attr_threshold,
                            )
                            confidence_threshold_alerts.append(alert)

                enhanced_assessment_data[attr_name] = enhanced_list

            else:
                # Unexpected type - use default
                logger.warning(
                    f"Attribute '{attr_name}' has unexpected assessment format. Using default confidence."
                )
                default_assessment = {
                    "confidence": 0.5,
                    "confidence_reason": f"LLM returned unexpected format for '{attr_name}'.",
                    "confidence_threshold": attr_threshold,
                }
                enhanced_assessment_data[attr_name] = default_assessment

        return enhanced_assessment_data, confidence_threshold_alerts

    # ============================================================================
    # ASSESSMENT EXECUTION
    # ============================================================================

    def _execute_bedrock_assessment(
        self, content: list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any], float]:
        """
        Execute Bedrock model invocation for assessment.

        Args:
            content: Formatted content for the model

        Returns:
            Tuple of (assessment_text, metering_data, duration_seconds)
        """
        # Get assessment configuration
        model_id = self.config.assessment.model
        if not model_id:
            raise ValueError("Assessment model_id is required but not configured")

        request_start_time = time.time()

        # Invoke Bedrock
        response_with_metering = bedrock.invoke_model(
            model_id=model_id,
            system_prompt=self.config.assessment.system_prompt,
            content=content,
            temperature=self.config.assessment.temperature,
            top_k=self.config.assessment.top_k,
            top_p=self.config.assessment.top_p,
            max_tokens=self.config.assessment.max_tokens,
            context="Assessment",
        )

        total_duration = time.time() - request_start_time

        # Extract text from response
        assessment_text = bedrock.extract_text_from_response(response_with_metering)
        metering = response_with_metering.get("metering", {})

        return assessment_text, metering, total_duration

    # ============================================================================
    # VALIDATION & HELPERS
    # ============================================================================

    def _validate_and_get_section(self, document: Document, section_id: str):
        """
        Validate document and return the section to process.

        Args:
            document: Document object to validate
            section_id: ID of section to retrieve

        Returns:
            Section object

        Raises:
            ValueError: If validation fails
        """
        if not document:
            raise ValueError("No document provided")

        if not document.sections:
            raise ValueError("Document has no sections to process")

        # Find the section with the given ID
        section = None
        for s in document.sections:
            if s.section_id == section_id:
                section = s
                break

        if not section:
            raise ValueError(f"Section {section_id} not found in document")

        if not section.extraction_result_uri:
            raise ValueError(
                f"Section {section_id} has no extraction results to assess"
            )

        if not section.page_ids:
            raise ValueError(f"Section {section_id} has no page IDs")

        return section

    # ============================================================================
    # PUBLIC API
    # ============================================================================

    def process_document_section(self, document: Document, section_id: str) -> Document:
        """
        Process a single section from a Document object to assess extraction confidence.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process

        Returns:
            Document: Updated Document object with assessment results appended to extraction results
        """
        # Check if assessment is enabled
        if not self.config.assessment.enabled:
            logger.info("Assessment is disabled via configuration")
            return document

        # Validate and get section
        try:
            section = self._validate_and_get_section(document, section_id)
        except ValueError as e:
            logger.error(str(e))
            document.errors.append(str(e))
            return document

        class_label = section.classification

        # Sort pages by page number
        sorted_page_ids = sorted(section.page_ids, key=int)
        start_page = int(sorted_page_ids[0])
        end_page = int(sorted_page_ids[-1])
        logger.info(
            f"Assessing {len(sorted_page_ids)} pages, class {class_label}: {start_page}-{end_page}"
        )

        # Track metrics
        metrics.put_metric("InputDocumentsForAssessment", 1)
        metrics.put_metric("InputDocumentPagesForAssessment", len(section.page_ids))

        try:
            # Load extraction data
            t0 = time.time()
            extraction_data_model = self._load_extraction_data(section)
            extraction_results = extraction_data_model.extraction_results
            t1 = time.time()
            logger.info(f"Time taken to load extraction data: {t1 - t0:.2f} seconds")

            # Load document content (text, images, OCR confidence)
            document_content = self._load_document_content(document, section)
            t2 = time.time()
            logger.info(f"Time taken to load document content: {t2 - t1:.2f} seconds")

            # Get schema for this document class
            class_schema = self._get_class_schema(class_label)
            if not class_schema:
                raise ValueError(f"No schema found for document class: {class_label}")

            property_descriptions = self._format_property_descriptions(class_schema)

            # Prepare prompt (type-safe access)
            prompt_template = self.config.assessment.task_prompt
            extraction_results_str = json.dumps(extraction_results, indent=2)

            if not prompt_template:
                raise ValueError(
                    "Assessment task_prompt is required in configuration but not found"
                )
            else:
                # Use the unified content builder for DOCUMENT_IMAGE placeholder support
                try:
                    content = self._build_content_with_or_without_image_placeholder(
                        prompt_template,
                        document_content.document_text,
                        class_label,
                        property_descriptions,
                        extraction_results_str,
                        document_content.ocr_text_confidence,
                        document_content.page_images,
                    )
                except ValueError as e:
                    logger.error(f"Error formatting prompt template: {str(e)}")
                    raise ValueError(
                        f"Assessment prompt template formatting failed: {str(e)}"
                    )

            logger.info(
                f"Assessing extraction confidence for {class_label} document, section {section_id}"
            )

            # Execute Bedrock assessment
            assessment_text, metering, total_duration = (
                self._execute_bedrock_assessment(content)
            )
            logger.info(f"Time taken for assessment: {total_duration:.2f} seconds")

            # Process assessment response
            (
                enhanced_assessment_data,
                confidence_threshold_alerts,
                parsing_succeeded,
            ) = self._process_assessment_response(
                assessment_text, extraction_results, class_schema
            )

            # Update the existing extraction result with enhanced assessment data
            extraction_data_model.full_data["explainability_info"] = [
                enhanced_assessment_data
            ]
            extraction_data_model.full_data["metadata"] = (
                extraction_data_model.full_data.get("metadata", {})
            )
            extraction_data_model.full_data["metadata"]["assessment_time_seconds"] = (
                total_duration
            )
            extraction_data_model.full_data["metadata"][
                "assessment_parsing_succeeded"
            ] = parsing_succeeded

            # Write the updated result back to S3
            # extraction_result_uri is guaranteed to exist by _validate_and_get_section
            assert section.extraction_result_uri is not None
            bucket, key = utils.parse_s3_uri(section.extraction_result_uri)
            s3.write_content(
                extraction_data_model.full_data,
                bucket,
                key,
                content_type="application/json",
            )

            # Update the section in the document with confidence threshold alerts
            for doc_section in document.sections:
                if doc_section.section_id == section_id:
                    # Convert ConfidenceAlert objects to dicts with camelCase keys for UI
                    doc_section.confidence_threshold_alerts = [
                        alert.model_dump(by_alias=True)
                        for alert in confidence_threshold_alerts
                    ]
                    break

            # Update document with metering data
            document.metering = utils.merge_metering_data(
                document.metering, metering or {}
            )

            t5 = time.time()
            logger.info(
                f"Total assessment time for section {section_id}: {t5 - t0:.2f} seconds"
            )

        except Exception as e:
            error_msg = (
                f"Error processing assessment for section {section_id}: {str(e)}"
            )
            logger.error(error_msg)
            document.errors.append(error_msg)
            raise

        return document

    def assess_document(self, document: Document) -> Document:
        """
        Assess extraction confidence for all sections in a document.

        Args:
            document: Document object with extraction results

        Returns:
            Document: Updated Document object with assessment results
        """
        logger.info(f"Starting assessment for document {document.id}")

        for section in document.sections:
            if section.extraction_result_uri:
                logger.info(f"Assessing section {section.section_id}")
                document = self.process_document_section(document, section.section_id)
            else:
                logger.warning(
                    f"Section {section.section_id} has no extraction results to assess"
                )

        logger.info(f"Completed assessment for document {document.id}")
        return document
