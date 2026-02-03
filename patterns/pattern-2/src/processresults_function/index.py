# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import datetime
import json
import logging
import os
from urllib.parse import urlparse

import boto3
from idp_common import s3, utils
from idp_common.config import get_config
from idp_common.docs_service import create_document_service
from idp_common.models import Document, HitlMetadata, Status

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger("idp_common.bedrock.client").setLevel(
    os.environ.get("BEDROCK_LOG_LEVEL", "INFO")
)

# Initialize AWS clients
s3_client = boto3.client("s3")


def is_hitl_enabled():
    """Check if HITL is enabled from configuration."""
    try:
        config = get_config(as_model=True)
        return config.assessment.hitl_enabled
    except Exception as e:
        logger.warning(f"Failed to get HITL config: {e}")
        return False  # Default to disabled if config unavailable


def handle_hitl_wait(event):
    """
    Handle HITL wait action by storing the task token for later workflow continuation.

    Args:
        event: Event containing task token and document information

    Returns:
        Dict confirming HITL wait setup
    """
    task_token = event.get("taskToken")
    document = event.get("document", {})
    # Support document_id, input_key, and object_key for compatibility with compressed/uncompressed formats
    object_key = (
        document.get("document_id")
        or document.get("input_key")
        or document.get("object_key")
    )

    if not task_token or not object_key:
        raise ValueError(
            f"taskToken and document key are required for HITL wait. Got taskToken={bool(task_token)}, document keys={list(document.keys())}"
        )

    logger.info(f"Setting up HITL wait for document {object_key}")

    try:
        # Store the task token directly in DynamoDB
        tracking_table = os.environ.get("TRACKING_TABLE_NAME") or os.environ.get(
            "TRACKING_TABLE"
        )
        if not tracking_table:
            raise ValueError(
                "TRACKING_TABLE_NAME or TRACKING_TABLE environment variable not set"
            )

        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(tracking_table)
        table.update_item(
            Key={"PK": f"doc#{object_key}", "SK": "none"},
            UpdateExpression="SET HITLTaskToken = :token, HITLStatus = :status",
            ExpressionAttributeValues={
                ":token": task_token,
                ":status": "WaitingForReview",
            },
        )

        logger.info(
            f"Task token stored for document {object_key}, workflow will wait for HITL completion"
        )

        # Return immediately - the workflow will wait for send_task_success
        return {
            "HITLWaitSetup": True,
            "ObjectKey": object_key,
            "Message": "Workflow waiting for HITL completion",
        }

    except Exception as e:
        logger.error(f"Failed to store task token for document {object_key}: {str(e)}")
        raise


def handler(event, context):
    """
    Consolidates the results from multiple extraction steps into a single output.
    Also handles HITL wait action to store task token for workflow continuation.

    Args:
        event: Contains the document metadata and extraction results array or HITL wait action
        context: Lambda context

    Returns:
        Dict containing the fully processed document or HITL wait confirmation
    """
    logger.info(f"Processing event: {json.dumps(event)}")

    # Check if this is a HITL wait action
    if event.get("action") == "wait_for_hitl":
        return handle_hitl_wait(event)

    config = get_config(as_model=True)
    # Get the base document from the original classification result - handle both compressed and uncompressed
    working_bucket = os.environ.get("WORKING_BUCKET")
    classification_document_data = event.get("ClassificationResult", {}).get(
        "document", {}
    )
    document = Document.load_document(
        classification_document_data, working_bucket, logger
    )

    extraction_results = event.get("ExtractionResults", [])
    execution_arn = event.get("execution_arn", "")
    execution_id = execution_arn.split(":")[-1] if execution_arn else "unknown"

    # Get confidence threshold from configuration
    confidence_threshold = config.assessment.default_confidence_threshold
    logger.info(f"Using confidence threshold: {confidence_threshold}")

    # Update document status to POSTPROCESSING
    document.status = Status.POSTPROCESSING
    document_service = create_document_service()
    logger.info(f"Updating document status to {document.status}")
    document_service.update_document(document)

    # Clear sections list to rebuild from extraction results
    document.sections = []
    validation_errors = []
    validation_errors = []
    hitl_triggered = False

    # Combine all section results
    for i, result in enumerate(extraction_results):
        # New optimized format - document is at the top level
        document_data = result.get("document", {})
        section_document = Document.load_document(document_data, working_bucket, logger)
        logger.info(f"section_document: {section_document}")
        if section_document:
            # Add section to document if present
            if section_document.sections:
                section = section_document.sections[0]
                logger.info(f"section: {section}")
                logger.info(
                    f"section.confidence_threshold_alerts: {section.confidence_threshold_alerts}"
                )
                hitl_enabled = is_hitl_enabled()
                logger.info(f"is_hitl_enabled: {hitl_enabled}")
                document.sections.append(section)

                # Check if HITL review is needed for this section
                if hitl_enabled and section.confidence_threshold_alerts:
                    logger.info(
                        f"Section {section.section_id} has {len(section.confidence_threshold_alerts)} confidence threshold alerts - marking for HITL review"
                    )
                    hitl_triggered = True

                    # Create HITL metadata entry for in-house portal review
                    section_page_numbers = list(range(1, len(section.page_ids) + 1))
                    hitl_metadata = HitlMetadata(
                        execution_id=execution_id,
                        record_number=int(section.section_id),
                        bp_match=True,
                        extraction_bp_name=section.classification,
                        hitl_triggered=True,
                        page_array=section_page_numbers,
                    )
                    document.hitl_metadata.append(hitl_metadata)

                # Create metadata file for section output
                if section.extraction_result_uri:
                    create_metadata_file(
                        section.extraction_result_uri, section.classification, "section"
                    )

                if section_document.status == Status.FAILED:
                    error_message = (
                        f"Processing failed for section {i + 1}: "
                        f"{'; '.join(section_document.errors)}"
                    )
                    validation_errors.append(error_message)
                    logger.error(f"Error: {error_message}")

            # Add metering from section processing
            document.metering = utils.merge_metering_data(
                document.metering, section_document.metering
            )

    # Create metadata files for pages
    for page_id, page in document.pages.items():
        if page.raw_text_uri:
            create_metadata_file(page.raw_text_uri, page.classification, "page")

    # Collect section IDs that need HITL review
    hitl_sections_pending = []
    if hitl_triggered:
        for section in document.sections:
            if section.confidence_threshold_alerts:
                hitl_sections_pending.append(section.section_id)

    # Update document status based on HITL requirement
    if hitl_triggered:
        # Set status to HITL_IN_PROGRESS when HITL is triggered
        document.status = Status.HITL_IN_PROGRESS
        logger.info(
            f"Document requires human review, setting status to {document.status}"
        )
        logger.info(f"Sections pending HITL review: {hitl_sections_pending}")

    # Update final status in AppSync / Document Service
    logger.info(f"Updating document status to {document.status}")
    document_service.update_document(document)

    # Update HITLSectionsPending in DynamoDB if HITL is triggered
    if hitl_triggered and hitl_sections_pending:
        try:
            tracking_table = os.environ.get("TRACKING_TABLE_NAME")
            if tracking_table:
                dynamodb = boto3.resource("dynamodb")
                table = dynamodb.Table(tracking_table)
                table.update_item(
                    Key={"PK": f"doc#{document.input_key}", "SK": "none"},
                    UpdateExpression="SET HITLSectionsPending = :pending, HITLSectionsCompleted = :completed",
                    ExpressionAttributeValues={
                        ":pending": hitl_sections_pending,
                        ":completed": [],
                    },
                )
                logger.info(
                    f"Updated HITLSectionsPending for document {document.input_key}"
                )
        except Exception as e:
            logger.error(f"Failed to update HITLSectionsPending: {str(e)}")

    # Check if rule validation is enabled in config AND has rules configured
    rule_validation_enabled = False
    if hasattr(config, 'rule_validation'):
        rule_validation_enabled = config.rule_validation.enabled
        # Also check if there are any rules configured
        if rule_validation_enabled and hasattr(config, 'rule_classes'):
            if not config.rule_classes or len(config.rule_classes) == 0:
                logger.info("Rule validation is enabled but no rule_classes configured - skipping rule validation")
                rule_validation_enabled = False
        logger.info(f"Rule validation enabled: {rule_validation_enabled}")
    
    # Return the completed document with compression
    response = {
        "document": document.serialize_document(
            working_bucket, "processresults", logger
        ),
        "hitl_triggered": hitl_triggered,
        "rule_validation_enabled": rule_validation_enabled
    }

    logger.info(f"Response: {json.dumps(response, default=str)}")

    if document.errors:
        validation_errors.extend(document.errors)

    # Raise exception if there were validation errors
    if validation_errors:
        document.status = Status.FAILED
        # Create comprehensive error message
        error_summary = f"Processing failed for {len(validation_errors)} out of {len(extraction_results)} sections"
        combined_errors = "; ".join(validation_errors)
        full_error_message = f"{error_summary}: {combined_errors}"
        logger.error(f"Error: {full_error_message}")
        raise Exception(full_error_message)

    return response


def create_metadata_file(file_uri, class_type, file_type=None):
    """
    Creates a metadata file alongside the given URI file with the same name plus '.metadata.json'
    """
    try:
        # Parse the S3 URI to get bucket and key
        parsed_uri = urlparse(file_uri)
        bucket = parsed_uri.netloc
        key = parsed_uri.path.lstrip("/")

        # Create the metadata key by adding '.metadata.json' to the original key
        metadata_key = f"{key}.metadata.json"

        # Determine the file type if not provided
        if file_type is None:
            if key.endswith(".json"):
                file_type = "section"
            else:
                file_type = "page"

        # Create metadata content
        metadata_content = {
            "metadataAttributes": {
                "DateTime": datetime.datetime.now().isoformat(),
                "Class": class_type,
                "FileType": file_type,
            }
        }

        # Upload metadata file to S3 using common library
        s3.write_content(
            metadata_content, bucket, metadata_key, content_type="application/json"
        )

        logger.info(f"Created metadata file at s3://{bucket}/{metadata_key}")
    except Exception as e:
        logger.error(f"Error creating metadata file for {file_uri}: {str(e)}")
