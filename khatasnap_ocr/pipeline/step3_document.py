"""
Step 3 — Document Detection & Perspective Correction
Detects the bill boundary and warps it to a flat rectangle.
Handles: tilted photos, angled shots, curved pages.
"""
import cv2
import numpy as np


def detect_and_correct(image: np.ndarray) -> tuple[np.ndarray, bool]:
    """
    Detect document boundary and apply perspective correction.
    Returns (corrected_image, was_corrected).
    If no document boundary found, returns original image unchanged.
    """
    corners = _detect_corners(image)

    if corners is not None:
        corrected = _four_point_transform(image, corners)
        return corrected, True

    return image, False


def _detect_corners(image: np.ndarray) -> np.ndarray | None:
    """
    Find the four corners of a document in an image.
    Uses a multi-strategy approach for robustness.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Strategy 1: Edge-based contour detection
    corners = _edge_based_detection(gray, w, h)
    if corners is not None:
        return corners

    # Strategy 2: Threshold-based (works better for white bills on dark surfaces)
    corners = _threshold_based_detection(gray, w, h)
    if corners is not None:
        return corners

    return None


def _edge_based_detection(gray: np.ndarray, w: int, h: int) -> np.ndarray | None:
    """Standard Canny + contour approach."""
    # Blur to reduce noise before edge detection
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    # Dilate edges to connect broken lines
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return _find_doc_contour(contours, w, h)


def _threshold_based_detection(gray: np.ndarray, w: int, h: int) -> np.ndarray | None:
    """Otsu threshold approach — good for white paper on dark background."""
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return _find_doc_contour(contours, w, h)


def _find_doc_contour(contours, w: int, h: int) -> np.ndarray | None:
    """
    Find the largest quadrilateral contour that looks like a document.
    Must cover at least 20% of image area.
    """
    min_area = w * h * 0.20
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for contour in contours[:5]:  # Only check top 5 largest
        area = cv2.contourArea(contour)
        if area < min_area:
            break

        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

        if len(approx) == 4:
            # Validate: corners should be roughly spread across the image
            pts = approx.reshape(4, 2)
            x_spread = pts[:, 0].max() - pts[:, 0].min()
            y_spread = pts[:, 1].max() - pts[:, 1].min()
            if x_spread > w * 0.3 and y_spread > h * 0.3:
                return approx

    return None


def _four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    Apply perspective transform given 4 corner points.
    Orders points: top-left, top-right, bottom-right, bottom-left.
    """
    pts = pts.reshape(4, 2).astype("float32")

    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # top-left: smallest sum
    rect[2] = pts[np.argmax(s)]   # bottom-right: largest sum
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right: smallest diff
    rect[3] = pts[np.argmax(diff)]  # bottom-left: largest diff

    tl, tr, br, bl = rect

    width  = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))

    dst = np.array([
        [0, 0],
        [width - 1, 0],
        [width - 1, height - 1],
        [0, height - 1]
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (width, height))


def auto_crop_margins(image: np.ndarray, margin_px: int = 10) -> np.ndarray:
    """Remove white/black borders after perspective correction."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return image
    x, y, w, h = cv2.boundingRect(coords)
    # Add small margin back
    x = max(0, x - margin_px)
    y = max(0, y - margin_px)
    w = min(image.shape[1] - x, w + 2 * margin_px)
    h = min(image.shape[0] - y, h + 2 * margin_px)
    return image[y:y+h, x:x+w]
