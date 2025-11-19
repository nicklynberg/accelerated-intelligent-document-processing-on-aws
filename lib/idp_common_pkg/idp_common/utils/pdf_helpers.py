"""
PDF utility functions for loading and converting PDF pages to images.

This module provides utilities for working with PDF documents in assessment
and other workflows that need to display PDF pages as images.
"""

import io
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF

    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def pdf_page_to_image(
    pdf_path: str | Path,
    page_number: int = 0,
    max_width: int = 1200,
    max_height: int = 1200,
    dpi_scale: float = 1.0,
) -> bytes:
    """
    Convert a PDF page to a PNG image with optional resizing.

    Args:
        pdf_path: Path to the PDF file
        page_number: Page number (0-based index)
        max_width: Maximum width in pixels (default: 1200 for ~1MP)
        max_height: Maximum height in pixels (default: 1200 for ~1MP)
        dpi_scale: DPI scaling factor (default: 1.0 = 72 DPI, 2.0 = 144 DPI)

    Returns:
        PNG image as bytes

    Raises:
        ImportError: If PyMuPDF is not installed
        FileNotFoundError: If PDF file doesn't exist
        ValueError: If page number is invalid
    """
    if not HAS_PYMUPDF:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF handling. "
            "Install with: pip install PyMuPDF"
        )

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    # Open PDF
    pdf_doc = fitz.open(str(pdf_path))

    try:
        # Validate page number
        if page_number < 0 or page_number >= len(pdf_doc):
            raise ValueError(
                f"Invalid page number {page_number}. "
                f"PDF has {len(pdf_doc)} pages (0-{len(pdf_doc) - 1})"
            )

        # Get the page
        page = pdf_doc[page_number]

        # Render page to pixmap
        mat = fitz.Matrix(dpi_scale, dpi_scale)
        pix = page.get_pixmap(matrix=mat)

        # Convert to PNG bytes
        png_bytes = pix.tobytes("png")

        # Always resize to ensure we stay within limits
        if HAS_PIL:
            png_bytes = _resize_image(png_bytes, max_width, max_height)

        return png_bytes

    finally:
        pdf_doc.close()


def pdf_to_images(
    pdf_path: str | Path,
    max_width: int = 1200,
    max_height: int = 1200,
    dpi_scale: float = 1.0,
    page_numbers: Optional[list[int]] = None,
) -> list[bytes]:
    """
    Convert multiple PDF pages to PNG images.

    Args:
        pdf_path: Path to the PDF file
        max_width: Maximum width in pixels (default: 1200 for ~1MP)
        max_height: Maximum height in pixels (default: 1200 for ~1MP)
        dpi_scale: DPI scaling factor (default: 1.0 = 72 DPI)
        page_numbers: List of page numbers to convert (0-based). If None, converts all pages.

    Returns:
        List of PNG images as bytes, one per page

    Raises:
        ImportError: If PyMuPDF is not installed
        FileNotFoundError: If PDF file doesn't exist
    """
    if not HAS_PYMUPDF:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF handling. "
            "Install with: pip install PyMuPDF"
        )

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    pdf_doc = fitz.open(str(pdf_path))

    try:
        # Determine which pages to convert
        if page_numbers is None:
            page_numbers = list(range(len(pdf_doc)))

        images = []
        for page_num in page_numbers:
            if page_num < 0 or page_num >= len(pdf_doc):
                raise ValueError(
                    f"Invalid page number {page_num}. "
                    f"PDF has {len(pdf_doc)} pages (0-{len(pdf_doc) - 1})"
                )

            # Get the page
            page = pdf_doc[page_num]

            # Render page to pixmap
            mat = fitz.Matrix(dpi_scale, dpi_scale)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PNG bytes
            png_bytes = pix.tobytes("png")

            # Always resize to ensure we stay within limits
            if HAS_PIL:
                png_bytes = _resize_image(png_bytes, max_width, max_height)

            images.append(png_bytes)

        return images

    finally:
        pdf_doc.close()


def get_pdf_page_count(pdf_path: str | Path) -> int:
    """
    Get the number of pages in a PDF.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Number of pages in the PDF

    Raises:
        ImportError: If PyMuPDF is not installed
        FileNotFoundError: If PDF file doesn't exist
    """
    if not HAS_PYMUPDF:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF handling. "
            "Install with: pip install PyMuPDF"
        )

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    pdf_doc = fitz.open(str(pdf_path))
    page_count = len(pdf_doc)
    pdf_doc.close()

    return page_count


def _resize_image(
    png_bytes: bytes,
    max_width: int,
    max_height: int,
) -> bytes:
    """
    Resize a PNG image while maintaining aspect ratio.

    Args:
        png_bytes: PNG image as bytes
        max_width: Maximum width in pixels
        max_height: Maximum height in pixels

    Returns:
        Resized PNG image as bytes
    """
    if not HAS_PIL:
        # If PIL not available, return original
        return png_bytes

    img = Image.open(io.BytesIO(png_bytes))

    # Resize to max dimensions while maintaining aspect ratio
    img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

    # Save as optimized PNG
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)

    return buffer.getvalue()


def create_minimal_png() -> bytes:
    """
    Create a minimal 1x1 pixel white PNG image.

    Useful as a fallback when PDF loading fails or for testing.

    Returns:
        Minimal PNG image as bytes (1x1 white pixel)
    """
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
