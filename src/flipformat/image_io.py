"""
Centralized image loading with HEIC/HEIF support.

Pillow does not natively read HEIC (Apple's default photo format).
This module registers the pillow-heif plugin on first use so that
Image.open() transparently handles .heic and .heif files everywhere.
"""

import io
from pathlib import Path
from PIL import Image

_heif_registered = False


def _ensure_heif_support():
    """Register pillow-heif if available. Safe to call multiple times."""
    global _heif_registered
    if _heif_registered:
        return
    _heif_registered = True
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass


def open_image(src) -> Image.Image:
    """
    Open an image from a file path, bytes, or file-like object.
    Supports JPEG, PNG, WebP, TIFF, BMP, and HEIC/HEIF.
    """
    _ensure_heif_support()

    if isinstance(src, (str, Path)):
        return Image.open(str(src))

    if isinstance(src, bytes):
        return Image.open(io.BytesIO(src))

    return Image.open(src)
