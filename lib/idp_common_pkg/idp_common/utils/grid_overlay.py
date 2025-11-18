# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Grid overlay module for adding coordinate references to document images.

This module provides functions to add ruler-style coordinate grids to images,
enabling LLMs to provide precise bounding box coordinates for extracted fields.
"""

import io
import logging

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def add_ruler_edges(
    image_data: bytes,
    ruler_width: int = 30,
    tick_interval: int = 50,
    label_interval: int = 100,
    ruler_color: tuple[int, int, int, int] = (240, 240, 240, 255),
    tick_color: str = "black",
    label_color: str = "black",
    font_size: int = 12,
) -> bytes:
    """
    Add ruler-style edges to the image (like graph paper margins).
    Document content remains completely unobscured.

    Args:
        image_data: Raw image bytes (JPEG, PNG, etc.)
        ruler_width: Width of the ruler margin in pixels
        tick_interval: Spacing between minor tick marks (in 0-1000 scale)
        label_interval: Spacing between labeled major tick marks (in 0-1000 scale)
        ruler_color: Background color of ruler (RGBA tuple)
        tick_color: Color of tick marks
        label_color: Color of coordinate labels
        font_size: Font size for labels

    Returns:
        Image bytes with ruler edges added (JPEG format)
    """
    image = Image.open(io.BytesIO(image_data)).convert("RGBA")
    orig_width, orig_height = image.size

    logger.info(f"Adding ruler edges to image {orig_width}x{orig_height}")

    # Create canvas with ruler margins on top and left
    new_width = orig_width + ruler_width
    new_height = orig_height + ruler_width

    canvas = Image.new("RGBA", (new_width, new_height), (255, 255, 255, 255))

    draw = ImageDraw.Draw(canvas)

    # Create ruler backgrounds
    # Top ruler (horizontal) - for X coordinates
    draw.rectangle([(ruler_width, 0), (new_width, ruler_width)], fill=ruler_color)
    # Left ruler (vertical) - for Y coordinates
    draw.rectangle([(0, ruler_width), (ruler_width, new_height)], fill=ruler_color)
    # Corner square
    draw.rectangle([(0, 0), (ruler_width, ruler_width)], fill=ruler_color)

    # Paste original image offset by ruler width
    canvas.paste(image, (ruler_width, ruler_width))

    # Load font
    font = _load_font(font_size)
    small_font = _load_font(max(font_size - 2, 8))

    # Draw tick marks and labels on TOP ruler (X-axis)
    for i in range(0, 1001, tick_interval):
        pixel_x = ruler_width + int((i / 1000.0) * orig_width)

        if i % label_interval == 0:
            # Major tick with label
            draw.line(
                [(pixel_x, ruler_width - 12), (pixel_x, ruler_width)],
                fill=tick_color,
                width=2,
            )
            # Center the label above the tick
            label = str(i)
            bbox = draw.textbbox((0, 0), label, font=font)
            label_width = bbox[2] - bbox[0]
            draw.text(
                (pixel_x - label_width // 2, 2),
                label,
                fill=label_color,
                font=font,
            )
        else:
            # Minor tick (no label)
            draw.line(
                [(pixel_x, ruler_width - 6), (pixel_x, ruler_width)],
                fill=tick_color,
                width=1,
            )

    # Draw tick marks and labels on LEFT ruler (Y-axis)
    for i in range(0, 1001, tick_interval):
        pixel_y = ruler_width + int((i / 1000.0) * orig_height)

        if i % label_interval == 0:
            # Major tick with label
            draw.line(
                [(ruler_width - 12, pixel_y), (ruler_width, pixel_y)],
                fill=tick_color,
                width=2,
            )
            # Right-align the label
            label = str(i)
            bbox = draw.textbbox((0, 0), label, font=font)
            label_width = bbox[2] - bbox[0]
            draw.text(
                (ruler_width - label_width - 14, pixel_y - 6),
                label,
                fill=label_color,
                font=font,
            )
        else:
            # Minor tick
            draw.line(
                [(ruler_width - 6, pixel_y), (ruler_width, pixel_y)],
                fill=tick_color,
                width=1,
            )

    # Add origin marker in corner (skip if using default font that doesn't support sizing)
    try:
        draw.text((2, 2), "0", fill=label_color, font=small_font)
    except (OSError, AttributeError):
        logger.debug("Skipping origin label - font rendering issue")

    canvas = canvas.convert("RGB")
    img_byte_array = io.BytesIO()
    canvas.save(img_byte_array, format="JPEG", quality=95)

    logger.info(f"Ruler edges added. New size: {new_width}x{new_height}")
    return img_byte_array.getvalue()


def draw_bounding_boxes(
    image_data: bytes,
    bboxes: list[dict],
    has_ruler: bool = False,
    ruler_width: int = 30,
    box_color: str = "red",
    box_width: int = 3,
    label_font_size: int = 12,
    show_labels: bool = True,
) -> bytes:
    """
    Draw bounding boxes on an image using normalized 0-1000 coordinates.

    Args:
        image_data: Raw image bytes
        bboxes: List of bounding box dictionaries, each containing:
            - 'bbox': [x1, y1, x2, y2] in 0-1000 normalized scale
            - 'label': Optional label text for the box
            - 'color': Optional color override for this box
            - 'page': Optional page number (for multi-page docs)
        has_ruler: If True, account for ruler margins in coordinate calculation
        ruler_width: Width of ruler margin (only used if has_ruler=True)
        box_color: Default color for bounding boxes
        box_width: Line width for bounding boxes
        label_font_size: Font size for box labels
        show_labels: Whether to show labels on boxes

    Returns:
        Image bytes with bounding boxes drawn

    Example:
        bboxes = [
            {
                'bbox': [150, 220, 380, 245],
                'label': 'Account Number',
                'color': 'green'
            },
            {
                'bbox': [100, 300, 500, 330],
                'label': 'Balance'
            }
        ]
        result = draw_bounding_boxes(image_data, bboxes)
    """
    image = Image.open(io.BytesIO(image_data)).convert("RGBA")
    width, height = image.size

    # If image has ruler edges, calculate the actual document area
    if has_ruler:
        doc_width = width - ruler_width
        doc_height = height - ruler_width
        offset_x = ruler_width
        offset_y = ruler_width
    else:
        doc_width = width
        doc_height = height
        offset_x = 0
        offset_y = 0

    # Create overlay for semi-transparent boxes
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font = _load_font(label_font_size)

    for i, bbox_info in enumerate(bboxes):
        bbox = bbox_info.get("bbox", [])
        if len(bbox) != 4:
            logger.warning(f"Invalid bbox format at index {i}: {bbox}")
            continue

        x1_norm, y1_norm, x2_norm, y2_norm = bbox

        # Convert from 0-1000 scale to pixel coordinates
        x1_pixel = offset_x + int((x1_norm / 1000.0) * doc_width)
        y1_pixel = offset_y + int((y1_norm / 1000.0) * doc_height)
        x2_pixel = offset_x + int((x2_norm / 1000.0) * doc_width)
        y2_pixel = offset_y + int((y2_norm / 1000.0) * doc_height)

        # Get color for this box
        color = bbox_info.get("color", box_color)

        # Draw rectangle outline
        draw.rectangle(
            [(x1_pixel, y1_pixel), (x2_pixel, y2_pixel)],
            outline=color,
            width=box_width,
        )

        # Add semi-transparent fill
        fill_color = _get_rgba_color(color, alpha=50)
        draw.rectangle(
            [
                (x1_pixel + box_width, y1_pixel + box_width),
                (x2_pixel - box_width, y2_pixel - box_width),
            ],
            fill=fill_color,
        )

        # Add label if provided
        if show_labels and "label" in bbox_info:
            label = bbox_info["label"]

            # Draw label background
            label_bbox = draw.textbbox((0, 0), label, font=font)
            label_width = label_bbox[2] - label_bbox[0]
            label_height = label_bbox[3] - label_bbox[1]

            # Position label above the box
            label_x = x1_pixel
            label_y = y1_pixel - label_height - 4

            # If label would go off top of image, put it below the box
            if label_y < offset_y:
                label_y = y2_pixel + 2

            # Draw label background
            draw.rectangle(
                [
                    (label_x - 2, label_y - 2),
                    (label_x + label_width + 2, label_y + label_height + 2),
                ],
                fill=(255, 255, 255, 220),
            )

            # Draw label text
            draw.text((label_x, label_y), label, fill=color, font=font)

        # Add coordinate annotation
        coord_text = f"[{x1_norm},{y1_norm},{x2_norm},{y2_norm}]"
        coord_bbox = draw.textbbox((0, 0), coord_text, font=_load_font(8))
        coord_width = coord_bbox[2] - coord_bbox[0]

        # Position coordinates at bottom-right of box
        coord_x = x2_pixel - coord_width - 2
        coord_y = y2_pixel + 2

        draw.rectangle(
            [(coord_x - 1, coord_y - 1), (coord_x + coord_width + 1, coord_y + 10)],
            fill=(255, 255, 255, 200),
        )
        draw.text((coord_x, coord_y), coord_text, fill="gray", font=_load_font(8))

    # Composite overlay onto original image
    result = Image.alpha_composite(image, overlay)
    result = result.convert("RGB")

    img_byte_array = io.BytesIO()
    result.save(img_byte_array, format="JPEG", quality=95)

    logger.info(f"Drew {len(bboxes)} bounding boxes on image")
    return img_byte_array.getvalue()


def add_ruler_and_draw_boxes(
    image_data: bytes,
    bboxes: list[dict],
    ruler_width: int = 30,
    tick_interval: int = 50,
    label_interval: int = 100,
    box_color: str = "red",
    box_width: int = 3,
) -> bytes:
    """
    Convenience function to add ruler edges and draw bounding boxes in one step.

    Args:
        image_data: Raw image bytes
        bboxes: List of bounding box dictionaries
        ruler_width: Width of ruler margin
        tick_interval: Spacing between minor ticks
        label_interval: Spacing between major ticks
        box_color: Default color for boxes
        box_width: Line width for boxes

    Returns:
        Image bytes with ruler and bounding boxes
    """
    # First add ruler edges
    image_with_ruler = add_ruler_edges(
        image_data,
        ruler_width=ruler_width,
        tick_interval=tick_interval,
        label_interval=label_interval,
    )

    # Then draw bounding boxes (accounting for ruler offset)
    result = draw_bounding_boxes(
        image_with_ruler,
        bboxes,
        has_ruler=True,
        ruler_width=ruler_width,
        box_color=box_color,
        box_width=box_width,
    )

    return result


def _load_font(size: int):
    """Load a font, falling back to default if not available."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]

    for font_path in font_paths:
        try:
            return ImageFont.truetype(font_path, size)
        except (OSError, IOError):
            continue

    # Fall back to default font without size (it's fixed size)
    logger.warning(
        "Could not load TrueType font from standard paths, using PIL default"
    )
    return ImageFont.load_default()


def _get_rgba_color(color_name: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Convert color name to RGBA tuple."""
    color_map = {
        "red": (255, 0, 0, alpha),
        "green": (0, 255, 0, alpha),
        "blue": (0, 0, 255, alpha),
        "yellow": (255, 255, 0, alpha),
        "orange": (255, 165, 0, alpha),
        "purple": (128, 0, 128, alpha),
        "cyan": (0, 255, 255, alpha),
        "magenta": (255, 0, 255, alpha),
        "lime": (0, 255, 0, alpha),
        "pink": (255, 192, 203, alpha),
        "black": (0, 0, 0, alpha),
        "white": (255, 255, 255, alpha),
        "gray": (128, 128, 128, alpha),
    }

    return color_map.get(color_name.lower(), (255, 0, 0, alpha))
