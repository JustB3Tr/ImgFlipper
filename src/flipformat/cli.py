"""
Command-line interface for flipformat.

Can be invoked two ways:
    flip <command>                  (if Scripts/ is on PATH)
    python -m flipformat <command>  (always works)

Usage:
    flip create  --front photo_front.jpg --back photo_back.jpg -o card.flip
    flip info     card.flip
    flip extract  card.flip --outdir ./out
"""

import argparse
import json
import os
import sys

from flipformat.flip_file import FlipFile
from flipformat.autocrop import autocrop_pair, ALGORITHM_ID


def cmd_create(args):
    ff = FlipFile()

    from PIL import Image
    front_img = Image.open(args.front)
    back_img = Image.open(args.back)

    if not args.no_crop:
        print("Auto-cropping images...")
        if not args.no_deskew:
            print("  Deskew correction enabled")
        if not args.no_ocr:
            print("  OCR orientation fix enabled")
        front_img, back_img = autocrop_pair(
            front_img, back_img,
            deskew=not args.no_deskew,
            fix_orientation=not args.no_ocr,
        )
        ff.crop_method = "auto"
        ff.crop_algorithm = ALGORITHM_ID
    else:
        w = max(front_img.width, back_img.width)
        h = max(front_img.height, back_img.height)
        front_img = front_img.resize((w, h))
        back_img = back_img.resize((w, h))
        ff.crop_method = "none"

    ff.set_front(front_img)
    ff.set_back(back_img)
    ff.label = args.label or ""

    quality = args.quality if args.quality else 85
    ff.save(args.output, quality=quality)

    size_kb = os.path.getsize(args.output) / 1024
    print(f"Created {args.output}  ({size_kb:.1f} KB)")
    print(f"  Front: {front_img.width}x{front_img.height}")
    print(f"  Back:  {back_img.width}x{back_img.height}")


def cmd_info(args):
    ff = FlipFile.open(args.file)
    print(json.dumps(ff.manifest, indent=2))


def cmd_extract(args):
    import zipfile

    outdir = args.outdir or "."
    os.makedirs(outdir, exist_ok=True)

    with zipfile.ZipFile(args.file, "r") as zf:
        zf.extractall(outdir)

    print(f"Extracted contents of {args.file} to {outdir}/")


def main():
    parser = argparse.ArgumentParser(
        prog="flip",
        description="Create and inspect .flip dual-sided image files.\n\n"
                    "If 'flip' is not recognized, use:  python -m flipformat <command>",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="Create a .flip file from two images")
    p_create.add_argument("--front", "-f", required=True, help="Front-side image path")
    p_create.add_argument("--back", "-b", required=True, help="Back-side image path")
    p_create.add_argument("--output", "-o", default="output.flip", help="Output .flip path")
    p_create.add_argument("--label", "-l", default="", help="Label for the object")
    p_create.add_argument("--no-crop", action="store_true", help="Skip auto-crop")
    p_create.add_argument("--no-deskew", action="store_true", help="Skip slant/deskew correction")
    p_create.add_argument("--no-ocr", action="store_true", help="Skip OCR-based orientation fix")
    p_create.add_argument("--quality", "-q", type=int, default=85, help="WebP quality (1-100)")

    p_info = sub.add_parser("info", help="Show manifest info from a .flip file")
    p_info.add_argument("file", help="Path to .flip file")

    p_extract = sub.add_parser("extract", help="Extract .flip contents to a directory")
    p_extract.add_argument("file", help="Path to .flip file")
    p_extract.add_argument("--outdir", "-d", default=".", help="Output directory")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "create": cmd_create,
        "info": cmd_info,
        "extract": cmd_extract,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
