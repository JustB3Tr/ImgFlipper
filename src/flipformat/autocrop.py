"""
Auto-crop module — robust detection of cards, documents, and paper in photos.

Multi-strategy pipeline that handles:
  - Dark cards on dark surfaces (low contrast)
  - Light cards on light surfaces
  - Textured backgrounds (wood grain, fabric)
  - Slight to moderate perspective/rotation
  - Cards that only partially contrast with background

Strategies tried (best result wins):
  1. Multi-channel Canny edges (BGR channels independently)
  2. Adaptive thresholding (handles uneven lighting)
  3. CLAHE-enhanced contrast + Canny
  4. Saturation/color-based segmentation
  5. Laplacian of Gaussian edge detection
  6. GrabCut foreground segmentation (fallback)

Each strategy produces quad candidates. The best quad is selected based on
a scoring function that considers area, rectangularity, and position.
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


ALGORITHM_ID = "multi_strategy_crop_v4"


# ---------------------------------------------------------------------- #
#  Public API                                                              #
# ---------------------------------------------------------------------- #

def autocrop(
    img: Image.Image,
    target_size: Optional[Tuple[int, int]] = None,
    deskew: bool = True,
    fix_orientation: bool = True,
) -> Image.Image:
    if not _HAS_CV2:
        raise RuntimeError(
            "OpenCV is required for auto-crop. Install it: pip install opencv-python-headless"
        )

    cv_img = _pil_to_cv(img)

    # Downscale for faster detection, keep mapping to original
    cv_work, scale = _downscale(cv_img, max_dim=1024)

    corners = _detect_quad_multi(cv_work)

    if corners is not None:
        # Map corners back to original resolution
        corners_orig = corners * scale
        cropped = _perspective_crop(cv_img, corners_orig)
    else:
        cropped = _fallback_grabcut(cv_img)

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
    front_cropped = autocrop(front, deskew=deskew, fix_orientation=fix_orientation)
    back_cropped = autocrop(back, deskew=deskew, fix_orientation=fix_orientation)

    w = max(front_cropped.width, back_cropped.width)
    h = max(front_cropped.height, back_cropped.height)

    front_out = front_cropped.resize((w, h), Image.LANCZOS)
    back_out = back_cropped.resize((w, h), Image.LANCZOS)

    return front_out, back_out


# ---------------------------------------------------------------------- #
#  Multi-strategy quad detection                                           #
# ---------------------------------------------------------------------- #

def _detect_quad_multi(cv_img: np.ndarray) -> Optional[np.ndarray]:
    """
    Try multiple edge/segmentation strategies and pick the best quad.
    """
    h, w = cv_img.shape[:2]
    img_area = h * w
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    all_candidates: List[Tuple[float, np.ndarray]] = []

    # Strategy 1: Multi-threshold Canny on grayscale
    for lo, hi in [(20, 80), (40, 120), (60, 180), (80, 200)]:
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, lo, hi)
        edges = _close_edges(edges)
        quads = _find_quads_in_edges(edges, img_area)
        all_candidates.extend(quads)

    # Strategy 2: Per-channel Canny
    for ch in cv2.split(cv_img):
        blurred_ch = cv2.GaussianBlur(ch, (5, 5), 0)
        edges = cv2.Canny(blurred_ch, 30, 100)
        edges = _close_edges(edges)
        quads = _find_quads_in_edges(edges, img_area)
        all_candidates.extend(quads)

    # Strategy 3: CLAHE enhanced contrast
    for clip_limit in (2.0, 4.0, 8.0):
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
        for lo, hi in [(30, 100), (50, 150)]:
            edges = cv2.Canny(blurred, lo, hi)
            edges = _close_edges(edges)
            quads = _find_quads_in_edges(edges, img_area)
            all_candidates.extend(quads)

    # Strategy 4: Adaptive thresholding
    for block_size in (15, 25, 51):
        for C_val in (3, 8, 15):
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, block_size, C_val,
            )
            thresh = _close_edges(thresh, kernel_size=5, iterations=2)
            quads = _find_quads_in_edges(thresh, img_area)
            all_candidates.extend(quads)

            thresh_inv = cv2.bitwise_not(thresh)
            thresh_inv = _close_edges(thresh_inv, kernel_size=5, iterations=2)
            quads = _find_quads_in_edges(thresh_inv, img_area)
            all_candidates.extend(quads)

    # Strategy 5: Saturation channel
    hsv = cv2.cvtColor(cv_img, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    for lo, hi in [(30, 100), (50, 150)]:
        sat_blur = cv2.GaussianBlur(sat, (5, 5), 0)
        edges = cv2.Canny(sat_blur, lo, hi)
        edges = _close_edges(edges)
        quads = _find_quads_in_edges(edges, img_area)
        all_candidates.extend(quads)

    # Strategy 6: Otsu thresholding
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    otsu = _close_edges(otsu, kernel_size=5, iterations=2)
    quads = _find_quads_in_edges(otsu, img_area)
    all_candidates.extend(quads)
    otsu_inv = cv2.bitwise_not(otsu)
    otsu_inv = _close_edges(otsu_inv, kernel_size=5, iterations=2)
    quads = _find_quads_in_edges(otsu_inv, img_area)
    all_candidates.extend(quads)

    # Strategy 7: Laplacian edge detection
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    lap = np.uint8(np.absolute(lap))
    _, lap_thresh = cv2.threshold(lap, 30, 255, cv2.THRESH_BINARY)
    lap_thresh = _close_edges(lap_thresh, kernel_size=5, iterations=3)
    quads = _find_quads_in_edges(lap_thresh, img_area)
    all_candidates.extend(quads)

    if not all_candidates:
        return None

    best = _pick_best_quad(all_candidates, cv_img, w, h)
    return best


def _close_edges(edges: np.ndarray, kernel_size: int = 3, iterations: int = 2) -> np.ndarray:
    """Morphological close to connect broken edge segments."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    closed = cv2.dilate(edges, kernel, iterations=iterations)
    closed = cv2.erode(closed, kernel, iterations=max(1, iterations - 1))
    return closed


def _find_quads_in_edges(edges: np.ndarray, img_area: int) -> List[Tuple[float, np.ndarray]]:
    """Extract quadrilateral contours from an edge/threshold image."""
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    min_area = img_area * 0.03
    max_area = img_area * 0.98

    candidates: List[Tuple[float, np.ndarray]] = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        peri = cv2.arcLength(cnt, True)
        if peri < 1:
            continue

        # Try multiple approximation tolerances
        for eps_mult in (0.015, 0.02, 0.03, 0.04, 0.05):
            approx = cv2.approxPolyDP(cnt, eps_mult * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                pts = approx.reshape(4, 2).astype(np.float32)
                ordered = _order_points(pts)
                if _is_valid_quad(ordered, img_area):
                    candidates.append((area, ordered))
                break

        # Also try minAreaRect for contours that are close to rectangular
        if area >= min_area:
            rect = cv2.minAreaRect(cnt)
            rect_area = rect[1][0] * rect[1][1]
            if rect_area > 0 and area / rect_area > 0.65:
                box = cv2.boxPoints(rect)
                pts = box.astype(np.float32)
                ordered = _order_points(pts)
                if _is_valid_quad(ordered, img_area):
                    candidates.append((area, ordered))

    return candidates


# ---------------------------------------------------------------------- #
#  Quad validation & scoring                                               #
# ---------------------------------------------------------------------- #

def _is_valid_quad(corners: np.ndarray, img_area: int) -> bool:
    """Reject quads that are obviously wrong."""
    tl, tr, br, bl = corners

    quad_area = cv2.contourArea(corners)
    if quad_area < img_area * 0.02 or quad_area > img_area * 0.85:
        return False

    pts = [tl, tr, br, bl]
    for i in range(4):
        p0 = pts[i]
        p1 = pts[(i + 1) % 4]
        p2 = pts[(i - 1) % 4]
        v1 = p1 - p0
        v2 = p2 - p0
        cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
        angle = math.degrees(math.acos(np.clip(cos_angle, -1, 1)))
        if angle < 45 or angle > 135:
            return False

    sides = [
        np.linalg.norm(tr - tl),
        np.linalg.norm(br - tr),
        np.linalg.norm(bl - br),
        np.linalg.norm(tl - bl),
    ]
    if min(sides) < 1:
        return False
    if max(sides) / min(sides) > 6:
        return False

    return True


def _corners_near_border(corners: np.ndarray, img_w: int, img_h: int, margin_pct: float = 0.04) -> bool:
    """Check if most corners sit near the image border (likely the photo frame, not a card)."""
    mx = img_w * margin_pct
    my = img_h * margin_pct
    near_border = 0
    for pt in corners:
        x, y = pt
        if x < mx or x > img_w - mx or y < my or y > img_h - my:
            near_border += 1
    return near_border >= 3


def _edge_contrast_score(cv_img: np.ndarray, corners: np.ndarray) -> float:
    """
    Measure actual brightness contrast across quad edges.
    Sample pixels just inside and just outside each edge midpoint.
    A real card edge will have a measurable brightness jump;
    a spurious quad (photo border, wood grain) will not.
    """
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    total_diff = 0.0
    n_samples = 0

    for i in range(4):
        p1 = corners[i]
        p2 = corners[(i + 1) % 4]

        # Sample at 20%, 50%, 80% along this edge
        for t in (0.2, 0.5, 0.8):
            mid = p1 + t * (p2 - p1)
            mx_pt, my_pt = mid

            # Edge normal (perpendicular direction)
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = math.hypot(dx, dy)
            if length < 1:
                continue
            nx = -dy / length
            ny = dx / length

            # Sample 8-15 pixels inside and outside
            diffs = []
            for offset in (8, 12, 15):
                ix = int(mx_pt + nx * offset)
                iy = int(my_pt + ny * offset)
                ox = int(mx_pt - nx * offset)
                oy = int(my_pt - ny * offset)

                if 0 <= ix < w and 0 <= iy < h and 0 <= ox < w and 0 <= oy < h:
                    diffs.append(abs(int(gray[iy, ix]) - int(gray[oy, ox])))

            if diffs:
                total_diff += max(diffs)
                n_samples += 1

    if n_samples == 0:
        return 0.0
    return total_diff / n_samples


def _pick_best_quad(
    candidates: List[Tuple[float, np.ndarray]],
    cv_img: np.ndarray,
    img_w: int,
    img_h: int,
) -> Optional[np.ndarray]:
    """
    Score each candidate quad and return the best one.

    Key insight: a card in a phone photo is typically 5-50% of the frame.
    Quads that fill >70% of the frame or hug the border are almost certainly
    false positives (the photo frame itself, wood grain, etc).

    Scoring:
      - Edge contrast (is there a real brightness change at the quad boundary?)
      - Rectangularity (90-degree corners)
      - Area sweet spot (penalize too large AND too small)
      - Centrality (cards are usually centered-ish)
      - Border rejection (corners near image edge = bad)
    """
    img_area = img_w * img_h
    img_cx, img_cy = img_w / 2.0, img_h / 2.0

    best_score = -1.0
    best_quad = None
    seen = []

    for area, corners in candidates:
        is_dup = False
        for prev in seen:
            if np.max(np.abs(corners - prev)) < 15:
                is_dup = True
                break
        if is_dup:
            continue
        seen.append(corners)

        quad_area = cv2.contourArea(corners)
        area_ratio = quad_area / img_area

        if area_ratio < 0.02 or area_ratio > 0.85:
            continue

        # Hard reject: corners hugging the image border
        if _corners_near_border(corners, img_w, img_h, margin_pct=0.03):
            continue

        # Edge contrast: the most important signal
        contrast = _edge_contrast_score(cv_img, corners)
        # Normalize: 5 = faint edge, 30+ = strong edge
        contrast_score = min(contrast / 25.0, 1.0)
        if contrast < 3.0:
            continue  # No real edge at all — skip

        # Area: sweet spot is 5-50% of frame; heavily penalize >60%
        if area_ratio < 0.05:
            area_score = area_ratio / 0.05
        elif area_ratio <= 0.50:
            area_score = 1.0
        elif area_ratio <= 0.70:
            area_score = 1.0 - (area_ratio - 0.50) * 3.0
        else:
            area_score = 0.1

        # Rectangularity
        pts = [corners[0], corners[1], corners[2], corners[3]]
        angle_penalty = 0.0
        for i in range(4):
            p0 = pts[i]
            p1 = pts[(i + 1) % 4]
            p2 = pts[(i - 1) % 4]
            v1 = p1 - p0
            v2 = p2 - p0
            cos_a = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
            ang = math.degrees(math.acos(np.clip(cos_a, -1, 1)))
            angle_penalty += abs(ang - 90)
        rect_score = max(0, 1.0 - angle_penalty / 120.0)

        # Centrality
        cx = np.mean(corners[:, 0])
        cy = np.mean(corners[:, 1])
        dist = math.hypot(cx - img_cx, cy - img_cy)
        max_dist = math.hypot(img_cx, img_cy)
        center_score = 1.0 - min(dist / max_dist, 1.0)

        # Aspect ratio
        sides = [np.linalg.norm(corners[(i+1) % 4] - corners[i]) for i in range(4)]
        w_est = (sides[0] + sides[2]) / 2
        h_est = (sides[1] + sides[3]) / 2
        if min(w_est, h_est) < 1:
            continue
        ar = max(w_est, h_est) / min(w_est, h_est)
        if 1.2 <= ar <= 2.2:
            ar_score = 1.0
        elif 1.0 <= ar <= 3.0:
            ar_score = 0.6
        else:
            ar_score = 0.2

        # Weighted total — edge contrast is king
        total = (
            contrast_score * 4.0
            + rect_score * 2.0
            + area_score * 2.0
            + center_score * 1.0
            + ar_score * 1.0
        )

        if total > best_score:
            best_score = total
            best_quad = corners

    return best_quad


# ---------------------------------------------------------------------- #
#  Fallback: GrabCut foreground segmentation                               #
# ---------------------------------------------------------------------- #

def _fallback_grabcut(cv_img: np.ndarray) -> np.ndarray:
    """
    When no quad is detected, use GrabCut to find the foreground object
    and crop to its bounding rectangle.
    """
    h, w = cv_img.shape[:2]

    # Start with a rectangle that excludes the outer 10% border
    margin_x = max(int(w * 0.10), 1)
    margin_y = max(int(h * 0.10), 1)
    rect = (margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y)

    mask = np.zeros((h, w), np.uint8)
    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)

    try:
        # Downscale for speed
        work, sc = _downscale(cv_img, max_dim=512)
        wh, ww = work.shape[:2]
        work_rect = (
            max(int(rect[0] / sc), 1),
            max(int(rect[1] / sc), 1),
            max(int(rect[2] / sc), 2),
            max(int(rect[3] / sc), 2),
        )
        work_mask = np.zeros((wh, ww), np.uint8)

        cv2.grabCut(work, work_mask, work_rect, bg_model, fg_model, 5, cv2.GC_INIT_WITH_RECT)

        fg_mask = np.where((work_mask == cv2.GC_FGD) | (work_mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

        # Scale mask back up
        fg_mask_full = cv2.resize(fg_mask, (w, h), interpolation=cv2.INTER_NEAREST)

        # Find bounding rect of foreground
        coords = cv2.findNonZero(fg_mask_full)
        if coords is not None and len(coords) > 100:
            x, y, rw, rh = cv2.boundingRect(coords)
            # Add a small padding
            pad = int(min(rw, rh) * 0.02)
            x = max(0, x - pad)
            y = max(0, y - pad)
            rw = min(w - x, rw + 2 * pad)
            rh = min(h - y, rh + 2 * pad)
            return cv_img[y:y+rh, x:x+rw]
    except Exception:
        pass

    # Ultimate fallback: conservative center crop
    mx = int(w * 0.08)
    my = int(h * 0.08)
    return cv_img[my:h - my, mx:w - mx]


# ---------------------------------------------------------------------- #
#  Deskew — Hough line-based slant correction                              #
# ---------------------------------------------------------------------- #

def _deskew(cv_img: np.ndarray, max_angle: float = 15.0) -> np.ndarray:
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
    return _trim_border(rotated)


def _trim_border(cv_img: np.ndarray, threshold: int = 10) -> np.ndarray:
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
    try:
        import pytesseract
    except ImportError:
        return img

    best_img = img
    best_score = _ocr_confidence(img)

    candidates = [
        img.transpose(Image.ROTATE_270),
        img.transpose(Image.ROTATE_180),
        img.transpose(Image.ROTATE_90),
        img.transpose(Image.FLIP_LEFT_RIGHT),
        img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_180),
    ]

    for candidate in candidates:
        score = _ocr_confidence(candidate)
        if score > best_score:
            best_score = score
            best_img = candidate

    return best_img


def _ocr_confidence(img: Image.Image) -> float:
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
#  Helpers                                                                 #
# ---------------------------------------------------------------------- #

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


def _downscale(cv_img: np.ndarray, max_dim: int = 1024) -> Tuple[np.ndarray, float]:
    """Downscale for faster processing. Returns (scaled_img, scale_factor)."""
    h, w = cv_img.shape[:2]
    if max(h, w) <= max_dim:
        return cv_img, 1.0
    scale = max_dim / max(h, w)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = cv2.resize(cv_img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized, 1.0 / scale


def _pil_to_cv(img: Image.Image) -> np.ndarray:
    rgb = img.convert("RGB")
    return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)


def _cv_to_pil(cv_img: np.ndarray) -> Image.Image:
    rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)
