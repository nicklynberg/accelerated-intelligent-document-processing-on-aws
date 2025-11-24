# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Shared utilities for geometry data conversion.

Consolidates duplicate geometry conversion logic from service.py and granular_service.py.
"""

import os
from typing import Any

from aws_lambda_powertools import Logger

from idp_common.assessment.models import Geometry

logger = Logger(service="assessment", level=os.getenv("LOG_LEVEL", "INFO"))


def process_assessment_geometry(
    attr_assessment: dict[str, Any], attr_name: str = ""
) -> dict[str, Any]:
    """
    Process and standardize geometry data in assessment response.

    Args:
        attr_assessment: Assessment dict with potential bbox/page fields
        attr_name: Field name for logging

    Returns:
        Enhanced assessment with standardized geometry
    """
    enhanced = attr_assessment.copy()

    # Check for bbox data
    if "bbox" in attr_assessment and "page" in attr_assessment:
        try:
            bbox_coords = attr_assessment["bbox"]
            page_num = attr_assessment["page"]

            if isinstance(bbox_coords, list) and len(bbox_coords) == 4:
                # Create Geometry object and convert to UI format
                geometry = Geometry.from_bbox_list(bbox_coords, page_num)
                enhanced["geometry"] = [geometry.to_ui_format()]

                logger.debug(
                    f"Converted bbox for {attr_name}: {bbox_coords} -> geometry"
                )
            else:
                logger.warning(f"Invalid bbox format for {attr_name}: {bbox_coords}")
        except Exception as e:
            logger.warning(f"Failed to process bbox for {attr_name}: {e}")
    elif "bbox" in attr_assessment and "page" not in attr_assessment:
        logger.warning(
            f"Found bbox without page for {attr_name} - removing incomplete bbox data"
        )
    elif "page" in attr_assessment and "bbox" not in attr_assessment:
        logger.warning(
            f"Found page without bbox for {attr_name} - removing incomplete page data"
        )

    # Remove raw bbox/page data
    enhanced.pop("bbox", None)
    enhanced.pop("page", None)

    return enhanced


def extract_geometry_from_nested_dict(
    data: dict[str, Any], path: list[str] | None = None
) -> dict[str, Any]:
    """
    Recursively process geometry data in nested assessment structures.

    Args:
        data: Assessment data dictionary (may contain nested dicts/lists)
        path: Current path for logging

    Returns:
        Enhanced data with processed geometry
    """
    if path is None:
        path = []

    if not isinstance(data, dict):
        return data

    result = {}

    for key, value in data.items():
        current_path = path + [key]

        if isinstance(value, dict):
            # Check if this looks like an assessment entry
            if "confidence" in value or "bbox" in value:
                # Process this assessment
                result[key] = process_assessment_geometry(value, ".".join(current_path))
            else:
                # Recurse into nested dict
                result[key] = extract_geometry_from_nested_dict(value, current_path)

        elif isinstance(value, list):
            # Process each item in list
            processed_list = []
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    processed_list.append(
                        extract_geometry_from_nested_dict(item, current_path + [str(i)])
                    )
                else:
                    processed_list.append(item)
            result[key] = processed_list
        else:
            result[key] = value

    return result
