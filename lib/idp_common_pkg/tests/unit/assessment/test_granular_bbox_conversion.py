# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Test to verify that the geometry_utils module correctly handles
bounding box conversion for assessment data.
"""

from idp_common.assessment.geometry_utils import extract_geometry_from_nested_dict


def test_both_services_convert_bbox_to_geometry():
    """Test that geometry_utils converts bbox to geometry correctly."""

    # Test data with bbox coordinates
    mock_assessment_data = {
        "YTDNetPay": {
            "confidence": 1.0,
            "confidence_reason": "Clear text with high OCR confidence",
            "bbox": [443, 333, 507, 345],
            "page": 1,
        },
        "CompanyAddress": {
            "State": {
                "confidence": 0.99,
                "confidence_reason": "Clear text",
                "bbox": [230, 116, 259, 126],
                "page": 1,
            },
            "ZipCode": {
                "confidence": 0.99,
                "confidence_reason": "Clear text",
                "bbox": [261, 116, 298, 126],
                "page": 1,
            },
        },
    }

    print("=== Testing Bounding Box Conversion in geometry_utils ===")

    # Test geometry conversion using geometry_utils
    print("\n📝 Testing extract_geometry_from_nested_dict")
    result = extract_geometry_from_nested_dict(mock_assessment_data)

    # Check YTDNetPay conversion
    ytd = result["YTDNetPay"]
    ytd_has_geometry = "geometry" in ytd
    ytd_has_bbox = "bbox" in ytd

    print(f"YTDNetPay: geometry={ytd_has_geometry}, bbox={ytd_has_bbox}")

    # Check CompanyAddress.State conversion
    state = result["CompanyAddress"]["State"]
    state_has_geometry = "geometry" in state
    state_has_bbox = "bbox" in state

    print(f"CompanyAddress.State: geometry={state_has_geometry}, bbox={state_has_bbox}")

    # Verify conversion
    print("\n🔍 Verification:")

    # Should convert bbox to geometry
    assert ytd_has_geometry, "Should convert YTDNetPay bbox to geometry"
    assert not ytd_has_bbox, "Should remove YTDNetPay bbox after conversion"

    # Should handle nested attributes
    assert state_has_geometry, "Should convert nested State bbox to geometry"
    assert not state_has_bbox, "Should remove nested State bbox after conversion"

    # Check geometry values are correct
    ytd_geometry = ytd["geometry"][0]["boundingBox"]
    assert ytd_geometry["top"] == 0.333  # 333/1000
    assert ytd_geometry["left"] == 0.443  # 443/1000
    assert ytd_geometry["width"] == 0.064  # (507-443)/1000
    assert ytd_geometry["height"] == 0.012  # (345-333)/1000

    state_geometry = state["geometry"][0]["boundingBox"]
    assert state_geometry["top"] == 0.116  # 116/1000
    assert state_geometry["left"] == 0.23  # 230/1000
    assert state_geometry["width"] == 0.029  # (259-230)/1000
    assert state_geometry["height"] == 0.01  # (126-116)/1000

    print("✅ Converts bbox → geometry correctly")
    print("✅ Handles nested attributes (CompanyAddress.State)")
    print("✅ Removes raw bbox data after conversion")
    print("✅ Produces correct normalized geometry values")

    print("\n🎉 geometry_utils correctly supports automatic bounding box conversion!")

    return True


if __name__ == "__main__":
    test_both_services_convert_bbox_to_geometry()
