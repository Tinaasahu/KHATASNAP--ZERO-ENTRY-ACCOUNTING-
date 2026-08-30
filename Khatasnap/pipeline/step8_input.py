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
    """Convert PDF pages to BGR numpy images using pymupdf, pypdfium2, or pdf2image."""
    # Method 1: pymupdf (Fastest, zero external binaries needed)
    try:
        import pymupdf
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        images = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=300)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
            if pix.n == 4:
                bgr = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif pix.n == 1:
                bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                bgr = img
            logger.info(f"PyMuPDF rendered page {i+1}: {bgr.shape[1]}x{bgr.shape[0]}px")
            images.append(bgr)
        if images:
            logger.info(f"Loaded PDF with {len(images)} pages via pymupdf")
            return images
    except Exception as e:
        logger.warning(f"pymupdf rendering failed: {e}, trying pypdfium2...")

    # Method 2: pypdfium2
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(file_bytes)
        images = []
        for i in range(len(pdf)):
            page = pdf[i]
            pil_image = page.render(scale=300/72).to_pil()
            bgr = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            logger.info(f"pypdfium2 rendered page {i+1}: {bgr.shape[1]}x{bgr.shape[0]}px")
            images.append(bgr)
        if images:
            logger.info(f"Loaded PDF with {len(images)} pages via pypdfium2")
            return images
    except Exception as e:
        logger.warning(f"pypdfium2 rendering failed: {e}, trying pdf2image...")

    # Method 3: pdf2image
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(file_bytes, dpi=300, fmt="RGB")
        images = []
        for i, page in enumerate(pages):
            bgr = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
            images.append(bgr)
        return images
    except Exception as e:
        raise ValueError(f"Could not convert PDF: {e}")

