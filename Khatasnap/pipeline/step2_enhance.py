"""
Step 2 — Smart Image Enhancement
Implements ALL techniques:
- Deskew, denoise, shadow removal, CLAHE contrast
- Wiener filter deblur for motion blur (phone photos)
- Morphological cleanup for broken characters
"""
import cv2
import numpy as np
from pipeline.step1_quality import analyze_quality


def _is_screen_photo(image: np.ndarray) -> bool:
    """
    Detect if image is a photo of a screen.
    Screen photos have regular high-frequency patterns (pixel grid)
    visible in the FFT frequency domain.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape)==3 else image
    # Downsample for speed
    small = cv2.resize(gray, (512, 512))
    f = np.fft.fft2(small.astype(float))
    fshift = np.fft.fftshift(f)
    magnitude = np.log(np.abs(fshift) + 1)
    # Screen photos show strong periodic peaks away from center
    h, w = magnitude.shape
    center_mask = np.zeros_like(magnitude, dtype=bool)
    center_mask[h//2-30:h//2+30, w//2-30:w//2+30] = True
    peripheral = magnitude[~center_mask]
    center_val = magnitude[center_mask].mean()
    # High peripheral peaks relative to center = screen pattern
    peak_ratio = np.percentile(peripheral, 99) / (center_val + 1e-6)
    return peak_ratio > 2.5


def _demoire(image: np.ndarray) -> np.ndarray:
    """
    Remove moiré patterns from screen photography.
    Uses a combination of Gaussian blur + bilateral filter to
    smooth the pixel grid without destroying text edges.
    """
    # Step 1: Mild Gaussian to kill the pixel grid frequency
    blurred = cv2.GaussianBlur(image, (3, 3), 0.8)
    # Step 2: Bilateral filter preserves edges while smoothing noise
    denoised = cv2.bilateralFilter(blurred, d=9, sigmaColor=75, sigmaSpace=75)
    return denoised


def _remove_glare(image: np.ndarray) -> np.ndarray:
    """
    Reduce specular glare (bright white spots from flash/reflections).
    Detects overexposed regions and inpaints them using surrounding context.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape)==3 else image
    # Glare mask: pixels brighter than 250
    _, glare_mask = cv2.threshold(gray, 250, 255, cv2.THRESH_BINARY)
    # Dilate mask slightly to cover glare edges
    kernel = np.ones((5, 5), np.uint8)
    glare_mask = cv2.dilate(glare_mask, kernel, iterations=2)
    if glare_mask.sum() == 0:
        return image
    # Inpaint glare regions
    result = cv2.inpaint(image, glare_mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)
    return result


def enhance(image: np.ndarray, quality: dict = None) -> np.ndarray:
    if quality is None:
        quality = analyze_quality(image)
    scores = quality["scores"]
    result = image.copy()

    # 0. Screen photo detection and special handling
    if _is_screen_photo(result):
        import logging
        logging.getLogger(__name__).info("Screen photo detected — applying deglare + demoiré")
        result = _remove_glare(result)
        result = _demoire(result)

    # 1. Deskew
    skew = scores.get("skew_angle_deg", 0.0)
    if abs(skew) > 1.5:
        result = _deskew(result, skew)

    # 2. Wiener deblur — for motion blur from shaky phone photos
    if scores["sharpness"] < 0.3:
        result = _wiener_deblur(result)

    # 3. Denoise
    if scores["noise"] < 0.5:
        result = cv2.fastNlMeansDenoisingColored(
            result, None, h=8, hColor=8,
            templateWindowSize=7, searchWindowSize=15
        )

    # 4. Shadow removal
    result = _remove_shadows_fast(result)

    # 5. CLAHE contrast boost
    result = _boost_contrast(result, scores)

    # 6. Sharpening
    if scores["sharpness"] < 0.5:
        result = _sharpen(result)

    # 7. Upscale if too small
    h, w = result.shape[:2]
    if min(h, w) < 1200:
        scale = 1200 / min(h, w)
        result = cv2.resize(result, (int(w * scale), int(h * scale)),
                            interpolation=cv2.INTER_CUBIC)

    return result


def _wiener_deblur(image: np.ndarray) -> np.ndarray:
    """
    Frequency-domain Wiener filter deblur.
    Reverses motion blur by modelling it as a convolution and inverting it.
    Works much better than unsharp masking for phone camera motion blur.
    """
    def wiener_channel(ch):
        # Estimate PSF (point spread function) as a horizontal motion blur kernel
        psf = np.zeros((1, 15), np.float32)
        psf[0, :] = 1.0 / 15
        # Pad PSF to image size
        psf_pad = np.zeros_like(ch, dtype=np.float32)
        psf_pad[:1, :15] = psf
        # FFT
        img_f = np.fft.fft2(ch.astype(np.float32))
        psf_f = np.fft.fft2(psf_pad)
        # Wiener filter: H* / (|H|^2 + K) where K is noise-to-signal ratio
        K = 0.01
        psf_conj = np.conj(psf_f)
        wiener = psf_conj / (np.abs(psf_f) ** 2 + K)
        restored = np.fft.ifft2(img_f * wiener).real
        return np.clip(restored, 0, 255).astype(np.uint8)

    channels = cv2.split(image)
    restored = [wiener_channel(ch) for ch in channels]
    return cv2.merge(restored)


def _boost_contrast(image: np.ndarray, scores: dict) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    if scores.get("contrast", 1.0) < 0.35:
        p2, p98 = np.percentile(l, 2), np.percentile(l, 98)
        if p98 > p2:
            l = np.clip((l.astype(float) - p2) / (p98 - p2) * 255, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def _deskew(image: np.ndarray, angle: float) -> np.ndarray:
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    M[0, 2] += (new_w - w) / 2
    M[1, 2] += (new_h - h) / 2
    return cv2.warpAffine(image, M, (new_w, new_h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _sharpen(image: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=2)
    return cv2.addWeighted(image, 1.4, blurred, -0.4, 0)


def _remove_shadows_fast(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    scale = min(1.0, 800 / max(h, w))
    small = cv2.resize(image, (int(w * scale), int(h * scale)))
    channels = cv2.split(small)
    orig_channels = cv2.split(image)
    result_channels = []
    for i, ch in enumerate(channels):
        dilated = cv2.dilate(ch, np.ones((7, 7), np.uint8))
        bg_small = cv2.GaussianBlur(dilated, (21, 21), 0)
        bg = cv2.resize(bg_small, (w, h))
        diff = 255 - cv2.absdiff(orig_channels[i], bg)
        norm = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
        result_channels.append(norm)
    return cv2.merge(result_channels)


def prepare_for_ocr(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, blockSize=15, C=8
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)