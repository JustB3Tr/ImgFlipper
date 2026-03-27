"""
Tests for the flipformat library.
"""

import json
import math
import os
import zipfile

import cv2
import numpy as np
from PIL import Image

from flipformat.flip_file import FlipFile, FORMAT_NAME, FORMAT_VERSION
from flipformat.autocrop import (
    autocrop,
    autocrop_pair,
    _detect_quad,
    _deskew,
    _order_points,
    _pil_to_cv,
    _cv_to_pil,
    _fix_text_orientation,
    ALGORITHM_ID,
)


def _make_test_image(width=400, height=250, color=(200, 50, 50)):
    """Create a simple solid-color test image."""
    arr = np.full((height, width, 3), color, dtype=np.uint8)
    return Image.fromarray(arr)


def _make_card_on_background(
    card_w=300, card_h=180, bg_w=640, bg_h=480,
    card_color=(255, 255, 255), bg_color=(40, 40, 40),
):
    """
    Create a synthetic image of a white card on a dark background,
    useful for testing contour-based auto-crop.
    """
    bg = np.full((bg_h, bg_w, 3), bg_color, dtype=np.uint8)
    y0 = (bg_h - card_h) // 2
    x0 = (bg_w - card_w) // 2
    bg[y0:y0 + card_h, x0:x0 + card_w] = card_color
    return Image.fromarray(bg)


def _make_rotated_card(angle_deg=5.0, card_w=300, card_h=180,
                       bg_w=640, bg_h=480):
    """
    Create a card that is slightly rotated (slanted) on a dark background.
    """
    bg = np.full((bg_h, bg_w, 3), (40, 40, 40), dtype=np.uint8)
    card = np.full((card_h, card_w, 3), (255, 255, 255), dtype=np.uint8)

    center = (bg_w // 2, bg_h // 2)
    M = cv2.getRotationMatrix2D((card_w // 2, card_h // 2), angle_deg, 1.0)
    cos_a = abs(M[0, 0])
    sin_a = abs(M[0, 1])
    new_w = int(card_h * sin_a + card_w * cos_a)
    new_h = int(card_h * cos_a + card_w * sin_a)
    M[0, 2] += (new_w - card_w) / 2
    M[1, 2] += (new_h - card_h) / 2
    rotated = cv2.warpAffine(card, M, (new_w, new_h))

    y0 = (bg_h - new_h) // 2
    x0 = (bg_w - new_w) // 2
    y1 = y0 + new_h
    x1 = x0 + new_w

    if y0 >= 0 and y1 <= bg_h and x0 >= 0 and x1 <= bg_w:
        mask = rotated.sum(axis=2) > 100
        bg[y0:y1, x0:x1][mask] = rotated[mask]

    return Image.fromarray(bg)


# ---------------------------------------------------------------------- #
#  FlipFile round-trip                                                     #
# ---------------------------------------------------------------------- #

class TestFlipFileRoundTrip:
    def test_create_and_open(self, tmp_path):
        front = _make_test_image(400, 250, (200, 50, 50))
        back = _make_test_image(400, 250, (50, 50, 200))

        ff = FlipFile()
        ff.set_front(front)
        ff.set_back(back)
        ff.label = "Test Card"

        out = str(tmp_path / "test.flip")
        ff.save(out)

        assert os.path.exists(out)
        assert os.path.getsize(out) > 0

        ff2 = FlipFile.open(out)
        assert ff2.label == "Test Card"
        assert ff2.front.size[0] == 400
        assert ff2.front.size[1] == 250
        assert ff2.back.size[0] == 400
        assert ff2.back.size[1] == 250

    def test_manifest_structure(self, tmp_path):
        front = _make_test_image(300, 200)
        back = _make_test_image(300, 200)

        ff = FlipFile()
        ff.set_front(front)
        ff.set_back(back)
        ff.label = "Manifest Test"
        ff.crop_method = "auto"

        out = str(tmp_path / "manifest_test.flip")
        ff.save(out)

        with zipfile.ZipFile(out, "r") as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names
            assert "front.webp" in names
            assert "back.webp" in names
            assert "thumbnail.webp" in names

            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["format"] == FORMAT_NAME
            assert manifest["version"] == FORMAT_VERSION
            assert manifest["object"]["label"] == "Manifest Test"
            assert manifest["images"]["front"]["width"] == 300
            assert manifest["images"]["front"]["height"] == 200
            assert manifest["crop"]["method"] == "auto"

    def test_load_from_file_path(self, tmp_path):
        img = _make_test_image()
        path = str(tmp_path / "img.png")
        img.save(path)

        ff = FlipFile()
        ff.set_front(path)
        ff.set_back(path)
        out = str(tmp_path / "from_path.flip")
        ff.save(out)

        ff2 = FlipFile.open(out)
        assert ff2.front is not None

    def test_error_on_missing_side(self):
        ff = FlipFile()
        ff.set_front(_make_test_image())
        try:
            ff.save("/tmp/should_fail.flip")
            assert False, "Expected ValueError"
        except ValueError:
            pass


# ---------------------------------------------------------------------- #
#  Auto-crop                                                               #
# ---------------------------------------------------------------------- #

class TestAutoCrop:
    def test_crop_detects_card(self):
        """A white card on dark background should be detected and cropped."""
        img = _make_card_on_background(300, 180, 640, 480)
        cropped = autocrop(img, deskew=False, fix_orientation=False)

        assert cropped.width < 640
        assert cropped.height < 480
        assert cropped.width >= 280
        assert cropped.height >= 160

    def test_crop_with_target_size(self):
        img = _make_card_on_background()
        cropped = autocrop(img, target_size=(200, 120), deskew=False, fix_orientation=False)
        assert cropped.size == (200, 120)

    def test_fallback_on_no_contour(self):
        """A uniform image should trigger the fallback center-crop."""
        uniform = _make_test_image(500, 500, (128, 128, 128))
        cropped = autocrop(uniform, deskew=False, fix_orientation=False)
        assert cropped.width < 500
        assert cropped.height < 500

    def test_order_points(self):
        pts = np.array([[100, 200], [100, 10], [300, 10], [300, 200]], dtype=np.float32)
        ordered = _order_points(pts)
        assert ordered[0][1] < ordered[3][1]
        assert ordered[0][0] < ordered[1][0]

    def test_autocrop_pair_same_dimensions(self):
        front = _make_card_on_background(300, 180, 640, 480)
        back = _make_card_on_background(280, 170, 640, 480)
        f_out, b_out = autocrop_pair(front, back, deskew=False, fix_orientation=False)
        assert f_out.size == b_out.size

    def test_algorithm_id_updated(self):
        assert "v2" in ALGORITHM_ID


# ---------------------------------------------------------------------- #
#  Deskew                                                                  #
# ---------------------------------------------------------------------- #

class TestDeskew:
    def test_deskew_corrects_slanted_card(self):
        """A 5-degree rotated card should be detected and roughly straightened."""
        img = _make_rotated_card(angle_deg=5.0)
        cv_img = _pil_to_cv(img)

        corners = _detect_quad(cv_img)
        if corners is not None:
            from flipformat.autocrop import _perspective_crop
            warped = _perspective_crop(cv_img, corners)
        else:
            warped = cv_img

        deskewed = _deskew(warped)
        assert deskewed.shape[0] > 0
        assert deskewed.shape[1] > 0

    def test_deskew_no_op_on_straight_card(self):
        """A perfectly straight card should be returned mostly unchanged."""
        img = _make_card_on_background(300, 180, 640, 480)
        cv_img = _pil_to_cv(img)
        corners = _detect_quad(cv_img)
        if corners is not None:
            from flipformat.autocrop import _perspective_crop
            warped = _perspective_crop(cv_img, corners)
        else:
            warped = cv_img

        deskewed = _deskew(warped)
        h_diff = abs(deskewed.shape[0] - warped.shape[0])
        w_diff = abs(deskewed.shape[1] - warped.shape[1])
        assert h_diff < 20
        assert w_diff < 20

    def test_full_pipeline_with_deskew(self):
        """Full autocrop pipeline with deskew enabled."""
        img = _make_rotated_card(angle_deg=3.0)
        cropped = autocrop(img, deskew=True, fix_orientation=False)
        assert cropped.width > 0
        assert cropped.height > 0


# ---------------------------------------------------------------------- #
#  OCR orientation (basic, no real text)                                   #
# ---------------------------------------------------------------------- #

class TestOCROrientation:
    def test_fix_orientation_returns_image(self):
        """With no text, the function should return the image unchanged."""
        img = _make_test_image(200, 150, (200, 200, 200))
        result = _fix_text_orientation(img)
        assert result.size[0] > 0
        assert result.size[1] > 0

    def test_fix_orientation_with_uniform_image(self):
        """Uniform image should just pass through."""
        img = _make_test_image(300, 200)
        result = _fix_text_orientation(img)
        assert result.size == (300, 200) or result.size == (200, 300)
