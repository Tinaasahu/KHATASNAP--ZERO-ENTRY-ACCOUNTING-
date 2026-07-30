"""
Step 8 — Input Handler
Handles all input types: JPG/PNG (camera/scan), PDF.
Converts everything to a list of numpy BGR images for the pipeline.
"""
import cv2
import numpy as np
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_input(file_bytes: bytes, filename: str) -> list[np.ndarray]:
    """
    Load input file and return list of BGR images (one per page for PDFs).
    Supports: jpg, jpeg, png, webp, bmp, tiff, pdf
    """
    ext = Path(filename).suffix.lower().lstrip(".")

    if ext == "pdf":
        return _load_pdf(file_bytes)
    else:
        return _load_image(file_bytes, filename)


def _load_image(file_bytes: bytes, filename: str) -> list[np.ndarray]:
    """Decode image bytes to BGR numpy array."""
    nparr = np.frombuffer(file_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError(
            f"Could not decode image '{filename}'. "
            "Ensure the file is a valid JPG, PNG, or WEBP image."
        )

    logger.info(f"Loaded image: {image.shape[1]}x{image.shape[0]}px")
    return [image]


def _load_pdf(file_bytes: bytes) -> list[np.ndarray]:
    """Convert PDF pages to images using pdfplumber + pdf2image."""
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        raise ImportError(
            "pdf2image is required for PDF support.\n"
            "Install it with: pip install pdf2image\n"
            "Also install poppler: https://github.com/oschwartz10612/poppler-windows/releases"
        )

    try:
        pages = convert_from_bytes(
            file_bytes,
            dpi=300,           # High DPI for good OCR quality
            fmt="RGB",
        )
    except Exception as e:
        raise ValueError(f"Could not convert PDF: {e}")

    images = []
    for i, page in enumerate(pages):
        # Convert PIL RGB → BGR numpy array
        bgr = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
        logger.info(f"PDF page {i+1}: {bgr.shape[1]}x{bgr.shape[0]}px")
        images.append(bgr)

    logger.info(f"Loaded PDF with {len(images)} pages")
    return images
