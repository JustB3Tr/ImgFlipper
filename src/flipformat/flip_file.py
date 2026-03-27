"""
Core FlipFile class for reading and writing .flip archives.
"""

import io
import json
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

FORMAT_NAME = "flip"
FORMAT_VERSION = "1.0"
GENERATOR = f"flipformat-py/{FORMAT_VERSION}"

THUMBNAIL_WIDTH = 256
WEBP_QUALITY = 85


class FlipFile:
    """
    Represents a .flip dual-sided image archive.

    Usage — creating:
        ff = FlipFile()
        ff.set_front(pil_image_or_path)
        ff.set_back(pil_image_or_path)
        ff.label = "Business Card"
        ff.save("card.flip")

    Usage — reading:
        ff = FlipFile.open("card.flip")
        front_img = ff.front   # PIL Image
        back_img  = ff.back    # PIL Image
        print(ff.manifest)
    """

    def __init__(self):
        self._front: Optional[Image.Image] = None
        self._back: Optional[Image.Image] = None
        self._front_hash: Optional[str] = None
        self._back_hash: Optional[str] = None
        self.label: str = ""
        self.crop_method: str = "none"
        self.crop_algorithm: str = ""
        self._created: Optional[str] = None

    # ------------------------------------------------------------------ #
    #  Public properties                                                   #
    # ------------------------------------------------------------------ #

    @property
    def front(self) -> Optional[Image.Image]:
        return self._front

    @property
    def back(self) -> Optional[Image.Image]:
        return self._back

    # ------------------------------------------------------------------ #
    #  Setters                                                             #
    # ------------------------------------------------------------------ #

    def set_front(self, src) -> None:
        """Accept a PIL Image, file path, or bytes."""
        self._front, self._front_hash = self._load_image(src)

    def set_back(self, src) -> None:
        self._back, self._back_hash = self._load_image(src)

    # ------------------------------------------------------------------ #
    #  Save                                                                #
    # ------------------------------------------------------------------ #

    def save(self, path: str, quality: int = WEBP_QUALITY) -> None:
        """Write a .flip archive to *path*."""
        if self._front is None or self._back is None:
            raise ValueError("Both front and back images must be set before saving.")

        front_bytes = self._encode_webp(self._front, quality)
        back_bytes = self._encode_webp(self._back, quality)
        thumb_img = self._make_thumbnail(self._front)
        thumb_bytes = self._encode_webp(thumb_img, quality=70)

        manifest = self._build_manifest(thumb_img)

        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2),
                        compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("front.webp", front_bytes,
                        compress_type=zipfile.ZIP_STORED)
            zf.writestr("back.webp", back_bytes,
                        compress_type=zipfile.ZIP_STORED)
            zf.writestr("thumbnail.webp", thumb_bytes,
                        compress_type=zipfile.ZIP_STORED)

    # ------------------------------------------------------------------ #
    #  Open (class method)                                                 #
    # ------------------------------------------------------------------ #

    @classmethod
    def open(cls, path: str) -> "FlipFile":
        """Read an existing .flip file and return a FlipFile instance."""
        ff = cls()
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                raise ValueError("Not a valid .flip file: missing manifest.json")

            manifest = json.loads(zf.read("manifest.json"))
            if manifest.get("format") != FORMAT_NAME:
                raise ValueError(f"Unknown format: {manifest.get('format')}")

            front_file = manifest["images"]["front"]["file"]
            back_file = manifest["images"]["back"]["file"]

            ff._front = Image.open(io.BytesIO(zf.read(front_file)))
            ff._back = Image.open(io.BytesIO(zf.read(back_file)))
            ff.label = manifest.get("object", {}).get("label", "")
            ff.crop_method = manifest.get("crop", {}).get("method", "none")
            ff.crop_algorithm = manifest.get("crop", {}).get("algorithm", "")
            ff._created = manifest.get("created")
            ff.manifest = manifest

        return ff

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_image(src) -> Tuple[Image.Image, str]:
        """Load from path/bytes/Image and return (Image, sha256_hex)."""
        if isinstance(src, Image.Image):
            raw_bytes = _image_to_bytes(src)
            return src.copy(), hashlib.sha256(raw_bytes).hexdigest()

        if isinstance(src, (str, Path)):
            from flipformat.image_io import open_image
            raw_bytes = Path(src).read_bytes()
            img = open_image(raw_bytes)
            img = _apply_exif_orientation(img)
            return img, hashlib.sha256(raw_bytes).hexdigest()

        if isinstance(src, bytes):
            from flipformat.image_io import open_image
            img = open_image(src)
            img = _apply_exif_orientation(img)
            return img, hashlib.sha256(src).hexdigest()

        raise TypeError(f"Unsupported source type: {type(src)}")

    @staticmethod
    def _encode_webp(img: Image.Image, quality: int = WEBP_QUALITY) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality)
        return buf.getvalue()

    @staticmethod
    def _make_thumbnail(img: Image.Image) -> Image.Image:
        ratio = THUMBNAIL_WIDTH / img.width
        new_h = int(img.height * ratio)
        return img.resize((THUMBNAIL_WIDTH, new_h), Image.LANCZOS)

    def _build_manifest(self, thumb_img: Image.Image) -> dict:
        now = self._created or datetime.now(timezone.utc).isoformat()
        return {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "created": now,
            "generator": GENERATOR,
            "object": {
                "label": self.label,
            },
            "images": {
                "front": {
                    "file": "front.webp",
                    "width": self._front.width,
                    "height": self._front.height,
                    "original_hash_sha256": self._front_hash or "",
                },
                "back": {
                    "file": "back.webp",
                    "width": self._back.width,
                    "height": self._back.height,
                    "original_hash_sha256": self._back_hash or "",
                },
            },
            "crop": {
                "method": self.crop_method,
                "algorithm": self.crop_algorithm,
            },
            "thumbnail": {
                "file": "thumbnail.webp",
                "width": thumb_img.width,
                "height": thumb_img.height,
            },
        }


# ---------------------------------------------------------------------- #
#  Module-level helpers                                                    #
# ---------------------------------------------------------------------- #

def _image_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _apply_exif_orientation(img: Image.Image) -> Image.Image:
    """Rotate/flip according to EXIF orientation tag, then strip it."""
    from PIL import ExifTags

    try:
        exif = img._getexif()
        if exif is None:
            return img
        orientation_key = next(
            k for k, v in ExifTags.TAGS.items() if v == "Orientation"
        )
        orientation = exif.get(orientation_key)
        if orientation is None:
            return img

        ops = {
            2: (Image.FLIP_LEFT_RIGHT,),
            3: (Image.ROTATE_180,),
            4: (Image.FLIP_TOP_BOTTOM,),
            5: (Image.TRANSPOSE,),
            6: (Image.ROTATE_270,),
            7: (Image.TRANSVERSE,),
            8: (Image.ROTATE_90,),
        }
        for op in ops.get(orientation, ()):
            img = img.transpose(op)
    except Exception:
        pass
    return img
