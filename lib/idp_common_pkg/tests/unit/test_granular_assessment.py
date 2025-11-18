# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the granular assessment service.
"""

import pytest
from idp_common.assessment.granular_service import (
    AssessmentResult,
    AssessmentTask,
    GranularAssessmentService,
    _safe_float_conversion,
)
from idp_common.config.models import IDPConfig


class TestSafeFloatConversion:
    """Test the _safe_float_conversion utility function."""

    def test_none_value(self):
        assert _safe_float_conversion(None) == 0.0
        assert _safe_float_conversion(None, 5.0) == 5.0

    def test_numeric_values(self):
        assert _safe_float_conversion(42) == 42.0
        assert _safe_float_conversion(3.14) == 3.14
        assert _safe_float_conversion("123.45") == 123.45

    def test_empty_string(self):
        assert _safe_float_conversion("") == 0.0
        assert _safe_float_conversion("   ") == 0.0

    def test_invalid_string(self):
        assert _safe_float_conversion("invalid") == 0.0
        assert _safe_float_conversion("invalid", 10.0) == 10.0


class TestGranularAssessmentService:
    """Test the GranularAssessmentService class."""

    @pytest.fixture
    def sample_config(self):
        """Sample configuration for testing."""
        return {
            "assessment": {
                "max_workers": 4,
                "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "top_p": 0.1,
                "max_tokens": 4096,
                "system_prompt": "You are an assessment expert.",
                "default_confidence_threshold": 0.9,
            },
            "classes": [
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "letter",
                    "x-aws-idp-document-type": "letter",
                    "type": "object",
                    "description": "A formal letter document",
                    "properties": {
                        "sender_name": {
                            "type": "string",
                            "description": "Name of the sender",
                        },
                        "recipient_name": {
                            "type": "string",
                            "description": "Name of the recipient",
                        },
                        "date": {
                            "type": "string",
                            "description": "Date of the letter",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Subject of the letter",
                        },
                        "signature": {
                            "type": "string",
                            "description": "Signature of the sender",
                        },
                    },
                }
            ],
        }

    @pytest.fixture
    def sample_extraction_results(self):
        """Sample extraction results for testing."""
        return {
            "sender_name": "Will E. Clark",
            "recipient_name": "The Honorable Wendell H. Ford",
            "date": "October 11, 1995",
            "subject": "Opposition to the 'Commitment to Our Children' petition",
            "signature": "Will E. Clark",
        }

    def test_initialization(self, sample_config):
        """Test service initialization."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        assert service.max_workers == 4
        assert service.enable_parallel  # max_workers > 1

    def test_initialization_single_worker(self, sample_config):
        """Test service initialization with single worker."""
        sample_config["assessment"]["max_workers"] = 1
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        assert service.max_workers == 1
        assert not service.enable_parallel  # max_workers = 1

    def test_get_class_schema(self, sample_config):
        """Test getting schema for a document class."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        schema = service._get_class_schema("letter")

        assert schema.get("x-aws-idp-document-type") == "letter"
        assert "properties" in schema
        assert len(schema["properties"]) == 5
        assert "sender_name" in schema["properties"]
        assert "recipient_name" in schema["properties"]

    def test_get_class_schema_not_found(self, sample_config):
        """Test getting schema for a non-existent class."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        schema = service._get_class_schema("nonexistent")

        assert schema == {}

    def test_create_assessment_tasks_simple_attributes(
        self, sample_config, sample_extraction_results
    ):
        """Test creating assessment tasks with simple attributes - new Strands approach."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        tasks, assessment_structure = service._create_assessment_tasks(
            sample_extraction_results, properties, 0.9
        )

        # With new approach: one task per leaf field = 5 tasks
        assert len(tasks) == 5

        # All tasks should be "attribute" type (single field assessment)
        assert all(t.task_type == "attribute" for t in tasks)

        # All tasks should have field_path as tuple
        assert all(isinstance(t.field_path, tuple) for t in tasks)

        # All tasks should have parent_assessment_dict reference
        assert all(t.parent_assessment_dict is not None for t in tasks)

        # Check that assessment_structure mirrors extraction_results
        assert isinstance(assessment_structure, dict)
        assert set(assessment_structure.keys()) == set(sample_extraction_results.keys())

    def test_create_assessment_tasks_with_nested_object(self, sample_config):
        """Test creating assessment tasks with nested object attributes."""
        # Add a nested object property to the config
        sample_config["classes"][0]["properties"]["address_info"] = {
            "type": "object",
            "description": "Address information",
            "properties": {
                "street": {"type": "string", "description": "Street address"},
                "city": {"type": "string", "description": "City name"},
            },
        }

        extraction_results = {
            "sender_name": "John Doe",
            "address_info": {"street": "123 Main St", "city": "Anytown"},
        }

        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        tasks, assessment_structure = service._create_assessment_tasks(
            extraction_results, properties, 0.9
        )

        # Should have 3 tasks: sender_name, address_info.street, address_info.city
        assert len(tasks) == 3

        # Find nested tasks
        nested_tasks = [t for t in tasks if len(t.field_path) > 1]
        assert len(nested_tasks) == 2

        # Check nested paths are tuples
        assert any(t.field_path == ("address_info", "street") for t in nested_tasks)
        assert any(t.field_path == ("address_info", "city") for t in nested_tasks)

        # Check assessment structure has nested dict
        assert "address_info" in assessment_structure
        assert isinstance(assessment_structure["address_info"], dict)

    def test_create_assessment_tasks_with_array(self, sample_config):
        """Test creating assessment tasks with array attributes."""
        # Add an array property to the config
        sample_config["classes"][0]["properties"]["transactions"] = {
            "type": "array",
            "description": "List of transactions",
            "items": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string", "description": "Transaction amount"},
                    "description": {
                        "type": "string",
                        "description": "Transaction description",
                    },
                },
            },
        }

        extraction_results = {
            "sender_name": "John Doe",
            "transactions": [
                {"amount": "100.00", "description": "Payment 1"},
                {"amount": "200.00", "description": "Payment 2"},
            ],
        }

        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        tasks, assessment_structure = service._create_assessment_tasks(
            extraction_results, properties, 0.9
        )

        # Should have 5 tasks: sender_name + 2 items * 2 fields each = 1 + 4 = 5
        assert len(tasks) == 5

        # Find array item tasks
        array_tasks = [
            t for t in tasks if len(t.field_path) == 3
        ]  # ("transactions", 0, "amount")
        assert len(array_tasks) == 4

        # Check array paths include indices
        assert any(t.field_path == ("transactions", 0, "amount") for t in array_tasks)
        assert any(
            t.field_path == ("transactions", 1, "description") for t in array_tasks
        )

        # Check assessment structure has array
        assert "transactions" in assessment_structure
        assert isinstance(assessment_structure["transactions"], list)
        assert len(assessment_structure["transactions"]) == 2

    def test_aggregate_assessment_results_new_approach(self, sample_config):
        """Test aggregating assessment results with new Strands approach."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        # Create pre-built assessment structure
        assessment_structure = {
            "sender_name": None,
            "recipient_name": None,
            "date": None,
        }

        # Create tasks with new structure
        task1 = AssessmentTask(
            task_id="task_0",
            task_type="attribute",
            field_path=("sender_name",),
            field_name="sender_name",
            field_schema={"type": "string"},
            confidence_threshold=0.9,
            parent_assessment_dict=assessment_structure,
        )

        task2 = AssessmentTask(
            task_id="task_1",
            task_type="attribute",
            field_path=("recipient_name",),
            field_name="recipient_name",
            field_schema={"type": "string"},
            confidence_threshold=0.9,
            parent_assessment_dict=assessment_structure,
        )

        task3 = AssessmentTask(
            task_id="task_2",
            task_type="attribute",
            field_path=("date",),
            field_name="date",
            field_schema={"type": "string"},
            confidence_threshold=0.9,
            parent_assessment_dict=assessment_structure,
        )

        # Create results
        result1 = AssessmentResult(
            task_id="task_0",
            success=True,
            assessment_data={"confidence": 0.95, "confidence_reason": "Clear"},
            confidence_alerts=[],
            metering={"model": {"input_tokens": 100}},
        )

        result2 = AssessmentResult(
            task_id="task_1",
            success=True,
            assessment_data={"confidence": 0.85, "confidence_reason": "Good"},
            confidence_alerts=[],
            metering={"model": {"input_tokens": 50}},
        )

        result3 = AssessmentResult(
            task_id="task_2",
            success=True,
            assessment_data={"confidence": 0.90, "confidence_reason": "Clear date"},
            confidence_alerts=[],
            metering={"model": {"input_tokens": 25}},
        )

        # Aggregate results using new signature
        enhanced_data, alerts, metering = service._aggregate_assessment_results(
            [task1, task2, task3], [result1, result2, result3], assessment_structure
        )

        # Check enhanced data (should be the assessment_structure with values filled in)
        assert "sender_name" in enhanced_data
        assert "recipient_name" in enhanced_data
        assert "date" in enhanced_data
        assert enhanced_data["sender_name"]["confidence_threshold"] == 0.9
        assert enhanced_data["sender_name"]["confidence"] == 0.95

        # Check metering aggregation
        assert metering["model"]["input_tokens"] == 175  # 100 + 50 + 25

    def test_empty_extraction_results_handling(self, sample_config):
        """Test handling of empty extraction results."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        # Empty extraction results should create no tasks
        tasks, assessment_structure = service._create_assessment_tasks(
            {}, properties, 0.9
        )
        assert len(tasks) == 0
        assert assessment_structure == {}

    def test_confidence_threshold_inheritance(self, sample_config):
        """Test that confidence thresholds are properly inherited."""
        # Add property-specific threshold
        sample_config["classes"][0]["properties"]["sender_name"][
            "x-aws-idp-confidence-threshold"
        ] = 0.95

        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        # Test getting threshold for property with specific threshold
        threshold = service._get_confidence_threshold_by_path(
            properties, "sender_name", 0.9
        )
        assert threshold == 0.95

        # Test getting threshold for property without specific threshold
        threshold = service._get_confidence_threshold_by_path(
            properties, "recipient_name", 0.9
        )
        assert threshold == 0.9


if __name__ == "__main__":
    pytest.main([__file__])
