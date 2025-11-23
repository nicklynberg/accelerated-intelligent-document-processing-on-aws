# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Assessment module for document extraction confidence evaluation.

This module provides services for assessing the confidence and accuracy of
extraction results by analyzing them against source documents using LLMs.

All assessment now uses the granular approach with Strands agents for
multiple focused inferences with caching and parallelization.
"""

import logging
from typing import Optional

from idp_common.config.models import IDPConfig

from .granular_service import GranularAssessmentService
from .models import AssessmentResult, AttributeAssessment

logger = logging.getLogger(__name__)


class AssessmentService:
    """
    Assessment service for evaluating document extraction confidence.

    This class uses the granular Strands-based assessment approach for all assessments.
    It provides backward compatibility by maintaining the same interface.
    """

    def __init__(self, region: str | None = None, config: IDPConfig | None = None):
        """
        Initialize the assessment service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary or IDPConfig model
        """
        if config is None:
            config = IDPConfig()
        elif isinstance(config, dict):
            config = IDPConfig(**config)

        self._service = GranularAssessmentService(region=region, config=config)

    def process_document_section(self, document, section_id: str):
        """Process a single section from a Document object to assess extraction confidence."""
        return self._service.process_document_section(document, section_id)

    def assess_document(self, document):
        """Assess extraction confidence for all sections in a document."""
        return self._service.assess_document(document)


def create_assessment_service(
    region: Optional[str] = None, config: Optional[IDPConfig] = None
):
    """
    Factory function to create the assessment service.

    Args:
        region: AWS region for Bedrock
        config: Configuration dictionary or IDPConfig model

    Returns:
        GranularAssessmentService instance
    """
    if not config:
        config = IDPConfig()

    logger.info("Creating GranularAssessmentService (Strands-based assessment)")
    return GranularAssessmentService(region=region, config=config)


__all__ = [
    "AssessmentService",
    "GranularAssessmentService",
    "AssessmentResult",
    "AttributeAssessment",
    "create_assessment_service",
]
