"""
Auto-crop module — robust detection of cards, documents, and paper in photos.

Primary approach: GrabCut foreground segmentation with quad fitting.
Secondary: multi-strategy contour detection with edge-contrast validation.

The key insight is that contour detection fails on low-contrast scenes
(dark card on dark table, light card on light table). GrabCut models
the color distribution of foreground vs background, which works even
with subtle contrast differences.
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


ALGORITHM_ID = "grabcut_quad_v5"


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
    cv_work, scale = _downscale(cv_img, max_dim=1024)

    # Try GrabCut first (best for real photos), then contour detection
    corners = _detect_via_grabcut(cv_work)
    if corners is None:
        corners = _detect_via_contours(cv_work)

    if corners is not None:
        corners_orig = corners * scale
        cropped = _perspective_crop(cv_img, corners_orig)
    else:
        cropped = _simple_grabcut_crop(cv_img)

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

    # Fit both to the same aspect ratio without squeezing.
    # Pad the smaller one with a letterbox rather than distorting.
    fw, fh = front_cropped.size
    bw, bh = back_cropped.size
    f_ar = fw / fh
    b_ar = bw / bh

    # If aspect ratios are close enough (within 20%), just resize to match
    if abs(f_ar - b_ar) / max(f_ar, b_ar) < 0.20:
        w = max(fw, bw)
        h = max(fh, bh)
        front_out = front_cropped.resize((w, h), Image.LANCZOS)
        back_out = back_cropped.resize((w, h), Image.LANCZOS)
    else:
        # Aspect ratios differ too much — use the larger dimensions
        # and pad the other with black letterbox
        w = max(fw, bw)
        h = max(fh, bh)
        front_out = _fit_to_size(front_cropped, w, h)
        back_out = _fit_to_size(back_cropped, w, h)

    return front_out, back_out


def _fit_to_size(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize preserving aspect ratio and center on a black canvas."""
    iw, ih = img.size
    scale = min(target_w / iw, target_h / ih)
    new_w = int(iw * scale)
    new_h = int(ih * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    canvas.paste(resized, (x, y))
    return canvas


# ---------------------------------------------------------------------- #
#  Strategy 1: GrabCut-based detection                                     #
# ---------------------------------------------------------------------- #

def _detect_via_grabcut(cv_img: np.ndarray) -> Optional[np.ndarray]:
    """
    Use GrabCut to segment foreground (the card) from background (the table).
    Then refine the mask and fit a tight quadrilateral.
    """
    h, w = cv_img.shape[:2]

    work, sc = _downscale(cv_img, max_dim=512)
    wh, ww = work.shape[:2]

    margin_x = max(int(ww * 0.05), 1)
    margin_y = max(int(wh * 0.05), 1)
    rect = (margin_x, margin_y, ww - 2 * margin_x, wh - 2 * margin_y)

    mask = np.zeros((wh, ww), np.uint8)
    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(work, mask, rect, bg_model, fg_model, 8, cv2.GC_INIT_WITH_RECT)
    except Exception:
        return None

    fg_mask = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)

    # Refine: tighten the mask to the actual card boundary.
    # GrabCut often includes shadows/reflections around the card.
    fg_mask = _refine_grabcut_mask(work, fg_mask)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel, iterations=2)

    contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    mask_area = ww * wh

    if area < mask_area * 0.03:
        return None

    min_rect = cv2.minAreaRect(largest)
    box = cv2.boxPoints(min_rect)
    corners = _order_points(box.astype(np.float32))

    if not _is_valid_quad(corners, mask_area):
        return None

    corners = corners * sc
    return corners


def _refine_grabcut_mask(work: np.ndarray, fg_mask: np.ndarray) -> np.ndarray:
    """
    Tighten a GrabCut foreground mask to the actual card edges.

    GrabCut's mask is often too generous — it includes shadows, reflections,
    and gradient areas around the card. This function:
    1. Looks at the brightness distribution inside the GrabCut region
    2. If the foreground is significantly brighter or darker than background,
       applies a threshold to isolate just the card
    3. Intersects with the original mask to keep it conservative
    """
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    bg_mask = cv2.bitwise_not(fg_mask)

    fg_pixels = gray[fg_mask > 0]
    bg_pixels = gray[bg_mask > 0]

    if len(fg_pixels) < 50 or len(bg_pixels) < 50:
        return fg_mask

    fg_mean = float(np.mean(fg_pixels))
    bg_mean = float(np.mean(bg_pixels))
    diff = fg_mean - bg_mean

    # Only refine if there's a meaningful brightness difference
    if abs(diff) < 15:
        return fg_mask

    # Blur to reduce noise before thresholding
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    if diff > 0:
        # Foreground is BRIGHTER (white card on dark table)
        # Threshold to keep only bright pixels
        threshold_val = bg_mean + abs(diff) * 0.4
        _, refined = cv2.threshold(blurred, int(threshold_val), 255, cv2.THRESH_BINARY)
    else:
        # Foreground is DARKER (dark card on lighter surface)
        threshold_val = bg_mean - abs(diff) * 0.4
        _, refined = cv2.threshold(blurred, int(threshold_val), 255, cv2.THRESH_BINARY_INV)

    # Intersect with original GrabCut mask to stay conservative
    refined = cv2.bitwise_and(refined, fg_mask)

    # Check that refinement didn't destroy the mask
    refined_area = cv2.countNonZero(refined)
    original_area = cv2.countNonZero(fg_mask)

    if refined_area < original_area * 0.20:
        return fg_mask

    return refined


# ---------------------------------------------------------------------- #
#  Strategy 2: Multi-strategy contour detection                            #
# ---------------------------------------------------------------------- #

def _detect_via_contours(cv_img: np.ndarray) -> Optional[np.ndarray]:
    """Contour-based detection as secondary approach."""
    h, w = cv_img.shape[:2]
    img_area = h * w
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    all_candidates: List[Tuple[float, np.ndarray]] = []

    # Canny at multiple thresholds
    for lo, hi in [(20, 80), (40, 120), (60, 180), (80, 200)]:
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, lo, hi)
        edges = _close_edges(edges)
        all_candidates.extend(_find_quads_in_edges(edges, img_area))

    # Per-channel Canny
    for ch in cv2.split(cv_img):
        blurred_ch = cv2.GaussianBlur(ch, (5, 5), 0)
        edges = cv2.Canny(blurred_ch, 30, 100)
        edges = _close_edges(edges)
        all_candidates.extend(_find_quads_in_edges(edges, img_area))

    # CLAHE enhanced
    for clip_limit in (3.0, 6.0, 10.0):
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
        edges = cv2.Canny(blurred, 40, 120)
        edges = _close_edges(edges)
        all_candidates.extend(_find_quads_in_edges(edges, img_area))

    # Adaptive thresholding
    for block_size in (15, 31, 51):
        for C_val in (5, 10):
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, block_size, C_val,
            )
            thresh = _close_edges(thresh, kernel_size=5, iterations=2)
            all_candidates.extend(_find_quads_in_edges(thresh, img_area))
            thresh_inv = cv2.bitwise_not(thresh)
            thresh_inv = _close_edges(thresh_inv, kernel_size=5, iterations=2)
            all_candidates.extend(_find_quads_in_edges(thresh_inv, img_area))

    if not all_candidates:
        return None

    return _pick_best_quad(all_candidates, cv_img, w, h)


# ---------------------------------------------------------------------- #
#  Simple GrabCut crop (final fallback — bounding box, no quad)            #
# ---------------------------------------------------------------------- #

def _simple_grabcut_crop(cv_img: np.ndarray) -> np.ndarray:
    h, w = cv_img.shape[:2]
    work, sc = _downscale(cv_img, max_dim=512)
    wh, ww = work.shape[:2]

    margin_x = max(int(ww * 0.08), 1)
    margin_y = max(int(wh * 0.08), 1)
    rect = (margin_x, margin_y, ww - 2 * margin_x, wh - 2 * margin_y)

    mask = np.zeros((wh, ww), np.uint8)
    bg_model = np.zeros((1, 65), np.float64)
    fg_model = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(work, mask, rect, bg_model, fg_model, 5, cv2.GC_INIT_WITH_RECT)
        fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        fg_full = cv2.resize(fg, (w, h), interpolation=cv2.INTER_NEAREST)

        coords = cv2.findNonZero(fg_full)
        if coords is not None and len(coords) > 100:
            x, y, rw, rh = cv2.boundingRect(coords)
            pad = int(min(rw, rh) * 0.02)
            x = max(0, x - pad)
            y = max(0, y - pad)
            rw = min(w - x, rw + 2 * pad)
            rh = min(h - y, rh + 2 * pad)
            return cv_img[y:y+rh, x:x+rw]
    except Exception:
        pass

    mx = int(w * 0.08)
    my = int(h * 0.08)
    return cv_img[my:h - my, mx:w - mx]


# ---------------------------------------------------------------------- #
#  Contour helpers                                                         #
# ---------------------------------------------------------------------- #

def _close_edges(edges: np.ndarray, kernel_size: int = 3, iterations: int = 2) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    closed = cv2.dilate(edges, kernel, iterations=iterations)
    closed = cv2.erode(closed, kernel, iterations=max(1, iterations - 1))
    return closed


def _find_quads_in_edges(edges: np.ndarray, img_area: int) -> List[Tuple[float, np.ndarray]]:
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    min_area = img_area * 0.03
    max_area = img_area * 0.80
    candidates: List[Tuple[float, np.ndarray]] = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        peri = cv2.arcLength(cnt, True)
        if peri < 1:
            continue

        for eps in (0.015, 0.02, 0.03, 0.04, 0.05):
            approx = cv2.approxPolyDP(cnt, eps * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                pts = _order_points(approx.reshape(4, 2).astype(np.float32))
                if _is_valid_quad(pts, img_area):
                    candidates.append((area, pts))
                break

        if area >= min_area:
            rect = cv2.minAreaRect(cnt)
            rect_area = rect[1][0] * rect[1][1]
            if rect_area > 0 and area / rect_area > 0.65:
                box = cv2.boxPoints(rect)
                pts = _order_points(box.astype(np.float32))
                if _is_valid_quad(pts, img_area):
                    candidates.append((area, pts))

    return candidates


# ---------------------------------------------------------------------- #
#  Quad validation & scoring                                               #
# ---------------------------------------------------------------------- #

def _is_valid_quad(corners: np.ndarray, img_area: int) -> bool:
    quad_area = cv2.contourArea(corners)
    if quad_area < img_area * 0.02 or quad_area > img_area * 0.85:
        return False

    tl, tr, br, bl = corners
    pts = [tl, tr, br, bl]
    for i in range(4):
        p0 = pts[i]
        p1 = pts[(i + 1) % 4]
        p2 = pts[(i - 1) % 4]
        v1 = p1 - p0
        v2 = p2 - p0
        cos_a = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
        angle = math.degrees(math.acos(np.clip(cos_a, -1, 1)))
        if angle < 50 or angle > 130:
            return False

    sides = [np.linalg.norm(pts[(i+1) % 4] - pts[i]) for i in range(4)]
    if min(sides) < 1:
        return False
    if max(sides) / min(sides) > 5:
        return False

    return True


def _edge_contrast(cv_img: np.ndarray, corners: np.ndarray) -> float:
    """Measure brightness difference across quad edges."""
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    total = 0.0
    n = 0

    for i in range(4):
        p1, p2 = corners[i], corners[(i + 1) % 4]
        dx, dy = float(p2[0] - p1[0]), float(p2[1] - p1[1])
        length = math.hypot(dx, dy)
        if length < 1:
            continue
        nx, ny = -dy / length, dx / length

        for t in (0.2, 0.4, 0.6, 0.8):
            mx_pt = p1[0] + t * (p2[0] - p1[0])
            my_pt = p1[1] + t * (p2[1] - p1[1])
            best_diff = 0
            for offset in (6, 10, 15, 20):
                ix, iy = int(mx_pt + nx * offset), int(my_pt + ny * offset)
                ox, oy = int(mx_pt - nx * offset), int(my_pt - ny * offset)
                if 0 <= ix < w and 0 <= iy < h and 0 <= ox < w and 0 <= oy < h:
                    best_diff = max(best_diff, abs(int(gray[iy, ix]) - int(gray[oy, ox])))
            if best_diff > 0:
                total += best_diff
                n += 1

    return total / max(n, 1)


def _corners_near_border(corners: np.ndarray, img_w: int, img_h: int) -> bool:
    mx, my = img_w * 0.03, img_h * 0.03
    near = sum(1 for pt in corners if pt[0] < mx or pt[0] > img_w - mx or pt[1] < my or pt[1] > img_h - my)
    return near >= 3


def _pick_best_quad(
    candidates: List[Tuple[float, np.ndarray]],
    cv_img: np.ndarray,
    img_w: int,
    img_h: int,
) -> Optional[np.ndarray]:
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
        if area_ratio < 0.02 or area_ratio > 0.80:
            continue

        if _corners_near_border(corners, img_w, img_h):
            continue

        contrast = _edge_contrast(cv_img, corners)
        if contrast < 3.0:
            continue
        contrast_score = min(contrast / 20.0, 1.0)

        if area_ratio <= 0.50:
            area_score = min(area_ratio / 0.10, 1.0)
        else:
            area_score = max(0.1, 1.0 - (area_ratio - 0.50) * 4.0)

        pts = [corners[0], corners[1], corners[2], corners[3]]
        angle_penalty = sum(
            abs(math.degrees(math.acos(np.clip(
                np.dot(pts[(i+1) % 4] - pts[i], pts[(i-1) % 4] - pts[i])
                / (np.linalg.norm(pts[(i+1) % 4] - pts[i]) * np.linalg.norm(pts[(i-1) % 4] - pts[i]) + 1e-8),
                -1, 1))) - 90)
            for i in range(4)
        )
        rect_score = max(0, 1.0 - angle_penalty / 100.0)

        cx, cy = np.mean(corners[:, 0]), np.mean(corners[:, 1])
        center_score = 1.0 - min(math.hypot(cx - img_cx, cy - img_cy) / math.hypot(img_cx, img_cy), 1.0)

        total = contrast_score * 4.0 + rect_score * 2.0 + area_score * 2.0 + center_score * 1.0

        if total > best_score:
            best_score = total
            best_quad = corners

    return best_quad


# ---------------------------------------------------------------------- #
#  Deskew                                                                  #
# ---------------------------------------------------------------------- #

def _deskew(cv_img: np.ndarray, max_angle: float = 15.0) -> np.ndarray:
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=min(cv_img.shape[:2]) // 8, maxLineGap=10)
    if lines is None or len(lines) == 0:
        return cv_img

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if abs(x2 - x1) < 1:
            continue
        a = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if abs(a) < 45:
            angles.append(a)
        elif abs(a - 90) < 45:
            angles.append(a - 90)
        elif abs(a + 90) < 45:
            angles.append(a + 90)

    if not angles:
        return cv_img

    median = float(np.median(angles))
    if abs(median) < 0.3 or abs(median) > max_angle:
        return cv_img

    h, w = cv_img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), median, 1.0)
    cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin_a + w * cos_a), int(h * cos_a + w * sin_a)
    M[0, 2] += (nw - w) / 2
    M[1, 2] += (nh - h) / 2
    rotated = cv2.warpAffine(cv_img, M, (nw, nh), borderMode=cv2.BORDER_REPLICATE)
    return _trim_border(rotated)


def _trim_border(cv_img: np.ndarray, threshold: int = 10) -> np.ndarray:
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    top, bot, left, right = 0, h, 0, w

    for y in range(h // 4):
        if np.mean(gray[y, w // 4: 3 * w // 4]) > threshold:
            top = y; break
    for y in range(h - 1, 3 * h // 4, -1):
        if np.mean(gray[y, w // 4: 3 * w // 4]) > threshold:
            bot = y + 1; break
    for x in range(w // 4):
        if np.mean(gray[h // 4: 3 * h // 4, x]) > threshold:
            left = x; break
    for x in range(w - 1, 3 * w // 4, -1):
        if np.mean(gray[h // 4: 3 * h // 4, x]) > threshold:
            right = x + 1; break

    if bot > top and right > left:
        return cv_img[top:bot, left:right]
    return cv_img


# ---------------------------------------------------------------------- #
#  OCR orientation fix                                                     #
# ---------------------------------------------------------------------- #

def _fix_text_orientation(img: Image.Image) -> Image.Image:
    try:
        import pytesseract
    except ImportError:
        return img

    best_img = img
    best_score = _ocr_confidence(img)

    for candidate in [
        img.transpose(Image.ROTATE_270),
        img.transpose(Image.ROTATE_180),
        img.transpose(Image.ROTATE_90),
        img.transpose(Image.FLIP_LEFT_RIGHT),
        img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_180),
    ]:
        score = _ocr_confidence(candidate)
        if score > best_score:
            best_score = score
            best_img = candidate

    return best_img


def _ocr_confidence(img: Image.Image) -> float:
    try:
        import pytesseract
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, timeout=5)
        score = 0.0
        for conf, text in zip(data.get("conf", []), data.get("text", [])):
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
#  Geometry helpers                                                        #
# ---------------------------------------------------------------------- #

def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def _perspective_crop(cv_img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    width, height = max(width, 1), max(height, 1)
    dst = np.array([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(cv_img, M, (width, height))


def _downscale(cv_img: np.ndarray, max_dim: int = 1024) -> Tuple[np.ndarray, float]:
    h, w = cv_img.shape[:2]
    if max(h, w) <= max_dim:
        return cv_img, 1.0
    scale = max_dim / max(h, w)
    resized = cv2.resize(cv_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return resized, 1.0 / scale


def _pil_to_cv(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def _cv_to_pil(cv_img: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))
