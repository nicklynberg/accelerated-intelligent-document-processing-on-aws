#!/usr/bin/env python3
"""
Test script for grid overlay functionality.

This script demonstrates how to:
1. Add ruler edges to a document image
2. Draw bounding boxes with normalized coordinates
3. Combine both features for LLM-assisted spatial localization

Usage:
    python scripts/test_grid_overlay.py [image_path] [output_dir]

Examples:
    # Use sample California license
    python scripts/test_grid_overlay.py samples/old_cal_license.png

    # Use a PDF (first page will be converted)
    python scripts/test_grid_overlay.py samples/lending_package.pdf

    # Specify output directory
    python scripts/test_grid_overlay.py samples/old_cal_license.png /tmp/grid_test
"""

import sys
import os
from pathlib import Path

# Add the library to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "idp_common_pkg"))

from idp_common.utils.grid_overlay import (
    add_ruler_edges,
    draw_bounding_boxes,
    add_ruler_and_draw_boxes,
)


def convert_pdf_to_image(pdf_path: str) -> bytes:
    """Convert first page of PDF to image bytes."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        page = doc.load_page(0)  # First page

        # Render at 150 DPI for good quality
        pix = page.get_pixmap(dpi=150)  # pyright: ignore[reportAttributeAccessIssue]
        return pix.tobytes("jpeg")
    except ImportError:
        print("ERROR: PyMuPDF (fitz) is required for PDF conversion.")
        print("Install it with: pip install PyMuPDF")
        sys.exit(1)


def load_image(image_path: str) -> bytes:
    """Load image from file path."""
    ext = Path(image_path).suffix.lower()

    if ext == ".pdf":
        print(f"Converting PDF first page to image...")
        return convert_pdf_to_image(image_path)
    else:
        with open(image_path, "rb") as f:
            return f.read()


def main():
    # Default paths
    default_image = "samples/old_cal_license.png"
    default_output_dir = "output/grid_overlay_test"

    # Parse arguments
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        image_path = default_image

    if len(sys.argv) > 2:
        output_dir = sys.argv[2]
    else:
        output_dir = default_output_dir

    # Resolve paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    if not os.path.isabs(image_path):
        image_path = str(project_root / image_path)

    if not os.path.isabs(output_dir):
        output_dir = str(project_root / output_dir)

    # Check if input exists
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found: {image_path}")
        print(f"Available samples in {project_root / 'samples'}:")
        for f in (project_root / "samples").iterdir():
            if f.is_file():
                print(f"  - {f.name}")
        sys.exit(1)

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    print(f"Input image: {image_path}")
    print(f"Output directory: {output_dir}")
    print()

    # Load the image
    print("Loading image...")
    image_data = load_image(image_path)
    print(f"Image size: {len(image_data)} bytes")
    print()

    # ========================================
    # Test 1: Add ruler edges only
    # ========================================
    print("Test 1: Adding ruler edges...")
    ruler_image = add_ruler_edges(
        image_data,
        ruler_width=30,
        tick_interval=50,
        label_interval=100,
    )

    output_path_1 = os.path.join(output_dir, "01_ruler_edges.jpg")
    with open(output_path_1, "wb") as f:
        f.write(ruler_image)
    print(f"  Saved: {output_path_1}")
    print()

    # ========================================
    # Test 2: Draw bounding boxes on original
    # ========================================
    print("Test 2: Drawing bounding boxes on original image...")

    # Example bounding boxes (adjust these based on your image)
    # These are in normalized 0-1000 scale
    sample_bboxes = [
        {
            "bbox": [50, 100, 400, 180],
            "label": "Header Area",
            "color": "red",
        },
        {
            "bbox": [100, 300, 600, 380],
            "label": "Name Field",
            "color": "green",
        },
        {
            "bbox": [100, 450, 500, 530],
            "label": "Address",
            "color": "blue",
        },
        {
            "bbox": [600, 500, 900, 600],
            "label": "Photo Area",
            "color": "orange",
        },
    ]

    bbox_image = draw_bounding_boxes(
        image_data,
        sample_bboxes,
        has_ruler=False,
        box_color="red",
        box_width=3,
    )

    output_path_2 = os.path.join(output_dir, "02_bounding_boxes.jpg")
    with open(output_path_2, "wb") as f:
        f.write(bbox_image)
    print(f"  Saved: {output_path_2}")
    print(f"  Bounding boxes drawn:")
    for bbox in sample_bboxes:
        print(f"    - {bbox['label']}: {bbox['bbox']}")
    print()

    # ========================================
    # Test 3: Ruler + Bounding boxes combined
    # ========================================
    print("Test 3: Combining ruler edges and bounding boxes...")

    combined_image = add_ruler_and_draw_boxes(
        image_data,
        sample_bboxes,
        ruler_width=30,
        tick_interval=50,
        label_interval=100,
        box_color="red",
        box_width=3,
    )

    output_path_3 = os.path.join(output_dir, "03_ruler_with_boxes.jpg")
    with open(output_path_3, "wb") as f:
        f.write(combined_image)
    print(f"  Saved: {output_path_3}")
    print()

    # ========================================
    # Test 4: Fine-grained grid (25 unit ticks)
    # ========================================
    print("Test 4: Fine-grained ruler (25 unit minor ticks)...")
    fine_ruler = add_ruler_edges(
        image_data,
        ruler_width=35,
        tick_interval=25,  # Finer ticks
        label_interval=100,
        font_size=9,
    )

    output_path_4 = os.path.join(output_dir, "04_fine_ruler.jpg")
    with open(output_path_4, "wb") as f:
        f.write(fine_ruler)
    print(f"  Saved: {output_path_4}")
    print()

    # ========================================
    # Test 5: Different box colors
    # ========================================
    print("Test 5: Multi-colored bounding boxes...")

    multi_color_bboxes = [
        {"bbox": [50, 50, 200, 150], "label": "Red", "color": "red"},
        {"bbox": [250, 50, 400, 150], "label": "Green", "color": "green"},
        {"bbox": [450, 50, 600, 150], "label": "Blue", "color": "blue"},
        {"bbox": [50, 200, 200, 300], "label": "Yellow", "color": "yellow"},
        {"bbox": [250, 200, 400, 300], "label": "Orange", "color": "orange"},
        {"bbox": [450, 200, 600, 300], "label": "Purple", "color": "purple"},
    ]

    multi_color_image = draw_bounding_boxes(
        image_data,
        multi_color_bboxes,
        has_ruler=False,
    )

    output_path_5 = os.path.join(output_dir, "05_multi_color_boxes.jpg")
    with open(output_path_5, "wb") as f:
        f.write(multi_color_image)
    print(f"  Saved: {output_path_5}")
    print()

    # ========================================
    # Summary
    # ========================================
    print("=" * 60)
    print("Grid Overlay Test Complete!")
    print("=" * 60)
    print()
    print("Generated files:")
    for i, path in enumerate(
        [output_path_1, output_path_2, output_path_3, output_path_4, output_path_5], 1
    ):
        print(f"  {i}. {path}")
    print()
    print("Next steps:")
    print("  1. Open the generated images to see the grid overlays")
    print("  2. Note how the ruler edges provide coordinate references")
    print("  3. Observe how bounding boxes are labeled with their coordinates")
    print()
    print("To use in assessment:")
    print("  - Add ruler edges to document images before sending to LLM")
    print("  - Update prompt to instruct LLM to read coordinates from ruler")
    print("  - LLM can now provide precise [x1, y1, x2, y2] coordinates")
    print()

    # Interactive demo: Let user test their own coordinates
    print("=" * 60)
    print("Interactive Bounding Box Test")
    print("=" * 60)
    print("You can test drawing custom bounding boxes.")
    print("Enter coordinates in format: x1,y1,x2,y2 (0-1000 scale)")
    print("Example: 100,200,400,250")
    print("Type 'quit' to exit")
    print()

    custom_bboxes = []
    while True:
        try:
            user_input = input("Enter bbox coordinates (or 'quit'): ").strip()
            if user_input.lower() == "quit":
                break

            coords = [int(x.strip()) for x in user_input.split(",")]
            if len(coords) != 4:
                print("  Invalid format. Use: x1,y1,x2,y2")
                continue

            label = input("  Label for this box (press Enter for default): ").strip()
            if not label:
                label = f"Box {len(custom_bboxes) + 1}"

            custom_bboxes.append(
                {
                    "bbox": coords,
                    "label": label,
                    "color": ["red", "green", "blue", "orange", "purple"][
                        len(custom_bboxes) % 5
                    ],
                }
            )

            print(f"  Added: {label} at {coords}")

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"  Error: {e}")

    if custom_bboxes:
        print(f"\nDrawing {len(custom_bboxes)} custom bounding boxes...")
        custom_image = add_ruler_and_draw_boxes(image_data, custom_bboxes)

        output_path_custom = os.path.join(output_dir, "06_custom_boxes.jpg")
        with open(output_path_custom, "wb") as f:
            f.write(custom_image)
        print(f"Saved: {output_path_custom}")

    print("\nDone!")


if __name__ == "__main__":
    main()
