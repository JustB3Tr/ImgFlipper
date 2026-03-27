"""
Smart metadata extraction — auto-label, size estimation, and object type detection.

Given a cropped card/document image:
  - OCR the text and pick the most prominent line as a label
  - Estimate physical size in inches based on standard object ratios
  - Classify the object type (card, document, poster, receipt, etc.)
"""

from typing import Optional, Tuple
from PIL import Image


# Standard sizes in inches (width x height, landscape)
KNOWN_SIZES = {
    "credit_card":    (3.375, 2.125),
    "business_card":  (3.5, 2.0),
    "id_card":        (3.375, 2.125),
    "driver_license": (3.375, 2.125),
    "passport":       (4.921, 3.465),
    "us_letter":      (11.0, 8.5),
    "a4":             (11.693, 8.268),
    "a5":             (8.268, 5.827),
    "receipt":        (3.15, 8.0),
    "photo_4x6":      (6.0, 4.0),
    "postcard":       (5.83, 4.13),
}

TYPE_LABELS = {
    "credit_card":    "Card",
    "business_card":  "Card",
    "id_card":        "Card",
    "driver_license": "Card",
    "passport":       "Document",
    "us_letter":      "Document",
    "a4":             "Document",
    "a5":             "Document",
    "receipt":        "Receipt",
    "photo_4x6":      "Photo",
    "postcard":       "Postcard",
}


def auto_label(img: Image.Image) -> str:
    """
    OCR the image and return a short, meaningful label.
    Picks the most prominent text (longest high-confidence line,
    preferring lines that look like names, titles, or company names).
    """
    try:
        import pytesseract
    except ImportError:
        return ""

    try:
        data = pytesseract.image_to_data(
            img, output_type=pytesseract.Output.DICT, timeout=8
        )
    except Exception:
        return ""

    # Group words into lines by block_num + line_num
    lines = {}
    for i, text in enumerate(data.get("text", [])):
        try:
            conf = int(data["conf"][i])
        except (ValueError, TypeError):
            continue
        if conf < 50 or not str(text).strip():
            continue

        key = (data["block_num"][i], data["line_num"][i])
        if key not in lines:
            lines[key] = {"words": [], "confs": [], "top": data["top"][i], "height": data["height"][i]}
        lines[key]["words"].append(str(text).strip())
        lines[key]["confs"].append(conf)

    if not lines:
        return ""

    # Score each line: prefer short-ish lines with high confidence and large font
    candidates = []
    for key, info in lines.items():
        line_text = " ".join(info["words"])
        if len(line_text) < 2 or len(line_text) > 80:
            continue
        avg_conf = sum(info["confs"]) / len(info["confs"])
        font_size = info["height"]

        # Prefer lines near the top (often titles/names)
        top_bonus = max(0, 1.0 - info["top"] / 500.0)

        # Prefer lines that are 2-6 words (names, titles)
        word_count = len(info["words"])
        length_score = 1.0 if 2 <= word_count <= 6 else 0.6

        score = avg_conf * font_size * top_bonus * length_score
        candidates.append((score, line_text))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def estimate_size_and_type(
    width_px: int, height_px: int
) -> Tuple[Optional[Tuple[float, float]], str, str]:
    """
    Given pixel dimensions of a cropped object, estimate:
      - Physical size in inches (w, h)
      - Specific size name (e.g. "credit_card", "us_letter")
      - General type label (e.g. "Card", "Document")

    Uses aspect ratio matching against known standard sizes.
    Returns (size_inches, size_name, type_label).
    """
    if width_px < 1 or height_px < 1:
        return None, "unknown", "Unknown"

    # Normalize to landscape
    w = max(width_px, height_px)
    h = min(width_px, height_px)
    ar = w / h

    best_match = None
    best_diff = float("inf")

    for name, (sw, sh) in KNOWN_SIZES.items():
        std_ar = max(sw, sh) / min(sw, sh)
        diff = abs(ar - std_ar)
        if diff < best_diff:
            best_diff = diff
            best_match = name

    # Only confident if aspect ratio is within 15%
    if best_diff < 0.25 and best_match:
        size = KNOWN_SIZES[best_match]
        # Return in the same orientation as the input
        if width_px >= height_px:
            size_out = (max(size), min(size))
        else:
            size_out = (min(size), max(size))
        return size_out, best_match, TYPE_LABELS.get(best_match, "Unknown")

    # Fallback heuristic based on aspect ratio
    if ar < 1.3:
        return None, "square", "Card"
    elif ar < 2.0:
        return None, "card_like", "Card"
    elif ar < 3.5:
        return None, "document_like", "Document"
    else:
        return None, "receipt_like", "Receipt"
