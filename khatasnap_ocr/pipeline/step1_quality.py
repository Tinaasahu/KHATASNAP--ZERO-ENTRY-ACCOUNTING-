"""
Step 1 — Image Quality Analyzer
Scores the input image and flags issues before processing.
"""
import cv2
import numpy as np


def analyze_quality(image: np.ndarray) -> dict:
    """
    Analyze image quality and return a report with scores and issues.
    All scores are 0.0 to 1.0. Overall score below 0.4 = poor quality.
    """
    issues = []
    scores = {}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()

    # ── 1. Blur / sharpness (Laplacian variance) ─────────────────────────
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Typical sharp invoice: >300. Blurry phone photo: <80
    sharpness = min(lap_var / 500.0, 1.0)
    scores["sharpness"] = round(sharpness, 3)
    if sharpness < 0.15:
        issues.append("Image is very blurry — hold camera steady or use a scanner")
    elif sharpness < 0.35:
        issues.append("Image is slightly blurry — results may be less accurate")

    # ── 2. Brightness ─────────────────────────────────────────────────────
    mean_brightness = gray.mean() / 255.0
    # Ideal range: 0.4 – 0.85
    if mean_brightness < 0.25:
        brightness_score = mean_brightness / 0.25
        issues.append("Image is too dark — use better lighting")
    elif mean_brightness > 0.92:
        brightness_score = 1.0 - ((mean_brightness - 0.92) / 0.08)
        issues.append("Image is overexposed — reduce brightness or avoid direct flash")
    else:
        # Score peaks at 0.6 brightness
        brightness_score = 1.0 - abs(mean_brightness - 0.6) / 0.35
    scores["brightness"] = round(max(brightness_score, 0.0), 3)

    # ── 3. Contrast ───────────────────────────────────────────────────────
    contrast = gray.std() / 128.0
    scores["contrast"] = round(min(contrast, 1.0), 3)
    if contrast < 0.2:
        issues.append("Low contrast — text may be hard to read")

    # ── 4. Resolution ─────────────────────────────────────────────────────
    h, w = gray.shape[:2]
    min_dim = min(h, w)
    # Minimum usable: 600px. Good: 1200px+
    resolution_score = min(min_dim / 1200.0, 1.0)
    scores["resolution"] = round(resolution_score, 3)
    if min_dim < 600:
        issues.append(f"Resolution too low ({w}x{h}) — minimum 600px on shortest side")
    elif min_dim < 900:
        issues.append(f"Resolution acceptable ({w}x{h}) but higher is better")

    # ── 5. Skew / rotation detection ──────────────────────────────────────
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)
    skew_angle = 0.0
    if lines is not None:
        angles = []
        for line in lines[:20]:
            rho, theta = line[0]
            angle = np.degrees(theta) - 90
            if abs(angle) < 45:
                angles.append(angle)
        if angles:
            skew_angle = float(np.median(angles))

    skew_score = 1.0 - min(abs(skew_angle) / 20.0, 1.0)
    scores["skew"] = round(skew_score, 3)
    scores["skew_angle_deg"] = round(skew_angle, 2)
    if abs(skew_angle) > 10:
        issues.append(f"Document is tilted {skew_angle:.1f}° — will auto-correct")
    elif abs(skew_angle) > 5:
        issues.append(f"Slight tilt detected ({skew_angle:.1f}°) — will auto-correct")

    # ── 6. Noise level ────────────────────────────────────────────────────
    # Estimate noise via difference from Gaussian blur
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    noise = np.abs(gray.astype(float) - blurred.astype(float)).mean()
    noise_score = 1.0 - min(noise / 15.0, 1.0)
    scores["noise"] = round(noise_score, 3)
    if noise_score < 0.4:
        issues.append("High noise detected — image may be from low quality camera")

    # ── Overall score (weighted average) ─────────────────────────────────
    weights = {
        "sharpness":   0.35,
        "brightness":  0.20,
        "contrast":    0.15,
        "resolution":  0.20,
        "skew":        0.05,
        "noise":       0.05,
    }
    overall = sum(scores[k] * weights[k] for k in weights)
    scores["overall"] = round(overall, 3)

    grade = "excellent" if overall > 0.8 else \
            "good"      if overall > 0.6 else \
            "fair"      if overall > 0.4 else "poor"

    return {
        "scores":     scores,
        "grade":      grade,
        "issues":     issues,
        "dimensions": {"width": int(w), "height": int(h)},
        "processable": overall > 0.25,  # Below this — reject with message
    }
