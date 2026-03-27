"""
Auto-crop module — detects a card / document / paper in a photo and
returns a tightly cropped, perspective-corrected image.

Pipeline:
  1. Convert to grayscale, apply Gaussian blur.
  2. Edge detection (Canny).
  3. Find contours, pick the largest quad-like contour.
  4. Approximate the quadrilateral corners.
  5. Apply a perspective warp to produce a flat, rectangular output.

Falls back to simple center-crop heuristic if no good contour is found.
"""

from typing import Optional, Tuple, List
import numpy as np

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from PIL import Image


ALGORITHM_ID = "contour_detection_v1"


def autocrop(img: Image.Image, target_size: Optional[Tuple[int, int]] = None) -> Image.Image:
    """
    Detect and crop the dominant rectangular object from *img*.

    Parameters
    ----------
    img : PIL.Image.Image
        Input photograph.
    target_size : (width, height), optional
        If given, the cropped result is resized to this exact size.

    Returns
    -------
    PIL.Image.Image
        Cropped (and optionally resized) image.
    """
    if not _HAS_CV2:
        raise RuntimeError(
            "OpenCV is required for auto-crop. Install it: pip install opencv-python-headless"
        )

    cv_img = _pil_to_cv(img)
    corners = _detect_quad(cv_img)

    if corners is not None:
        cropped = _perspective_crop(cv_img, corners)
    else:
        cropped = _fallback_center_crop(cv_img)

    result = _cv_to_pil(cropped)

    if target_size is not None:
        result = result.resize(target_size, Image.LANCZOS)

    return result


def autocrop_pair(
    front: Image.Image,
    back: Image.Image,
) -> Tuple[Image.Image, Image.Image]:
    """
    Auto-crop both sides and ensure they end up the same dimensions.
    The larger of the two detected crops determines the output size.
    """
    front_cropped = autocrop(front)
    back_cropped = autocrop(back)

    w = max(front_cropped.width, back_cropped.width)
    h = max(front_cropped.height, back_cropped.height)

    front_out = front_cropped.resize((w, h), Image.LANCZOS)
    back_out = back_cropped.resize((w, h), Image.LANCZOS)

    return front_out, back_out


# ---------------------------------------------------------------------- #
#  Internal detection pipeline                                             #
# ---------------------------------------------------------------------- #

def _detect_quad(cv_img: np.ndarray) -> Optional[np.ndarray]:
    """
    Return 4 corner points of the dominant rectangle, or None if not found.
    Points are ordered: top-left, top-right, bottom-right, bottom-left.
    """
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    edges = cv2.Canny(blurred, 50, 150)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    img_area = cv_img.shape[0] * cv_img.shape[1]
    min_area = img_area * 0.05

    candidates: List[Tuple[float, np.ndarray]] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue

        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

        if len(approx) == 4 and cv2.isContourConvex(approx):
            candidates.append((area, approx))

    if not candidates:
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            rect = cv2.minAreaRect(cnt)
            box = cv2.boxPoints(rect)
            box = np.intp(box)
            rect_area = rect[1][0] * rect[1][1]
            if rect_area > 0 and area / rect_area > 0.7:
                candidates.append((area, box.reshape(4, 1, 2)))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1].reshape(4, 2).astype(np.float32)

    return _order_points(best)


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Order points: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]

    return rect


def _perspective_crop(cv_img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Warp the quadrilateral to a flat rectangle."""
    tl, tr, br, bl = corners

    width_top = np.linalg.norm(tr - tl)
    width_bot = np.linalg.norm(br - bl)
    width = int(max(width_top, width_bot))

    height_left = np.linalg.norm(bl - tl)
    height_right = np.linalg.norm(br - tr)
    height = int(max(height_left, height_right))

    width = max(width, 1)
    height = max(height, 1)

    dst = np.array([
        [0, 0],
        [width - 1, 0],
        [width - 1, height - 1],
        [0, height - 1],
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(corners, dst)
    warped = cv2.warpPerspective(cv_img, M, (width, height))
    return warped


def _fallback_center_crop(cv_img: np.ndarray, margin_pct: float = 0.05) -> np.ndarray:
    """If quad detection fails, trim a small margin from all edges."""
    h, w = cv_img.shape[:2]
    mx = int(w * margin_pct)
    my = int(h * margin_pct)
    return cv_img[my:h - my, mx:w - mx]


# ---------------------------------------------------------------------- #
#  PIL <-> OpenCV conversions                                              #
# ---------------------------------------------------------------------- #

def _pil_to_cv(img: Image.Image) -> np.ndarray:
    rgb = img.convert("RGB")
    return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)


def _cv_to_pil(cv_img: np.ndarray) -> Image.Image:
    rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)
