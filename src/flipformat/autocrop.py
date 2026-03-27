"""
Auto-crop module — detects a card / document / paper in a photo and
returns a tightly cropped, perspective-corrected, deskewed image.

Pipeline:
  1. Convert to grayscale, apply Gaussian blur.
  2. Edge detection (Canny).
  3. Find contours, pick the largest quad-like contour.
  4. Approximate the quadrilateral corners.
  5. Apply a perspective warp to produce a flat, rectangular output.
  6. Deskew: detect residual slant via Hough line transform and correct it.
  7. (Optional) OCR orientation fix: detect text direction and auto-rotate/mirror.

Falls back to simple center-crop heuristic if no good contour is found.
"""

from typing import Optional, Tuple, List
import math
import numpy as np

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from PIL import Image


ALGORITHM_ID = "contour_deskew_ocr_v2"


def autocrop(
    img: Image.Image,
    target_size: Optional[Tuple[int, int]] = None,
    deskew: bool = True,
    fix_orientation: bool = True,
) -> Image.Image:
    """
    Detect and crop the dominant rectangular object from *img*,
    correct any slant, and optionally fix text orientation.

    Parameters
    ----------
    img : PIL.Image.Image
        Input photograph.
    target_size : (width, height), optional
        If given, the cropped result is resized to this exact size.
    deskew : bool
        If True, detect and correct residual slant after perspective warp.
    fix_orientation : bool
        If True, use OCR to ensure text reads correctly (rotate/mirror if needed).

    Returns
    -------
    PIL.Image.Image
        Cropped, deskewed, orientation-corrected image.
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

    if deskew:
        cropped = _deskew(cropped)

    result = _cv_to_pil(cropped)

    if fix_orientation:
        result = _fix_text_orientation(result)

    if target_size is not None:
        result = result.resize(target_size, Image.LANCZOS)

    return result


def autocrop_pair(
    front: Image.Image,
    back: Image.Image,
    deskew: bool = True,
    fix_orientation: bool = True,
) -> Tuple[Image.Image, Image.Image]:
    """
    Auto-crop both sides and ensure they end up the same dimensions.
    The larger of the two detected crops determines the output size.
    """
    front_cropped = autocrop(front, deskew=deskew, fix_orientation=fix_orientation)
    back_cropped = autocrop(back, deskew=deskew, fix_orientation=fix_orientation)

    w = max(front_cropped.width, back_cropped.width)
    h = max(front_cropped.height, back_cropped.height)

    front_out = front_cropped.resize((w, h), Image.LANCZOS)
    back_out = back_cropped.resize((w, h), Image.LANCZOS)

    return front_out, back_out


# ---------------------------------------------------------------------- #
#  Deskew — Hough line-based slant correction                              #
# ---------------------------------------------------------------------- #

def _deskew(cv_img: np.ndarray, max_angle: float = 15.0) -> np.ndarray:
    """
    Detect residual rotation via Hough line transform and correct it.
    Only applies correction if the detected angle is within max_angle degrees.
    """
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=min(cv_img.shape[:2]) // 8,
                            maxLineGap=10)
    if lines is None or len(lines) == 0:
        return cv_img

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        # Normalize to the small deviation from horizontal (0) or vertical (90)
        if abs(angle) < 45:
            angles.append(angle)
        elif abs(angle - 90) < 45:
            angles.append(angle - 90)
        elif abs(angle + 90) < 45:
            angles.append(angle + 90)

    if not angles:
        return cv_img

    median_angle = float(np.median(angles))

    if abs(median_angle) < 0.3 or abs(median_angle) > max_angle:
        return cv_img

    h, w = cv_img.shape[:2]
    center = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)

    cos_a = abs(M[0, 0])
    sin_a = abs(M[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)
    M[0, 2] += (new_w - w) / 2
    M[1, 2] += (new_h - h) / 2

    rotated = cv2.warpAffine(cv_img, M, (new_w, new_h),
                             borderMode=cv2.BORDER_REPLICATE)

    # Trim any border artifacts from the rotation
    return _trim_border(rotated)


def _trim_border(cv_img: np.ndarray, threshold: int = 10) -> np.ndarray:
    """Remove near-black or replicated border rows/cols after rotation."""
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    top, bot, left, right = 0, h, 0, w

    for y in range(h // 4):
        if np.mean(gray[y, w // 4: 3 * w // 4]) > threshold:
            top = y
            break
    for y in range(h - 1, 3 * h // 4, -1):
        if np.mean(gray[y, w // 4: 3 * w // 4]) > threshold:
            bot = y + 1
            break
    for x in range(w // 4):
        if np.mean(gray[h // 4: 3 * h // 4, x]) > threshold:
            left = x
            break
    for x in range(w - 1, 3 * w // 4, -1):
        if np.mean(gray[h // 4: 3 * h // 4, x]) > threshold:
            right = x + 1
            break

    if bot > top and right > left:
        return cv_img[top:bot, left:right]
    return cv_img


# ---------------------------------------------------------------------- #
#  OCR-based orientation fix                                               #
# ---------------------------------------------------------------------- #

def _fix_text_orientation(img: Image.Image) -> Image.Image:
    """
    Use OCR to determine if the image text is readable. Try all four
    rotations (0, 90, 180, 270) and optionally a horizontal mirror.
    Pick the orientation with the highest OCR confidence / readable text count.
    """
    try:
        import pytesseract
    except ImportError:
        return img

    best_img = img
    best_score = _ocr_confidence(img)

    candidates = [
        ("rot90", img.transpose(Image.ROTATE_270)),
        ("rot180", img.transpose(Image.ROTATE_180)),
        ("rot270", img.transpose(Image.ROTATE_90)),
        ("mirror", img.transpose(Image.FLIP_LEFT_RIGHT)),
        ("mirror_rot180", img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_180)),
    ]

    for _label, candidate in candidates:
        score = _ocr_confidence(candidate)
        if score > best_score:
            best_score = score
            best_img = candidate

    return best_img


def _ocr_confidence(img: Image.Image) -> float:
    """
    Run Tesseract on the image and return a composite score:
    number of high-confidence words (conf > 60) found.
    """
    try:
        import pytesseract
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, timeout=5)
        confs = data.get("conf", [])
        texts = data.get("text", [])
        score = 0.0
        for conf, text in zip(confs, texts):
            try:
                c = int(conf)
            except (ValueError, TypeError):
                continue
            if c > 60 and len(str(text).strip()) >= 2:
                score += c / 100.0
        return score
    except Exception:
        return 0.0


# ---------------------------------------------------------------------- #
#  Contour detection (unchanged core logic)                                #
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
