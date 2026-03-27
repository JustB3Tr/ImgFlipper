"""
Tests for the flipformat library.
"""

import json
import os
import tempfile
import zipfile

import numpy as np
from PIL import Image

from flipformat.flip_file import FlipFile, FORMAT_NAME, FORMAT_VERSION
from flipformat.autocrop import autocrop, _detect_quad, _pil_to_cv, _order_points


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
        cropped = autocrop(img)

        assert cropped.width < 640
        assert cropped.height < 480
        assert cropped.width >= 280
        assert cropped.height >= 160

    def test_crop_with_target_size(self):
        img = _make_card_on_background()
        cropped = autocrop(img, target_size=(200, 120))
        assert cropped.size == (200, 120)

    def test_fallback_on_no_contour(self):
        """A uniform image should trigger the fallback center-crop."""
        uniform = _make_test_image(500, 500, (128, 128, 128))
        cropped = autocrop(uniform)
        assert cropped.width < 500
        assert cropped.height < 500

    def test_order_points(self):
        pts = np.array([[100, 200], [100, 10], [300, 10], [300, 200]], dtype=np.float32)
        ordered = _order_points(pts)
        assert ordered[0][1] < ordered[3][1]  # top-left y < bottom-left y
        assert ordered[0][0] < ordered[1][0]  # top-left x < top-right x
