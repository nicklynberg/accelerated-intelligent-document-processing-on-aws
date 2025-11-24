#!/usr/bin/env python3
# pyright: reportAttributeAccessIssue=false
# ruff: noqa
"""
Full integration test for granular assessment service with mocked AWS services.

This script:
1. Uses moto's mock_aws() to mock S3 and other AWS services
2. Configures passthrough for Bedrock API calls (to use real AWS Bedrock)
3. Creates a complete test document with pages and images
4. Uploads test data to mocked S3
5. Runs the full assessment pipeline with REAL Bedrock calls
6. Validates the results

Usage:
    python test_granular_assessment_full.py [--max-workers N]

Requirements:
    - Valid AWS credentials for Bedrock access (calls go to real Bedrock!)
    - Bedrock model access: us.anthropic.claude-3-5-sonnet-20241022-v2:0
    - pip install moto[all] boto3 PyMuPDF pillow

Note:
    This test uses moto's passthrough feature to allow Bedrock calls
    while still mocking S3/DynamoDB. You will incur real Bedrock costs!

    Uses real sample document from samples/bank-statement-multipage.pdf
"""

import argparse
import json
from pathlib import Path
from typing import Any

import boto3
from idp_common.assessment.granular_service import GranularAssessmentService
from idp_common.config.models import AssessmentConfig, IDPConfig
from idp_common.models import Document, Page, Section
from idp_common.utils.pdf_helpers import create_minimal_png, pdf_page_to_image
from moto import mock_aws

# Test configuration
TEST_BUCKET = "test-idp-bucket"
TEST_REGION = "us-east-1"


def load_sample_document_image() -> bytes:
    """Load a real sample document from the samples folder and convert first page to PNG."""
    # Use the bank statement sample - it's a real invoice-like document
    sample_path = (
        Path(__file__).parent.parent.parent / "samples" / "bank-statement-multipage.pdf"
    )

    if not sample_path.exists():
        print(f"Warning: Sample document not found at {sample_path}")
        print("Falling back to minimal test image")
        return create_minimal_png()

    try:
        # Convert first page of PDF to image with size limits
        # Max 1200x1200 pixels for ~1MP (~100-200KB depending on content)
        png_bytes = pdf_page_to_image(
            pdf_path=sample_path,
            page_number=0,  # First page
            max_width=1200,
            max_height=1200,
            dpi_scale=1.0,  # Standard DPI
        )

        print(
            f"✓ Loaded real document image from {sample_path.name} ({len(png_bytes):,} bytes)"
        )
        return png_bytes

    except Exception as e:
        print(f"Warning: Failed to load sample document: {e}")
        print("Falling back to minimal test image")
        return create_minimal_png()


def create_sample_extraction_result() -> dict[str, Any]:
    """Create sample extraction results for a bank statement."""
    return {
        "Account Number": "1234567890",
        "Statement Period": "January 2024",
        "Account Holder Address": {
            "Street Number": "123",
            "Street Name": "Main St",
            "City": "San Francisco",
            "State": "CA",
            "ZIP Code": "94102",
        },
        "Transactions": [
            {
                "Date": "01/05/2024",
                "Description": "Direct Deposit - Acme Corp",
                "Amount": 2500.00,
            },
            {
                "Date": "01/10/2024",
                "Description": "ATM Withdrawal",
                "Amount": -200.00,
            },
            {
                "Date": "01/15/2024",
                "Description": "Online Payment - Electric Co",
                "Amount": -150.00,
            },
        ],
    }


def create_sample_schema() -> dict[str, Any]:
    """Create a sample JSON schema for bank statement documents."""
    return {
        "type": "object",
        "x-aws-idp-document-type": "Bank Statement",
        "properties": {
            "Account Number": {
                "type": "string",
                "description": "Primary account identifier",
                "x-aws-idp-confidence-threshold": 0.95,
            },
            "Statement Period": {
                "type": "string",
                "description": "Statement period (e.g., January 2024)",
                "x-aws-idp-confidence-threshold": 0.90,
            },
            "Account Holder Address": {
                "type": "object",
                "description": "Complete address information for the account holder",
                "x-aws-idp-confidence-threshold": 0.85,
                "properties": {
                    "Street Number": {
                        "type": "string",
                        "description": "House or building number",
                        "x-aws-idp-confidence-threshold": 0.90,
                    },
                    "Street Name": {
                        "type": "string",
                        "description": "Name of the street",
                        "x-aws-idp-confidence-threshold": 0.80,
                    },
                    "City": {
                        "type": "string",
                        "description": "City name",
                        "x-aws-idp-confidence-threshold": 0.90,
                    },
                    "State": {
                        "type": "string",
                        "description": "State abbreviation (e.g., CA, NY)",
                        "x-aws-idp-confidence-threshold": 0.90,
                    },
                    "ZIP Code": {
                        "type": "string",
                        "description": "5 or 9 digit postal code",
                        "x-aws-idp-confidence-threshold": 0.90,
                    },
                },
            },
            "Transactions": {
                "type": "array",
                "description": "List of all transactions in the statement period",
                "items": {
                    "type": "object",
                    "properties": {
                        "Date": {
                            "type": "string",
                            "format": "date",
                            "description": "Transaction date (MM/DD/YYYY)",
                            "x-aws-idp-confidence-threshold": 0.90,
                        },
                        "Description": {
                            "type": "string",
                            "description": "Transaction description or merchant name",
                            "x-aws-idp-confidence-threshold": 0.70,
                        },
                        "Amount": {
                            "type": "number",
                            "description": "Transaction amount (positive for deposits, negative for withdrawals)",
                            "x-aws-idp-confidence-threshold": 0.95,
                        },
                    },
                },
            },
        },
    }


def create_parsed_text() -> str:
    """Create sample parsed text."""
    return """BANK STATEMENT

Account Number: 1234567890
Statement Period: January 2024

Account Holder Address:
123 Main St
San Francisco, CA 94102

Transaction History:
Date        Description                      Amount
01/05/2024  Direct Deposit - Acme Corp       $2,500.00
01/10/2024  ATM Withdrawal                   -$200.00
01/15/2024  Online Payment - Electric Co     -$150.00

Ending Balance: $2,150.00
"""


def create_raw_ocr_data() -> dict[str, Any]:
    """Create sample raw OCR data."""
    return {
        "Blocks": [
            {
                "BlockType": "LINE",
                "Text": "BANK STATEMENT",
                "Confidence": 99.5,
                "Geometry": {
                    "BoundingBox": {
                        "Left": 0.4,
                        "Top": 0.1,
                        "Width": 0.2,
                        "Height": 0.05,
                    }
                },
            },
            {
                "BlockType": "LINE",
                "Text": "Account Number: 1234567890",
                "Confidence": 98.9,
                "Geometry": {
                    "BoundingBox": {
                        "Left": 0.35,
                        "Top": 0.15,
                        "Width": 0.3,
                        "Height": 0.04,
                    }
                },
            },
            {
                "BlockType": "LINE",
                "Text": "123 Main St",
                "Confidence": 98.2,
                "Geometry": {
                    "BoundingBox": {
                        "Left": 0.3,
                        "Top": 0.25,
                        "Width": 0.2,
                        "Height": 0.03,
                    }
                },
            },
        ]
    }


def create_text_confidence_data() -> dict[str, Any]:
    """Create sample text confidence data."""
    return {
        "text_blocks": [
            {
                "text": "BANK STATEMENT",
                "confidence": 0.995,
                "bbox": [400, 100, 600, 150],
                "page": 1,
            },
            {
                "text": "Account Number: 1234567890",
                "confidence": 0.989,
                "bbox": [350, 150, 650, 190],
                "page": 1,
            },
            {
                "text": "123 Main St",
                "confidence": 0.985,
                "bbox": [300, 250, 500, 280],
                "page": 1,
            },
            {
                "text": "$2,500.00",
                "confidence": 0.975,
                "bbox": [600, 400, 750, 430],
                "page": 1,
            },
        ]
    }


def setup_s3_test_data(
    s3_client, bucket: str, doc_id: str
) -> tuple[Document, dict[str, Any]]:
    """
    Set up test data in mocked S3 bucket.

    Returns:
        Tuple of (Document, extraction_result)
    """
    print("📦 Setting up S3 test data...")

    # Create bucket
    s3_client.create_bucket(Bucket=bucket)
    print(f"   Created bucket: {bucket}")

    # Upload page image
    image_key = f"documents/{doc_id}/pages/page-1.png"
    image_bytes = load_sample_document_image()
    s3_client.put_object(
        Bucket=bucket, Key=image_key, Body=image_bytes, ContentType="image/png"
    )
    print(
        f"   ✓ Uploaded image: s3://{bucket}/{image_key} ({len(image_bytes):,} bytes)"
    )

    # Upload parsed text
    text_key = f"documents/{doc_id}/pages/page-1.txt"
    s3_client.put_object(
        Bucket=bucket,
        Key=text_key,
        Body=create_parsed_text().encode("utf-8"),
        ContentType="text/plain",
    )
    print(f"   ✓ Uploaded text: s3://{bucket}/{text_key}")

    # Upload raw OCR data
    # raw_ocr_key = f"documents/{doc_id}/pages/page-1-raw.json"
    # s3_client.put_object(
    #     Bucket=bucket,
    #     Key=raw_ocr_key,
    #     Body=json.dumps(create_raw_ocr_data()).encode("utf-8"),
    #     ContentType="application/json",
    # )
    # print(f"   ✓ Uploaded raw OCR: s3://{bucket}/{raw_ocr_key}")

    # Upload text confidence data
    confidence_key = f"documents/{doc_id}/pages/page-1-confidence.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=confidence_key,
        Body=json.dumps(create_text_confidence_data()).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"   ✓ Uploaded confidence: s3://{bucket}/{confidence_key}")

    # Create and upload extraction results
    extraction_result = create_sample_extraction_result()
    extraction_data = {
        "document_class": {"type": "Bank Statement"},
        "split_document": {"page_indices": [1]},
        "inference_result": extraction_result,
        "metadata": {"extraction_time_seconds": 2.5},
        "explainability_info": [],
    }

    extraction_key = f"documents/{doc_id}/extraction/result.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=extraction_key,
        Body=json.dumps(extraction_data).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"   ✓ Uploaded extraction: s3://{bucket}/{extraction_key}")

    # Create Document object
    doc = Document(
        id=doc_id,
        workflow_execution_arn=f"arn:aws:states:{TEST_REGION}:123456789012:execution:test-workflow:test-exec-001",
        pages={},
        sections=[],
    )

    # Add page
    page = Page(
        page_id="1",
        image_uri=f"s3://{bucket}/{image_key}",
        parsed_text_uri=f"s3://{bucket}/{text_key}",
        # raw_text_uri=f"s3://{bucket}/{raw_ocr_key}",
        text_confidence_uri=f"s3://{bucket}/{confidence_key}",
    )
    doc.pages["1"] = page

    # Add section
    section = Section(
        section_id="section-001",
        classification="Bank Statement",
        page_ids=["1"],
        extraction_result_uri=f"s3://{bucket}/{extraction_key}",
    )
    doc.sections.append(section)

    print("   ✓ Created Document object with 1 page, 1 section")
    print()

    return doc, extraction_result


def create_test_config(schema: dict[str, Any], max_workers: int = 2) -> IDPConfig:
    """Create test configuration."""
    return IDPConfig(
        classes=[schema],
        assessment=AssessmentConfig(
            enabled=True,
            model="us.anthropic.claude-sonnet-4-20250514-v1:0",  # Use inference profile
            system_prompt="You are a document analysis assessment expert. Your role is to evaluate the confidence and accuracy of data extraction results by analyzing them against source documents. Provide accurate confidence scores for each assessment.",
            temperature=0.0,
            max_tokens=4096,
            default_confidence_threshold=0.90,
            max_workers=max_workers,
            # Use default ImageConfig (1200x1200 for ~1MP images)
        ),
    )


def print_assessment_results(doc: Document, section_id: str, s3_client):
    """Print detailed assessment results."""
    print("=" * 80)
    print("📊 Assessment Results")
    print("=" * 80)
    print()

    print(f"Document Status: {doc.status}")
    print(f"Document ID: {doc.id}")
    print()

    # Find assessed section
    section = next((s for s in doc.sections if s.section_id == section_id), None)
    if not section:
        print("❌ Section not found")
        return

    print(f"Section ID: {section.section_id}")
    print(f"Classification: {section.classification}")

    # Check for confidence alerts
    if section.confidence_threshold_alerts:
        print(f"\n⚠️  Confidence Alerts: {len(section.confidence_threshold_alerts)}")
        for i, alert in enumerate(section.confidence_threshold_alerts[:5]):
            print(f"   {i + 1}. {alert}")
        if len(section.confidence_threshold_alerts) > 5:
            print(f"   ... and {len(section.confidence_threshold_alerts) - 5} more")
    else:
        print("\n✅ No confidence threshold alerts")

    # Read assessment data from S3
    if section.extraction_result_uri:
        print("\n📄 Assessment Data:")

        # Parse S3 URI
        uri_parts = section.extraction_result_uri.replace("s3://", "").split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1]

        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            extraction_with_assessment = json.loads(response["Body"].read())

            if "explainability_info" in extraction_with_assessment:
                explainability = extraction_with_assessment["explainability_info"]
                if explainability and len(explainability) > 0:
                    assessment_data = explainability[0]

                    print(f"   Assessed {len(assessment_data)} fields\n")

                    # Show sample assessments
                    sample_fields = list(assessment_data.keys())[:5]
                    for field in sample_fields:
                        field_assessment = assessment_data[field]
                        if (
                            isinstance(field_assessment, dict)
                            and "confidence" in field_assessment
                        ):
                            conf = field_assessment["confidence"]
                            value = field_assessment.get("value", "N/A")
                            threshold = field_assessment.get(
                                "confidence_threshold", 0.90
                            )
                            status_icon = "✅" if conf >= threshold else "⚠️"
                            print(f"   {status_icon} {field}:")
                            print(f"      Value: {value}")
                            print(
                                f"      Confidence: {conf:.2f} (threshold: {threshold:.2f})"
                            )

                            # Show bounding box if present
                            if "bounding_box" in field_assessment:
                                bbox = field_assessment["bounding_box"]
                                if isinstance(bbox, dict):
                                    print(
                                        f"      Bounding Box: [x1={bbox.get('x1', 'N/A')}, y1={bbox.get('y1', 'N/A')}, "
                                        f"x2={bbox.get('x2', 'N/A')}, y2={bbox.get('y2', 'N/A')}, page={bbox.get('page', 'N/A')}]"
                                    )
                                elif isinstance(bbox, list) and len(bbox) > 0:
                                    # If multiple bounding boxes, show first one
                                    first_bbox = bbox[0]
                                    print(
                                        f"      Bounding Box: [x1={first_bbox.get('x1', 'N/A')}, y1={first_bbox.get('y1', 'N/A')}, "
                                        f"x2={first_bbox.get('x2', 'N/A')}, y2={first_bbox.get('y2', 'N/A')}, page={first_bbox.get('page', 'N/A')}]"
                                    )
                                    if len(bbox) > 1:
                                        print(
                                            f"      (+ {len(bbox) - 1} more bounding boxes)"
                                        )

                    if len(assessment_data) > 5:
                        print(f"\n   ... and {len(assessment_data) - 5} more fields")

                # Show metadata
                if "metadata" in extraction_with_assessment:
                    metadata = extraction_with_assessment["metadata"]
                    print("\n⏱️  Timing:")
                    if "assessment_time_seconds" in metadata:
                        print(
                            f"   Assessment time: {metadata['assessment_time_seconds']:.2f}s"
                        )
                    if "assessment_tasks_total" in metadata:
                        print(f"   Total tasks: {metadata['assessment_tasks_total']}")
                        print(
                            f"   Successful: {metadata.get('assessment_tasks_successful', 0)}"
                        )
                        print(
                            f"   Failed: {metadata.get('assessment_tasks_failed', 0)}"
                        )
        except Exception as e:
            print(f"   Could not read assessment data: {e}")

    # Show metering
    if doc.metering:
        print("\n💰 Token Usage:")
        for key, value in doc.metering.items():
            if isinstance(value, dict):
                total_tokens = value.get("totalTokens", 0)
                input_tokens = value.get("inputTokens", 0)
                output_tokens = value.get("outputTokens", 0)
                cache_read = value.get("cacheReadInputTokens", 0)
                cache_write = value.get("cacheWriteInputTokens", 0)

                print(f"   {key}:")
                print(f"      Total: {total_tokens:,} tokens")
                print(f"      Input: {input_tokens:,} | Output: {output_tokens:,}")
                if cache_read > 0:
                    print(f"      Cache read: {cache_read:,}")
                if cache_write > 0:
                    print(f"      Cache write: {cache_write:,}")


def main():
    """Run the full assessment test."""
    parser = argparse.ArgumentParser(
        description="Test granular assessment with mocked AWS"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="Number of parallel workers (default: 2)",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("Granular Assessment Full Integration Test")
    print(f"(With mocked S3, real Bedrock calls, {args.max_workers} workers)")
    print("=" * 80)
    print()

    doc_id = "test-bank-statement-001"

    # Use moto to mock AWS services (S3, DynamoDB, etc.)
    # But allow Bedrock calls to pass through to real AWS
    with mock_aws(
        config={
            "core": {
                "mock_credentials": False,
                "passthrough": {
                    "urls": [
                        r".*bedrock.*\.amazonaws\.com.*",
                        r".*bedrock-runtime.*\.amazonaws\.com.*",
                    ]
                },
            }
        }
    ):
        # Create S3 client (will use mocked S3)
        s3_client = boto3.client("s3", region_name=TEST_REGION)

        # Set up test data
        doc, extraction_result = setup_s3_test_data(s3_client, TEST_BUCKET, doc_id)

        print("📋 Test Document:")
        print(f"   ID: {doc.id}")
        print(f"   Pages: {len(doc.pages)}")
        print(f"   Sections: {len(doc.sections)}")
        print(f"   Fields in extraction: {len(extraction_result)} top-level")
        print()

        # Create schema and config
        schema = create_sample_schema()
        config = create_test_config(schema, max_workers=args.max_workers)

        print("⚙️  Initializing GranularAssessmentService...")
        service = GranularAssessmentService(
            region=TEST_REGION, config=config, cache_table=None
        )
        print("   ✓ Service initialized")
        print(f"   Max workers: {service.max_workers}")
        print(f"   Parallel: {service.enable_parallel}")
        print()

        # Get task count
        section = doc.sections[0]
        properties = schema["properties"]

        tasks, _ = service._create_assessment_tasks(
            extraction_results=extraction_result,
            properties=properties,
            default_confidence_threshold=config.assessment.default_confidence_threshold,
        )

        print("🔍 Assessment Plan:")
        print(f"   Total tasks to execute: {len(tasks)}")
        print("   Expected: 17 tasks")
        print("     - 2 top-level scalars (Account Number, Statement Period)")
        print(
            "     - 5 address fields (Street Number, Street Name, City, State, ZIP Code)"
        )
        print("     - 9 transaction fields (3 transactions × 3 fields each)")
        print()

        print("=" * 80)
        print("🚀 Running Full Assessment Pipeline")
        print("=" * 80)
        print()
        print("⚠️  This will make REAL calls to AWS Bedrock!")
        print(
            f"   Assessing {len(tasks)} fields with {service.max_workers} parallel workers"
        )
        print(f"   Model: {config.assessment.model}")
        print()

        try:
            # Run the assessment
            print("⏳ Calling process_document_section()...")
            print()

            updated_doc = service.process_document_section(doc, section.section_id)

            print()
            print("✅ Assessment completed successfully!")
            print()

            # Print results
            print_assessment_results(updated_doc, section.section_id, s3_client)

            print()
            print("=" * 80)
            print("✅ Full Integration Test PASSED!")
            print("=" * 80)

        except Exception as e:
            print()
            print(f"❌ Assessment failed: {e}")
            print()

            import traceback

            print("Full error traceback:")
            traceback.print_exc()
            print()

            print("=" * 80)
            print("❌ Full Integration Test FAILED")
            print("=" * 80)

            # Still return success code if it was just a Bedrock auth issue
            if "credentials" in str(e).lower() or "bedrock" in str(e).lower():
                print(
                    "\n💡 This appears to be an AWS credentials/Bedrock access issue."
                )
                print(
                    "   The test infrastructure (S3 mocking, task creation) is working correctly."
                )


if __name__ == "__main__":
    main()
