"""
Step 5 — Layout Reconstruction
Implements ALL techniques:
- Adaptive y-tolerance row grouping (median block height)
- Y-overlap based row merging (fixes split detections)
- X-histogram column detection (more accurate than Voronoi)
"""
import numpy as np
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def group_into_rows(blocks: list[dict], y_tolerance: int = None) -> list[list[dict]]:
    """
    Group text blocks into horizontal rows.
    Uses y-overlap merging first, then cy-distance fallback.
    """
    if not blocks: return []

    if y_tolerance is None:
        heights = [b["bbox"]["y2"] - b["bbox"]["y1"] for b in blocks]
        med = float(np.median(heights)) if heights else 20
        y_tolerance = max(8, min(24, int(med * 0.6)))
        logger.info(f"y_tolerance={y_tolerance}px, {len(blocks)} blocks")

    # Sort by vertical center
    srt = sorted(blocks, key=lambda b: b["bbox"]["cy"])
    rows, cur = [], [srt[0]]

    for b in srt[1:]:
        # Use y-overlap check: do this block and the current row overlap vertically?
        row_y1 = min(x["bbox"]["y1"] for x in cur)
        row_y2 = max(x["bbox"]["y2"] for x in cur)
        b_y1, b_y2 = b["bbox"]["y1"], b["bbox"]["y2"]

        overlap = min(row_y2, b_y2) - max(row_y1, b_y1)
        b_height = b_y2 - b_y1
        overlap_ratio = overlap / b_height if b_height > 0 else 0

        # Accept if >30% overlap OR within cy tolerance
        cy_dist = abs(b["bbox"]["cy"] - np.mean([x["bbox"]["cy"] for x in cur]))
        if overlap_ratio > 0.3 or cy_dist <= y_tolerance:
            cur.append(b)
        else:
            rows.append(sorted(cur, key=lambda x: x["bbox"]["x1"]))
            cur = [b]

    rows.append(sorted(cur, key=lambda x: x["bbox"]["x1"]))
    logger.info(f"Grouped into {len(rows)} rows")
    return rows


def build_column_map_histogram(blocks: list[dict], image_width: int) -> dict:
    """
    X-histogram based column detection.
    Finds peaks in the distribution of block x1 positions.
    Much more accurate than Voronoi for detecting true column boundaries.
    Returns: {column_index: (x_start, x_end)}
    """
    if not blocks or image_width <= 0:
        return {}

    # Build histogram of x1 positions
    hist = np.zeros(image_width, dtype=int)
    for b in blocks:
        x1 = min(b["bbox"]["x1"], image_width - 1)
        hist[x1] += 1

    # Smooth histogram to find peaks
    kernel = np.ones(20) / 20
    smooth = np.convolve(hist, kernel, mode='same')

    # Find peaks — positions with local maxima above threshold
    threshold = smooth.max() * 0.15
    peaks = []
    in_peak = False
    peak_start = 0

    for i, v in enumerate(smooth):
        if v > threshold and not in_peak:
            in_peak = True
            peak_start = i
        elif v <= threshold and in_peak:
            in_peak = False
            peak_center = (peak_start + i) // 2
            peaks.append(peak_center)

    if in_peak:
        peaks.append((peak_start + image_width) // 2)

    if not peaks:
        return {}

    # Build column zones: each column spans from midpoint to midpoint
    col_map = {}
    for i, peak in enumerate(peaks):
        x_start = (peaks[i-1] + peak) // 2 if i > 0 else 0
        x_end   = (peak + peaks[i+1]) // 2 if i < len(peaks)-1 else image_width
        col_map[i] = (x_start, x_end)

    return col_map


def assign_column_histogram(block: dict, col_map: dict) -> int | None:
    """Assign a block to a column using histogram-based map."""
    if not col_map: return None
    cx = (block["bbox"]["x1"] + block["bbox"]["x2"]) / 2
    for col_idx, (x_start, x_end) in col_map.items():
        if x_start <= cx < x_end:
            return col_idx
    # Fallback: nearest column center
    centers = {i: (x_start + x_end) / 2 for i, (x_start, x_end) in col_map.items()}
    return min(centers, key=lambda i: abs(centers[i] - cx))


def row_to_text(row: list[dict]) -> str:
    return " ".join(b["text"] for b in row)