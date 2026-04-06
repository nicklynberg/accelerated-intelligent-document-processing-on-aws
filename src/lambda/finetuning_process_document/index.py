"""
Lambda function to process a single document for fine-tuning.

This function:
1. Downloads a single document from S3
2. Converts PDF to images (if needed)
3. Creates a training example in Bedrock format
4. Writes the example to S3 as an individual JSONL file

Called by Step Functions Distributed Map for parallel processing.
"""

import base64
import io
import json
import logging
import os
import uuid
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
FINETUNING_BUCKET = os.environ.get("FINETUNING_DATA_BUCKET", "")
TEST_SET_BUCKET = os.environ.get("TEST_SET_BUCKET", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Bedrock fine-tuning limits
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB limit for Bedrock

# Initialize clients
s3_client = boto3.client("s3", region_name=REGION)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for processing a single document."""
    logger.info(f"Received event: {json.dumps(event)}")

    # Extract document info from the event
    # The event comes from the Distributed Map iterator
    job_id = event.get("jobId")
    document = event.get("document", {})
    classes = event.get("classes", [])
    
    filename = document.get("filename")
    input_uri = document.get("inputUri")
    baseline_key = document.get("baselineKey")

    if not job_id:
        raise ValueError("jobId is required")
    if not filename or not input_uri:
        raise ValueError("document with filename and inputUri is required")

    try:
        # Load baseline data
        baseline = _load_baseline(baseline_key)
        if not baseline:
            logger.warning(f"No baseline found for {filename}, skipping")
            return {
                "success": False,
                "filename": filename,
                "reason": "No baseline found"
            }

        # Create training example
        example = _create_training_example(
            input_uri=input_uri,
            baseline=baseline,
            filename=filename,
            classes=classes,
            job_id=job_id
        )

        if not example:
            logger.warning(f"Failed to create training example for {filename}")
            return {
                "success": False,
                "filename": filename,
                "reason": "Failed to create training example"
            }

        # Write individual JSONL file to S3
        example_id = str(uuid.uuid4())
        output_key = f"finetuning/{job_id}/examples/{example_id}.jsonl"
        
        s3_client.put_object(
            Bucket=FINETUNING_BUCKET,
            Key=output_key,
            Body=json.dumps(example).encode("utf-8"),
            ContentType="application/jsonl",
        )

        logger.info(f"Successfully processed {filename} -> {output_key}")

        return {
            "success": True,
            "filename": filename,
            "outputKey": output_key,
            "outputUri": f"s3://{FINETUNING_BUCKET}/{output_key}"
        }

    except Exception as e:
        logger.error(f"Error processing document {filename}: {str(e)}", exc_info=True)
        return {
            "success": False,
            "filename": filename,
            "reason": str(e)
        }


def _load_baseline(baseline_key: str) -> Optional[Dict[str, Any]]:
    """Load baseline JSON from S3."""
    if not baseline_key:
        return None
    
    try:
        response = s3_client.get_object(Bucket=TEST_SET_BUCKET, Key=baseline_key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        logger.warning(f"Error loading baseline {baseline_key}: {e}")
        return None


def _create_training_example(
    input_uri: str,
    baseline: Dict[str, Any],
    filename: str,
    classes: List[str],
    job_id: str
) -> Optional[Dict[str, Any]]:
    """Create a single training example from a document.
    
    For extraction fine-tuning, we create examples that teach the model
    to extract structured data from documents.
    
    Supports both image files and PDFs (PDFs are converted to images).
    
    IMPORTANT: Bedrock fine-tuning requires images to be stored in S3 and
    referenced via s3Location, not embedded as base64 bytes.
    """
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
    # Images are uploaded to S3 and referenced via s3Location (required for fine-tuning)
    try:
        image_s3_uris = _get_document_images_as_s3(input_uri, job_id, filename)
        if not image_s3_uris:
            logger.warning(f"No images extracted from document: {filename}")
            return None
        
        # Add each image/page to the user content with S3 location reference
        for s3_uri, image_format in image_s3_uris:
            user_content.append({
                "image": {
                    "format": image_format,
                    "source": {
                        "s3Location": {
                            "uri": s3_uri
                        }
                    }
                }
            })
        
        logger.info(f"Added {len(image_s3_uris)} image(s) from document: {filename}")
        
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


def _resize_image_to_limit(img_bytes: bytes, img_format: str, max_size: int = MAX_IMAGE_SIZE_BYTES) -> Tuple[bytes, str]:
    """
    Resize an image if it exceeds the maximum size limit.
    
    Uses progressive quality reduction and resolution scaling to fit within limits.
    Converts to JPEG for better compression if needed.
    
    Args:
        img_bytes: Original image bytes
        img_format: Original format (png, jpeg, etc.)
        max_size: Maximum allowed size in bytes (default: 10MB)
        
    Returns:
        Tuple of (resized_bytes, format) - format may change to jpeg for better compression
    """
    if not PIL_SUPPORT:
        logger.warning("PIL not available, cannot resize images")
        return img_bytes, img_format
    
    # If already under limit, return as-is
    if len(img_bytes) <= max_size:
        return img_bytes, img_format
    
    logger.info(f"Image size {len(img_bytes)} exceeds limit {max_size}, resizing...")
    
    # Load image
    img = Image.open(io.BytesIO(img_bytes))
    
    # Convert to RGB if necessary (for JPEG compatibility)
    if img.mode in ('RGBA', 'P', 'LA'):
        # Create white background for transparency
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        if img.mode in ('RGBA', 'LA'):
            background.paste(img, mask=img.split()[-1])  # Use alpha channel as mask
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Try JPEG with decreasing quality first (most effective for size reduction)
    for quality in [85, 70, 55, 40, 30]:
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        result_bytes = buffer.getvalue()
        
        if len(result_bytes) <= max_size:
            logger.info(f"Resized image to {len(result_bytes)} bytes using JPEG quality={quality}")
            return result_bytes, "jpeg"
    
    # If still too large, reduce resolution progressively
    original_size = img.size
    for scale in [0.75, 0.5, 0.35, 0.25]:
        new_size = (int(original_size[0] * scale), int(original_size[1] * scale))
        resized_img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        for quality in [70, 50, 35]:
            buffer = io.BytesIO()
            resized_img.save(buffer, format='JPEG', quality=quality, optimize=True)
            result_bytes = buffer.getvalue()
            
            if len(result_bytes) <= max_size:
                logger.info(f"Resized image to {len(result_bytes)} bytes using scale={scale}, quality={quality}")
                return result_bytes, "jpeg"
    
    # Last resort: aggressive downscaling
    final_scale = 0.15
    new_size = (int(original_size[0] * final_scale), int(original_size[1] * final_scale))
    resized_img = img.resize(new_size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized_img.save(buffer, format='JPEG', quality=30, optimize=True)
    result_bytes = buffer.getvalue()
    
    logger.warning(f"Aggressively resized image to {len(result_bytes)} bytes (scale={final_scale})")
    return result_bytes, "jpeg"


def _get_document_images_as_s3(s3_uri: str, job_id: str, filename: str) -> List[Tuple[str, str]]:
    """
    Download document from S3, convert to images if needed, upload images to S3,
    and return list of S3 URIs.
    
    For PDFs, converts each page to an image.
    For images, copies the image to the finetuning bucket.
    
    IMPORTANT: Bedrock fine-tuning requires images to be referenced via S3 URIs,
    not embedded as base64 bytes. Images are automatically resized if they exceed
    the 10MB limit.
    
    Args:
        s3_uri: S3 URI of the source document
        job_id: Fine-tuning job ID for organizing output
        filename: Original filename for naming the output images
        
    Returns:
        List of tuples (s3_uri, format) for each image/page
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
    
    # Generate base name for output images (remove extension)
    base_name = os.path.splitext(os.path.basename(filename))[0]
    # Sanitize filename for S3 key
    base_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in base_name)
    
    result = []
    
    # Handle PDFs - convert to images and upload each page
    if lower_uri.endswith(".pdf"):
        if not PDF_SUPPORT or not PIL_SUPPORT:
            logger.warning(f"PDF support not available, skipping: {s3_uri}")
            return []
        
        images = _convert_pdf_to_images(doc_bytes)
        for page_idx, (img_bytes, img_format) in enumerate(images):
            # Resize if needed to meet Bedrock's 10MB limit
            img_bytes, img_format = _resize_image_to_limit(img_bytes, img_format)
            
            # Upload each page as a separate image
            image_key = f"finetuning/{job_id}/images/{base_name}_page{page_idx + 1}.{img_format}"
            s3_client.put_object(
                Bucket=FINETUNING_BUCKET,
                Key=image_key,
                Body=img_bytes,
                ContentType=f"image/{img_format}",
            )
            image_s3_uri = f"s3://{FINETUNING_BUCKET}/{image_key}"
            result.append((image_s3_uri, img_format))
            logger.debug(f"Uploaded PDF page {page_idx + 1} to {image_s3_uri}")
        
        return result
    
    # Handle images - copy to finetuning bucket
    if lower_uri.endswith(".jpg") or lower_uri.endswith(".jpeg"):
        img_format = "jpeg"
    elif lower_uri.endswith(".png"):
        img_format = "png"
    elif lower_uri.endswith(".gif"):
        img_format = "gif"
    elif lower_uri.endswith(".webp"):
        img_format = "webp"
    else:
        # Default to PNG
        img_format = "png"
    
    # Resize if needed to meet Bedrock's 10MB limit
    doc_bytes, img_format = _resize_image_to_limit(doc_bytes, img_format)
    
    # Upload the image to the finetuning bucket
    image_key = f"finetuning/{job_id}/images/{base_name}.{img_format}"
    s3_client.put_object(
        Bucket=FINETUNING_BUCKET,
        Key=image_key,
        Body=doc_bytes,
        ContentType=f"image/{img_format}",
    )
    image_s3_uri = f"s3://{FINETUNING_BUCKET}/{image_key}"
    result.append((image_s3_uri, img_format))
    logger.debug(f"Uploaded image to {image_s3_uri}")
    
    return result


def _get_document_images(s3_uri: str) -> List[Tuple[str, str]]:
    """
    Download document from S3 and return list of base64 encoded images.
    
    DEPRECATED: Use _get_document_images_as_s3 instead for fine-tuning,
    as Bedrock requires S3 URIs, not base64 bytes.
    
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