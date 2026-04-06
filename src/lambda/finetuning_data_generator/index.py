"""
Lambda function to generate training data for fine-tuning from a Test Set.

This function:
1. Reads documents and baselines from a Test Set
2. Converts them to Bedrock JSONL format for multi-image classification
3. Splits into training and validation sets
4. Uploads to S3

Called by Step Functions as part of the fine-tuning workflow.
"""

import base64
import io
import json
import logging
import os
import random
from typing import Any, Dict, List, Optional, Tuple

import boto3

# Try to import PDF conversion libraries
try:
    import pypdfium2 as pdfium
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    pdfium = None

try:
    from PIL import Image
    PIL_SUPPORT = True
except ImportError:
    PIL_SUPPORT = False
    Image = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
TRACKING_TABLE_NAME = os.environ.get("TRACKING_TABLE", "")
FINETUNING_BUCKET = os.environ.get("FINETUNING_DATA_BUCKET", "")
TEST_SET_BUCKET = os.environ.get("TEST_SET_BUCKET", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Initialize clients
dynamodb = boto3.resource("dynamodb", region_name=REGION)
s3_client = boto3.client("s3", region_name=REGION)

# DynamoDB key prefixes
FINETUNING_JOB_PREFIX = "finetuning#"

# System prompt for classification
CLASSIFICATION_SYSTEM_PROMPT = """You are a document classification expert. Analyze the provided document images and classify each page into one of the following categories: {classes}.

For each page, identify the document type based on its visual content, layout, and text. Return your classification as a JSON object."""


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for generating training data."""
    logger.info(f"Received event: {json.dumps(event)}")

    job_id = event.get("jobId")
    test_set_id = event.get("testSetId")
    train_split = event.get("trainSplit", 0.9)

    if not job_id:
        raise ValueError("jobId is required")
    if not test_set_id:
        raise ValueError("testSetId is required")

    try:
        # Update job status to GENERATING_DATA
        _update_job_status(job_id, "GENERATING_DATA")

        # Get test set documents and baselines
        documents = _get_test_set_documents(test_set_id)
        logger.info(f"Found {len(documents)} documents in test set {test_set_id}")

        if not documents:
            raise ValueError(f"No documents found in test set {test_set_id}")

        # Get all unique classes from baselines
        all_classes = _get_all_classes(documents)
        logger.info(f"Found {len(all_classes)} unique classes: {all_classes}")

        # Convert documents to training examples
        training_examples = _convert_to_training_examples(documents, all_classes)
        logger.info(f"Generated {len(training_examples)} training examples")

        # Shuffle and split into train/validation
        random.seed(42)  # For reproducibility
        random.shuffle(training_examples)

        split_idx = int(len(training_examples) * train_split)
        train_examples = training_examples[:split_idx]
        validation_examples = training_examples[split_idx:]

        logger.info(
            f"Split into {len(train_examples)} training and {len(validation_examples)} validation examples"
        )

        # Upload to S3
        training_data_uri = _upload_jsonl(
            train_examples, job_id, "train.jsonl"
        )
        validation_data_uri = _upload_jsonl(
            validation_examples, job_id, "validation.jsonl"
        )

        # Update job with data URIs
        _update_job_data_uris(job_id, training_data_uri, validation_data_uri)

        return {
            "jobId": job_id,
            "trainingDataUri": training_data_uri,
            "validationDataUri": validation_data_uri,
            "trainCount": len(train_examples),
            "validationCount": len(validation_examples),
            "classes": all_classes,
        }

    except Exception as e:
        logger.error(f"Error generating training data: {str(e)}", exc_info=True)
        _update_job_status(job_id, "FAILED", str(e))
        raise


def _get_test_set_documents(test_set_id: str) -> List[Dict[str, Any]]:
    """Get all documents from a test set with their baselines from S3.
    
    Test sets are stored in S3 with structure:
    - {test_set_id}/input/{filename} - input document files
    - {test_set_id}/baseline/{filename}/ - baseline folder for each document
    """
    bucket = TEST_SET_BUCKET
    if not bucket:
        raise ValueError("TEST_SET_BUCKET environment variable not set")
    
    documents = []
    
    # List all input files
    input_files = []
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{test_set_id}/input/"):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if not key.endswith('/'):  # Skip directories
                filename = key.split('/')[-1]
                input_files.append({
                    'filename': filename,
                    'input_key': key,
                    'input_uri': f"s3://{bucket}/{key}"
                })
    
    logger.info(f"Found {len(input_files)} input files in test set {test_set_id}")
    
    # For each input file, get its baseline
    for input_file in input_files:
        filename = input_file['filename']
        baseline_prefix = f"{test_set_id}/baseline/{filename}/"
        
        # Get baseline JSON file
        baseline_data = None
        try:
            # Look for extraction.json or similar baseline file
            baseline_response = s3_client.list_objects_v2(
                Bucket=bucket,
                Prefix=baseline_prefix
            )
            
            for obj in baseline_response.get('Contents', []):
                key = obj['Key']
                if key.endswith('.json'):
                    # Read the baseline JSON
                    response = s3_client.get_object(Bucket=bucket, Key=key)
                    baseline_data = json.loads(response['Body'].read().decode('utf-8'))
                    break
        except Exception as e:
            logger.warning(f"Failed to get baseline for {filename}: {e}")
            continue
        
        if baseline_data:
            doc = {
                'filename': filename,
                'input_uri': input_file['input_uri'],
                'baseline': baseline_data
            }
            documents.append(doc)
    
    return documents


def _get_all_classes(documents: List[Dict[str, Any]]) -> List[str]:
    """Extract all unique classes from document baselines."""
    classes = set()
    for doc in documents:
        baseline = doc.get("baseline", {})
        # Try different baseline formats
        # Format 1: baseline has 'Sections' with 'DocumentClass'
        sections = baseline.get("Sections", [])
        for section in sections:
            doc_class = section.get("DocumentClass")
            if doc_class:
                classes.add(doc_class)
        # Format 2: baseline has 'documentClass' at top level
        doc_class = baseline.get("documentClass") or baseline.get("DocumentClass")
        if doc_class:
            classes.add(doc_class)
    
    # If no classes found, use a default
    if not classes:
        classes.add("document")
    
    return sorted(list(classes))


def _convert_to_training_examples(
    documents: List[Dict[str, Any]], all_classes: List[str]
) -> List[Dict[str, Any]]:
    """Convert test set documents to Bedrock training format."""
    examples = []

    for doc in documents:
        try:
            example = _create_training_example(doc, all_classes)
            if example:
                examples.append(example)
        except Exception as e:
            logger.warning(f"Failed to convert document {doc.get('filename')}: {e}")
            continue

    return examples


def _create_training_example(
    doc: Dict[str, Any], all_classes: List[str]
) -> Optional[Dict[str, Any]]:
    """Create a single training example from a document.
    
    For extraction fine-tuning, we create examples that teach the model
    to extract structured data from documents.
    
    Supports both image files and PDFs (PDFs are converted to images).
    """
    input_uri = doc.get("input_uri")
    baseline = doc.get("baseline", {})
    filename = doc.get("filename", "")
    
    if not input_uri or not baseline:
        return None

    # Build the conversation format for Bedrock fine-tuning
    # Create user message with document image(s)
    user_content = []

    # Add instruction text based on what's in the baseline
    extraction_fields = _get_extraction_fields(baseline)
    if extraction_fields:
        fields_str = ", ".join(extraction_fields[:20])  # Limit to 20 fields
        user_content.append({
            "text": f"Extract the following information from this document: {fields_str}. Return the results as a JSON object."
        })
    else:
        user_content.append({
            "text": "Extract all relevant information from this document. Return the results as a JSON object."
        })

    # Add document image(s) - supports PDFs by converting to images
    try:
        images = _get_document_images(input_uri)
        if not images:
            logger.warning(f"No images extracted from document: {filename}")
            return None
        
        # Add each image/page to the user content
        for image_data, image_format in images:
            user_content.append({
                "image": {
                    "format": image_format,
                    "source": {
                        "bytes": image_data
                    }
                }
            })
        
        logger.info(f"Added {len(images)} image(s) from document: {filename}")
        
    except Exception as e:
        logger.warning(f"Failed to load document {input_uri}: {e}")
        return None

    if len(user_content) < 2:  # Need at least text + 1 image
        return None

    # Build expected response from baseline extraction results
    extraction_result = _format_baseline_for_training(baseline)
    assistant_response = json.dumps(extraction_result, indent=2)

    # Create the training example in Bedrock conversation format
    example = {
        "schemaVersion": "bedrock-conversation-2024",
        "system": [
            {
                "text": "You are a document extraction expert. Analyze the provided document and extract the requested information accurately. Return your results as a well-structured JSON object."
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": user_content
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "text": assistant_response
                    }
                ]
            }
        ]
    }

    return example


def _get_extraction_fields(baseline: Dict[str, Any]) -> List[str]:
    """Extract field names from baseline data."""
    fields = []
    
    # Try different baseline formats
    # Format 1: Sections with Extraction
    sections = baseline.get("Sections", [])
    for section in sections:
        extraction = section.get("Extraction", {})
        fields.extend(extraction.keys())
    
    # Format 2: Direct extraction at top level
    extraction = baseline.get("Extraction", {})
    fields.extend(extraction.keys())
    
    # Format 3: Fields array
    for field in baseline.get("fields", []):
        if isinstance(field, dict):
            fields.append(field.get("name", ""))
        elif isinstance(field, str):
            fields.append(field)
    
    return [f for f in fields if f]  # Filter empty strings


def _format_baseline_for_training(baseline: Dict[str, Any]) -> Dict[str, Any]:
    """Format baseline data as the expected extraction output."""
    result = {}
    
    # Try different baseline formats
    # Format 1: Sections with Extraction
    sections = baseline.get("Sections", [])
    for section in sections:
        extraction = section.get("Extraction", {})
        for key, value in extraction.items():
            # Handle different value formats
            if isinstance(value, dict):
                result[key] = value.get("value", value.get("Value", str(value)))
            else:
                result[key] = value
    
    # Format 2: Direct extraction at top level
    extraction = baseline.get("Extraction", {})
    for key, value in extraction.items():
        if isinstance(value, dict):
            result[key] = value.get("value", value.get("Value", str(value)))
        else:
            result[key] = value
    
    # Format 3: Fields array with values
    for field in baseline.get("fields", []):
        if isinstance(field, dict):
            name = field.get("name", "")
            value = field.get("value", "")
            if name:
                result[name] = value
    
    # If still empty, just return the baseline as-is (cleaned up)
    if not result:
        # Remove metadata fields
        for key, value in baseline.items():
            if key not in ["Sections", "metadata", "Metadata", "pageCount", "PageCount"]:
                result[key] = value
    
    return result


def _convert_pdf_to_images(pdf_bytes: bytes, max_pages: int = 10, dpi: int = 150) -> List[Tuple[bytes, str]]:
    """
    Convert PDF bytes to a list of PNG images.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        max_pages: Maximum number of pages to convert (to limit training data size)
        dpi: Resolution for rendering (higher = better quality but larger files)
        
    Returns:
        List of tuples (image_bytes, format) for each page
    """
    if not PDF_SUPPORT:
        logger.warning("pypdfium2 not available, cannot convert PDFs")
        return []
    
    if not PIL_SUPPORT:
        logger.warning("Pillow not available, cannot convert PDFs")
        return []
    
    images = []
    try:
        # Load PDF from bytes
        pdf = pdfium.PdfDocument(pdf_bytes)
        num_pages = min(len(pdf), max_pages)
        
        logger.info(f"Converting PDF with {len(pdf)} pages (processing {num_pages})")
        
        for page_idx in range(num_pages):
            page = pdf[page_idx]
            
            # Render page to bitmap
            # Scale factor: 1 = 72 DPI, so for 150 DPI we use 150/72 ≈ 2.08
            scale = dpi / 72.0
            bitmap = page.render(scale=scale)
            
            # Convert to PIL Image
            pil_image = bitmap.to_pil()
            
            # Convert to PNG bytes
            img_buffer = io.BytesIO()
            pil_image.save(img_buffer, format="PNG", optimize=True)
            img_bytes = img_buffer.getvalue()
            
            images.append((img_bytes, "png"))
            
        pdf.close()
        
    except Exception as e:
        logger.error(f"Error converting PDF to images: {e}", exc_info=True)
        return []
    
    return images


def _get_document_images(s3_uri: str) -> List[Tuple[str, str]]:
    """
    Download document from S3 and return list of base64 encoded images.
    
    For PDFs, converts each page to an image.
    For images, returns the image directly.
    
    Args:
        s3_uri: S3 URI of the document
        
    Returns:
        List of tuples (base64_data, format) for each image/page
    """
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")

    # Parse S3 URI
    path = s3_uri[5:]
    parts = path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""

    # Download document
    response = s3_client.get_object(Bucket=bucket, Key=key)
    doc_bytes = response["Body"].read()
    
    lower_uri = s3_uri.lower()
    
    # Handle PDFs
    if lower_uri.endswith(".pdf"):
        if not PDF_SUPPORT or not PIL_SUPPORT:
            logger.warning(f"PDF support not available, skipping: {s3_uri}")
            return []
        
        images = _convert_pdf_to_images(doc_bytes)
        return [(base64.b64encode(img_bytes).decode("utf-8"), fmt) for img_bytes, fmt in images]
    
    # Handle images
    if lower_uri.endswith(".jpg") or lower_uri.endswith(".jpeg"):
        return [(base64.b64encode(doc_bytes).decode("utf-8"), "jpeg")]
    elif lower_uri.endswith(".png"):
        return [(base64.b64encode(doc_bytes).decode("utf-8"), "png")]
    elif lower_uri.endswith(".gif"):
        return [(base64.b64encode(doc_bytes).decode("utf-8"), "gif")]
    elif lower_uri.endswith(".webp"):
        return [(base64.b64encode(doc_bytes).decode("utf-8"), "webp")]
    else:
        # Try to treat as image
        return [(base64.b64encode(doc_bytes).decode("utf-8"), "png")]


def _get_image_base64(s3_uri: str) -> str:
    """Download image from S3 and return base64 encoded string.
    
    DEPRECATED: Use _get_document_images instead for PDF support.
    """
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")

    # Parse S3 URI
    path = s3_uri[5:]
    parts = path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""

    # Download image
    response = s3_client.get_object(Bucket=bucket, Key=key)
    image_bytes = response["Body"].read()

    # Return base64 encoded
    return base64.b64encode(image_bytes).decode("utf-8")


def _upload_jsonl(
    examples: List[Dict[str, Any]], job_id: str, filename: str
) -> str:
    """Upload training examples as JSONL to S3."""
    # Convert to JSONL format
    jsonl_content = "\n".join(json.dumps(ex) for ex in examples)

    # Upload to S3
    key = f"finetuning/{job_id}/{filename}"
    s3_client.put_object(
        Bucket=FINETUNING_BUCKET,
        Key=key,
        Body=jsonl_content.encode("utf-8"),
        ContentType="application/jsonl",
    )

    s3_uri = f"s3://{FINETUNING_BUCKET}/{key}"
    logger.info(f"Uploaded {len(examples)} examples to {s3_uri}")

    return s3_uri


def _update_job_status(
    job_id: str, status: str, error_message: str = None
) -> None:
    """Update fine-tuning job status in DynamoDB."""
    table = dynamodb.Table(TRACKING_TABLE_NAME)

    update_expression = "SET #status = :status"
    expression_values = {":status": status}
    expression_names = {"#status": "status"}

    if error_message:
        update_expression += ", errorMessage = :err, errorStep = :step"
        expression_values[":err"] = error_message
        expression_values[":step"] = "GENERATING_DATA"

    table.update_item(
        Key={"PK": f"{FINETUNING_JOB_PREFIX}{job_id}", "SK": "metadata"},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values,
    )


def _update_job_data_uris(
    job_id: str, training_data_uri: str, validation_data_uri: str
) -> None:
    """Update job with training data URIs."""
    table = dynamodb.Table(TRACKING_TABLE_NAME)

    table.update_item(
        Key={"PK": f"{FINETUNING_JOB_PREFIX}{job_id}", "SK": "metadata"},
        UpdateExpression="SET trainingDataUri = :train, validationDataUri = :val",
        ExpressionAttributeValues={
            ":train": training_data_uri,
            ":val": validation_data_uri,
        },
    )