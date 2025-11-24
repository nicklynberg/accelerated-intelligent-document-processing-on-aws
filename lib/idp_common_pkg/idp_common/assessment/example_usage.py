#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Example usage of the Strands-Based Assessment Service.

This script demonstrates how to use the Strands-based assessment approach
for improved accuracy and scalability when assessing document extraction confidence.
All assessment now uses this unified approach with tool-based agent interactions.
"""

import json
import logging
from typing import Any, Dict

import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def example_granular_assessment():
    """Example of using Strands-based assessment service."""

    # Load configuration for assessment (always uses Strands-based approach)
    config = {
        "assessment": {
            "enabled": True,
            "default_confidence_threshold": 0.9,
            "model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "system_prompt": "You are a document analysis assessment expert...",
            "task_prompt": """
            <background>
            You are an expert document analysis assessment system...
            </background>
            
            <<CACHEPOINT>>
            
            <extraction-results>
            {EXTRACTION_RESULTS}
            </extraction-results>
            
            <final-instructions>
            Analyze and provide confidence assessments...
            </final-instructions>
            """,
            # Strands-based assessment settings
            "max_workers": 20,
        },
        "classes": [
            {
                "name": "Bank Statement",
                "attributes": [
                    {
                        "name": "Account Number",
                        "attributeType": "simple",
                        "confidence_threshold": 0.95,
                    },
                    {
                        "name": "Statement Period",
                        "attributeType": "simple",
                        "confidence_threshold": 0.85,
                    },
                    {
                        "name": "Account Holder Address",
                        "attributeType": "group",
                        "groupAttributes": [
                            {"name": "Street Number", "confidence_threshold": 0.95},
                            {"name": "Street Name", "confidence_threshold": 0.85},
                            {"name": "City", "confidence_threshold": 0.9},
                            {"name": "State", "confidence_threshold": 0.95},
                            {"name": "ZIP Code", "confidence_threshold": 0.95},
                        ],
                    },
                    {
                        "name": "Transactions",
                        "attributeType": "list",
                        "listItemTemplate": {
                            "itemAttributes": [
                                {"name": "Date", "confidence_threshold": 0.9},
                                {"name": "Description", "confidence_threshold": 0.75},
                                {"name": "Amount", "confidence_threshold": 0.95},
                            ]
                        },
                    },
                ],
            }
        ],
    }

    # Import the assessment module
    from idp_common.assessment import create_assessment_service

    # Create assessment service using factory function
    assessment_service = create_assessment_service(region="us-west-2", config=config)

    logger.info(f"Created assessment service: {type(assessment_service).__name__}")

    # Example extraction results that would be assessed
    example_extraction_results = {
        "Account Number": "123456789",
        "Statement Period": "January 2024",
        "Account Holder Address": {
            "Street Number": "123",
            "Street Name": "Main Street",
            "City": "Anytown",
            "State": "CA",
            "ZIP Code": "12345",
        },
        "Transactions": [
            {
                "Date": "01/15/2024",
                "Description": "GROCERY STORE PURCHASE",
                "Amount": "-45.67",
            },
            {
                "Date": "01/16/2024",
                "Description": "SALARY DEPOSIT",
                "Amount": "2500.00",
            },
            {
                "Date": "01/17/2024",
                "Description": "UTILITY PAYMENT",
                "Amount": "-125.30",
            },
        ],
    }

    logger.info("Example extraction results:")
    logger.info(json.dumps(example_extraction_results, indent=2))

    # Demonstrate task creation (this would normally be done internally)
    if hasattr(assessment_service, "_create_assessment_tasks"):
        class_schema = assessment_service._get_class_schema("Bank Statement")
        properties = class_schema.get("properties", {})
        tasks, assessment_structure = assessment_service._create_assessment_tasks(
            example_extraction_results, properties, 0.9
        )

        logger.info(f"\nCreated {len(tasks)} assessment tasks:")
        for task in tasks:
            logger.info(f"  - {task.task_id}: {task.task_type} for {task.field_name}")

    return assessment_service, config


def compare_approaches():
    """Demonstrate the Strands-based assessment approach."""

    logger.info("=== Strands-Based Assessment Approach ===")

    # Configuration for Strands-based assessment (always used)
    assessment_config = {
        "assessment": {
            "enabled": True,
            "max_workers": 4,
        }
    }

    from idp_common.assessment import create_assessment_service

    # Create assessment service
    assessment_service = create_assessment_service(config=assessment_config)

    logger.info(f"Assessment service: {type(assessment_service).__name__}")

    # Show the features
    logger.info("\nStrands-Based Assessment Features:")
    logger.info("  - Multiple focused inferences per field")
    logger.info("  - Tool-based interaction with Strands agents")
    logger.info("  - Prompt caching for cost optimization")
    logger.info("  - Parallel processing for speed")
    logger.info("  - Better handling of complex documents")
    logger.info("  - Consistent assessment structure")


def demonstrate_configuration_options():
    """Demonstrate different configuration options for Strands-based assessment."""

    logger.info("=== Configuration Options ===")

    # Conservative configuration (good for starting)
    conservative_config = {
        "assessment": {
            "enabled": True,
            "max_workers": 2,
        }
    }

    # Aggressive configuration (for high-throughput)
    aggressive_config = {
        "assessment": {
            "enabled": True,
            "max_workers": 50,
        }
    }

    # Balanced configuration (recommended)
    balanced_config = {
        "assessment": {
            "enabled": True,
            "max_workers": 20,
        }
    }

    configs = {
        "Conservative": conservative_config,
        "Aggressive": aggressive_config,
        "Balanced": balanced_config,
    }

    for name, config in configs.items():
        logger.info(f"\n{name} Configuration:")
        assessment_settings = config["assessment"]
        for key, value in assessment_settings.items():
            logger.info(f"  {key}: {value}")


def main():
    """Main example function."""

    logger.info("=== Strands-Based Assessment Service Examples ===")

    try:
        # Example 1: Basic usage
        logger.info("\n1. Basic Usage Example")
        service, config = example_granular_assessment()

        # Example 2: Demonstrate the approach
        logger.info("\n2. Assessment Approach")
        compare_approaches()

        # Example 3: Configuration options
        logger.info("\n3. Configuration Options")
        demonstrate_configuration_options()

        logger.info("\n=== Examples Complete ===")
        logger.info("To use Strands-based assessment in your application:")
        logger.info("1. Set assessment.enabled to true in your config")
        logger.info("2. Configure max_workers based on your throughput needs")
        logger.info("3. Use create_assessment_service() factory function")
        logger.info("4. Process documents with the same interface")
        logger.info("5. Monitor performance and tune max_workers parameter")

    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure idp_common package is installed and available")
    except Exception as e:
        logger.error(f"Error running examples: {e}")
        raise


if __name__ == "__main__":
    main()
