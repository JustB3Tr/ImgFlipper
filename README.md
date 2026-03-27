# `.flip` — Dual-Sided Image Format

> One file. Two sides. Any viewer.

`.flip` is an open file format that captures both sides of a physical object — a business card, ID, document, postcard, or anything with two faces — in a **single compressed file** that can be opened and flipped in any compatible viewer.

---

## How It Works

```
 ┌──────────────┐     ┌──────────────┐
 │  Front Photo  │     │  Back Photo   │
 └──────┬───────┘     └──────┬───────┘
        │                     │
        ▼                     ▼
  ┌──────────────────────────────────┐
  │   Auto-crop & perspective fix    │
  └──────────────┬───────────────────┘
                 │
                 ▼
          ┌────────────┐
          │  card.flip  │  (single file)
          └────────────┘
                 │
                 ▼
          ┌────────────┐
          │   Viewer    │  ← click/tap to flip
          └────────────┘
```

1. **Take two photos** — front and back of a card, paper, document.
2. **Run the CLI** — the tool auto-detects the object edges, crops, perspective-corrects, and merges both images into one `.flip` file.
3. **Open in any viewer** — the web viewer (or future native apps) lets you flip between front and back with a smooth animation.

## Quick Start

### Install

```bash
pip install -e .
```

### Create a `.flip` File

```bash
flip create --front photo_front.jpg --back photo_back.jpg -o my_card.flip --label "Business Card"
```

Options:
- `--no-crop` — skip auto-crop (if images are already cropped)
- `--quality 90` — WebP quality (default: 85)
- `--label "..."` — human-readable label stored in metadata

### Inspect a `.flip` File

```bash
flip info my_card.flip
```

### Extract Contents

```bash
flip extract my_card.flip --outdir ./extracted
```

### View in Browser

Open `viewer/index.html` in any browser and drop a `.flip` file onto it.

## File Format

A `.flip` file is a ZIP archive containing:

```
my_card.flip
├── manifest.json     # Metadata (format version, dimensions, crop info)
├── front.webp        # Front-side image (WebP)
├── back.webp         # Back-side image (WebP)
└── thumbnail.webp    # 256px-wide thumbnail (optional)
```

See [spec/FLIP_FORMAT_SPEC.md](spec/FLIP_FORMAT_SPEC.md) for the full specification.

## Auto-Crop Pipeline

The auto-crop module uses OpenCV to:

1. Convert to grayscale + Gaussian blur
2. Canny edge detection
3. Find the largest quadrilateral contour (the card/paper)
4. Approximate corners and apply perspective warp
5. Output a flat, rectangular crop
6. Match dimensions across front and back

If no clear rectangle is detected, a conservative center-crop fallback is used.

## Project Structure

```
.
├── src/flipformat/
│   ├── __init__.py       # Package entry
│   ├── flip_file.py      # Core FlipFile read/write class
│   ├── autocrop.py       # OpenCV auto-crop + perspective correction
│   └── cli.py            # CLI (flip create / info / extract)
├── viewer/
│   └── index.html        # Browser-based .flip viewer with flip animation
├── spec/
│   └── FLIP_FORMAT_SPEC.md  # Formal format specification
├── tests/
│   └── test_flip.py      # Unit tests
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Roadmap

- [ ] Native iOS viewer (SwiftUI)
- [ ] Native Android viewer (Jetpack Compose)
- [ ] Windows/macOS desktop viewer (Electron or Tauri)
- [ ] OS-level file association & Quick Look / preview handlers
- [ ] Camera capture mode (guide overlay for front/back shots)
- [ ] Batch processing (scan a stack of cards)
- [ ] OCR metadata extraction (read text from the card)
- [ ] IANA MIME type registration (`application/flip`)

## License

MIT
