# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the _aggregate_assessment_results function in GranularAssessmentService.
Tests the aggregation logic with real-world data to ensure assessment data is properly
inserted into the assessment structure.
"""

import pytest
from idp_common.assessment.granular_service import GranularAssessmentService
from idp_common.assessment.models import AssessmentResult, AssessmentTask


@pytest.mark.unit
class TestAggregateAssessmentResults:
    """Tests for _aggregate_assessment_results function."""

    def test_aggregate_simple_fields(self):
        """Test aggregation with simple top-level fields using real data."""
        # Create service instance
        service = GranularAssessmentService()

        # Create initial assessment structure (mimics what _create_assessment_tasks returns)
        assessment_structure = {
            "Account Number": None,
            "Statement Period": None,
        }

        # Create tasks using field_path (no parent references needed)
        tasks = [
            AssessmentTask(
                task_id="task_0",
                task_type="attribute",
                field_path=("Account Number",),
                field_name="Account Number",
                field_schema={"type": "string"},
                confidence_threshold=0.95,
            ),
            AssessmentTask(
                task_id="task_1",
                task_type="attribute",
                field_path=("Statement Period",),
                field_name="Statement Period",
                field_schema={"type": "string"},
                confidence_threshold=0.9,
            ),
        ]

        # Create results with simplified data structure (flat assessment dict, not wrapped by field name)
        results = [
            AssessmentResult(
                task_id="task_0",
                success=True,
                assessment_data={
                    "confidence": 0.0,
                    "value": "1234567890",
                    "reasoning": "The extracted value '1234567890' is completely incorrect.",
                    "confidence_threshold": 0.95,
                    "geometry": [
                        {
                            "boundingBox": {
                                "top": 0.458,
                                "left": 0.215,
                                "width": 0.07,
                                "height": 0.014,
                            },
                            "page": 1,
                        }
                    ],
                },
                confidence_alerts=[
                    {
                        "attribute_name": "Account Number",
                        "confidence": 0.0,
                        "confidence_threshold": 0.95,
                    }
                ],
                error_message=None,
                processing_time=195.07,
                metering={
                    "assessment/bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0": {
                        "inputTokens": 17457,
                        "outputTokens": 1320,
                    }
                },
            ),
            AssessmentResult(
                task_id="task_1",
                success=True,
                assessment_data={
                    "confidence": 0.0,
                    "value": "January 2024",
                    "reasoning": "The extracted value 'January 2024' is completely incorrect.",
                    "confidence_threshold": 0.9,
                    "geometry": [
                        {
                            "boundingBox": {
                                "top": 0.27,
                                "left": 0.058,
                                "width": 0.092,
                                "height": 0.015,
                            },
                            "page": 1,
                        }
                    ],
                },
                confidence_alerts=[
                    {
                        "attribute_name": "Statement Period",
                        "confidence": 0.0,
                        "confidence_threshold": 0.9,
                    }
                ],
                error_message=None,
                processing_time=148.42,
                metering={
                    "assessment/bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0": {
                        "inputTokens": 14097,
                        "outputTokens": 1104,
                    }
                },
            ),
        ]

        # Call the function under test
        (
            aggregated_structure,
            alerts,
            metering,
        ) = service._aggregate_assessment_results(tasks, results, assessment_structure)

        # Assertions
        assert aggregated_structure is not None
        assert "Account Number" in aggregated_structure
        assert "Statement Period" in aggregated_structure

        # Check Account Number was properly inserted (not None!)
        assert aggregated_structure["Account Number"] is not None
        assert aggregated_structure["Account Number"]["confidence"] == 0.0
        assert aggregated_structure["Account Number"]["value"] == "1234567890"
        assert "reasoning" in aggregated_structure["Account Number"]
        assert "geometry" in aggregated_structure["Account Number"]

        # Check Statement Period was properly inserted
        assert aggregated_structure["Statement Period"] is not None
        assert aggregated_structure["Statement Period"]["confidence"] == 0.0
        assert aggregated_structure["Statement Period"]["value"] == "January 2024"

        # Check alerts
        assert len(alerts) == 2

        # Check metering
        assert metering is not None
        assert (
            "assessment/bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0" in metering
        )

    def test_aggregate_nested_fields(self):
        """Test aggregation with nested object fields using real data."""
        service = GranularAssessmentService()

        # Create nested assessment structure
        nested_address = {
            "Street Number": None,
            "Street Name": None,
            "City": None,
        }
        assessment_structure = {"Account Holder Address": nested_address}

        # Create tasks using field_path for navigation
        tasks = [
            AssessmentTask(
                task_id="task_0",
                task_type="attribute",
                field_path=("Account Holder Address", "Street Number"),
                field_name="Street Number",
                field_schema={"type": "string"},
                confidence_threshold=0.85,
            ),
            AssessmentTask(
                task_id="task_1",
                task_type="attribute",
                field_path=("Account Holder Address", "Street Name"),
                field_name="Street Name",
                field_schema={"type": "string"},
                confidence_threshold=0.85,
            ),
            AssessmentTask(
                task_id="task_2",
                task_type="attribute",
                field_path=("Account Holder Address", "City"),
                field_name="City",
                field_schema={"type": "string"},
                confidence_threshold=0.85,
            ),
        ]

        # Create results with flat assessment data (not wrapped by field name)
        results = [
            AssessmentResult(
                task_id="task_0",
                success=True,
                assessment_data={
                    "confidence": 0.0,
                    "value": "123",
                    "reasoning": "The extracted value '123' is completely incorrect.",
                    "confidence_threshold": 0.85,
                    "geometry": [
                        {
                            "boundingBox": {
                                "top": 0.17,
                                "left": 0.114,
                                "width": 0.021,
                                "height": 0.012,
                            },
                            "page": 1,
                        }
                    ],
                },
                confidence_alerts=[],
                error_message=None,
                processing_time=216.45,
            ),
            AssessmentResult(
                task_id="task_1",
                success=True,
                assessment_data={
                    "confidence": 0.0,
                    "value": "Main St",
                    "reasoning": "The extracted value 'Main St' is completely incorrect.",
                    "confidence_threshold": 0.85,
                    "geometry": [
                        {
                            "boundingBox": {
                                "top": 0.17,
                                "left": 0.13,
                                "width": 0.09,
                                "height": 0.02,
                            },
                            "page": 1,
                        }
                    ],
                },
                confidence_alerts=[],
                error_message=None,
                processing_time=217.03,
            ),
            AssessmentResult(
                task_id="task_2",
                success=True,
                assessment_data={
                    "confidence": 0.1,
                    "value": "San Francisco",
                    "reasoning": "The extracted value 'San Francisco' does not match.",
                    "confidence_threshold": 0.85,
                    "geometry": [
                        {
                            "boundingBox": {
                                "top": 0.17,
                                "left": 0.2,
                                "width": 0.09,
                                "height": 0.015,
                            },
                            "page": 1,
                        }
                    ],
                },
                confidence_alerts=[],
                error_message=None,
                processing_time=217.32,
            ),
        ]

        # Call the function under test
        (
            aggregated_structure,
            alerts,
            metering,
        ) = service._aggregate_assessment_results(tasks, results, assessment_structure)

        # Assertions - check nested structure
        assert "Account Holder Address" in aggregated_structure
        nested = aggregated_structure["Account Holder Address"]

        # CRITICAL: These should NOT be None!
        assert nested["Street Number"] is not None
        assert nested["Street Number"]["confidence"] == 0.0
        assert nested["Street Number"]["value"] == "123"

        assert nested["Street Name"] is not None
        assert nested["Street Name"]["confidence"] == 0.0
        assert nested["Street Name"]["value"] == "Main St"

        assert nested["City"] is not None
        assert nested["City"]["confidence"] == 0.1
        assert nested["City"]["value"] == "San Francisco"

    def test_aggregate_array_fields(self):
        """Test aggregation with array fields using real data."""
        service = GranularAssessmentService()

        # Create array structure - each array item is a dict
        transaction_0 = {"Date": None, "Amount": None}
        transaction_1 = {"Date": None, "Amount": None}
        transactions_array = [transaction_0, transaction_1]
        assessment_structure = {"Transactions": transactions_array}

        # Create tasks using field_path for navigation
        tasks = [
            AssessmentTask(
                task_id="task_0",
                task_type="attribute",
                field_path=("Transactions", 0, "Date"),
                field_name="Date",
                field_schema={"type": "string"},
                confidence_threshold=0.9,
            ),
            AssessmentTask(
                task_id="task_1",
                task_type="attribute",
                field_path=("Transactions", 0, "Amount"),
                field_name="Amount",
                field_schema={"type": "number"},
                confidence_threshold=0.9,
            ),
            AssessmentTask(
                task_id="task_2",
                task_type="attribute",
                field_path=("Transactions", 1, "Date"),
                field_name="Date",
                field_schema={"type": "string"},
                confidence_threshold=0.9,
            ),
            AssessmentTask(
                task_id="task_3",
                task_type="attribute",
                field_path=("Transactions", 1, "Amount"),
                field_name="Amount",
                field_schema={"type": "number"},
                confidence_threshold=0.9,
            ),
        ]

        # Create results with flat assessment data (not wrapped by field name)
        results = [
            AssessmentResult(
                task_id="task_0",
                success=True,
                assessment_data={
                    "confidence": 0.2,
                    "value": "01/05/2024",
                    "reasoning": "Date mismatch",
                    "confidence_threshold": 0.9,
                    "geometry": [],
                },
                confidence_alerts=[],
                error_message=None,
                processing_time=230.94,
            ),
            AssessmentResult(
                task_id="task_1",
                success=True,
                assessment_data={
                    "confidence": 0.1,
                    "value": 2500.0,
                    "reasoning": "Cannot verify amount",
                    "confidence_threshold": 0.9,
                },
                confidence_alerts=[],
                error_message=None,
                processing_time=216.57,
            ),
            AssessmentResult(
                task_id="task_2",
                success=True,
                assessment_data={
                    "confidence": 0.0,
                    "value": "01/10/2024",
                    "reasoning": "Completely fabricated",
                    "confidence_threshold": 0.9,
                },
                confidence_alerts=[],
                error_message=None,
                processing_time=207.28,
            ),
            AssessmentResult(
                task_id="task_3",
                success=True,
                assessment_data={
                    "confidence": 0.1,
                    "value": -200.0,
                    "reasoning": "Cannot verify",
                    "confidence_threshold": 0.9,
                },
                confidence_alerts=[],
                error_message=None,
                processing_time=225.86,
            ),
        ]

        # Call the function under test
        (
            aggregated_structure,
            alerts,
            metering,
        ) = service._aggregate_assessment_results(tasks, results, assessment_structure)

        # Assertions - check array structure
        assert "Transactions" in aggregated_structure
        transactions = aggregated_structure["Transactions"]
        assert len(transactions) == 2

        # Check first transaction
        assert transactions[0]["Date"] is not None
        assert transactions[0]["Date"]["confidence"] == 0.2
        assert transactions[0]["Date"]["value"] == "01/05/2024"

        assert transactions[0]["Amount"] is not None
        assert transactions[0]["Amount"]["confidence"] == 0.1
        assert transactions[0]["Amount"]["value"] == 2500.0

        # Check second transaction
        assert transactions[1]["Date"] is not None
        assert transactions[1]["Date"]["confidence"] == 0.0
        assert transactions[1]["Date"]["value"] == "01/10/2024"

        assert transactions[1]["Amount"] is not None
        assert transactions[1]["Amount"]["confidence"] == 0.1
        assert transactions[1]["Amount"]["value"] == -200.0
