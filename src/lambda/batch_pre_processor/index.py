# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Batch Pre-Processor Lambda

Extracts ZIP files from staging bucket and uploads individual files
to the input bucket for processing. Updates job record with file list.
"""

import logging
import os
import tempfile
import zipfile

import boto3

from idp_common.job_service import create_job_service
from idp_common.models import Status

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")

INPUT_BUCKET = os.environ.get("INPUT_BUCKET_NAME", "")
TRACKING_TABLE = os.environ.get("TRACKING_TABLE", "")

job_service = create_job_service()


def handler(event, context):
    """Process EventBridge events for uploaded ZIP files."""
    logger.info(f"Processing event: {event}")

    # EventBridge event format
    bucket = event["detail"]["bucket"]["name"]
    key = event["detail"]["object"]["key"]

    # Expected key format: jobs/{uuid}/{filename}.zip
    if not key.endswith(".zip"):
        logger.warning(f"Skipping non-ZIP file: {key}")
        return {"statusCode": 200}

    # Extract job_id (uuid) from key
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "jobs":
        logger.warning(f"Unexpected key format: {key}")
        return {"statusCode": 200}

    job_id = parts[1]  # uuid
    logger.info(f"Processing ZIP for job: {job_id}")

    try:
        # Extract and upload files
        files = extract_and_upload(bucket, key, job_id)

        # Update job record with file list
        if job_service and files:
            file_status = {f: Status.IN_PROGRESS for f in files}
            job_service.update_job_files(job_id, file_status)
            logger.info(f"Updated job {job_id} with {len(files)} files")

    except Exception as e:
        logger.error(f"Error processing {key}: {e}", exc_info=True)
        raise

    return {"statusCode": 200}


def extract_and_upload(staging_bucket: str, zip_key: str, job_id: str) -> list[str]:
    """
    Extract ZIP and upload files to input bucket.

    Returns:
        List of uploaded filenames
    """
    uploaded_files = []
    seen_names = {}

    with tempfile.NamedTemporaryFile() as temp_file:
        s3.download_fileobj(staging_bucket, zip_key, temp_file)
        temp_file.seek(0)

        with zipfile.ZipFile(temp_file, "r") as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.is_dir():
                    continue

                basename = os.path.basename(file_info.filename)
                if not basename:
                    continue

                # Handle filename collisions
                if basename in seen_names:
                    seen_names[basename] += 1
                    name, ext = os.path.splitext(basename)
                    filename = f"{name}_{seen_names[basename]}{ext}"
                else:
                    seen_names[basename] = 0
                    filename = basename

                dest_key = f"jobs/{job_id}/{filename}"
                file_content = zip_ref.read(file_info.filename)

                s3.put_object(
                    Bucket=INPUT_BUCKET,
                    Key=dest_key,
                    Body=file_content,
                )
                logger.info(f"Uploaded {filename} to {dest_key}")
                uploaded_files.append(filename)

    return uploaded_files
