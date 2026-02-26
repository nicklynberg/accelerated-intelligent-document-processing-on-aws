# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for batch metadata and confidence retrieval"""

import inspect

import pytest


@pytest.mark.unit
def test_batch_operation_has_get_metadata_method():
    """Verify BatchOperation has get_metadata method"""
    from idp_sdk.operations.batch import BatchOperation

    assert hasattr(BatchOperation, "get_metadata")
    assert callable(getattr(BatchOperation, "get_metadata"))


@pytest.mark.unit
def test_batch_operation_has_get_confidence_method():
    """Verify BatchOperation has get_confidence method"""
    from idp_sdk.operations.batch import BatchOperation

    assert hasattr(BatchOperation, "get_confidence")
    assert callable(getattr(BatchOperation, "get_confidence"))


@pytest.mark.unit
def test_get_metadata_method_signature():
    """Verify get_metadata has correct parameters"""
    from idp_sdk.operations.batch import BatchOperation

    sig = inspect.signature(BatchOperation.get_metadata)
    params = list(sig.parameters.keys())

    assert "batch_id" in params
    assert "section_id" in params
    assert "limit" in params
    assert "next_token" in params
    assert "stack_name" in params


@pytest.mark.unit
def test_get_confidence_method_signature():
    """Verify get_confidence has correct parameters"""
    from idp_sdk.operations.batch import BatchOperation

    sig = inspect.signature(BatchOperation.get_confidence)
    params = list(sig.parameters.keys())

    assert "batch_id" in params
    assert "section_id" in params
    assert "limit" in params
    assert "next_token" in params
    assert "stack_name" in params
