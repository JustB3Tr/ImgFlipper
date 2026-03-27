# `.flip` — Dual-Sided Image Format

> One file. Two sides. Any viewer.

`.flip` is an open file format that captures both sides of a physical object — a business card, ID, document, postcard, or anything with two faces — in a **single compressed file** that can be opened and flipped in any compatible viewer on iOS, Android, Web, or desktop.

---

## How It Works

```
 ┌──────────────┐     ┌──────────────┐
 │  Front Photo  │     │  Back Photo   │
 └──────┬───────┘     └──────┬───────┘
        │                     │
        ▼                     ▼
  ┌──────────────────────────────────┐
  │  Auto-crop + deskew + OCR fix   │
  └──────────────┬───────────────────┘
                 │
                 ▼
          ┌────────────┐
          │  card.flip  │  (single file)
          └────────────┘
                 │
      ┌──────────┼──────────┐
      ▼          ▼          ▼
  ┌────────┐ ┌────────┐ ┌────────┐
  │  Web   │ │  iOS   │ │Android │
  │ Viewer │ │ Viewer │ │ Viewer │
  └────────┘ └────────┘ └────────┘
```

1. **Take two photos** — front and back of a card, paper, document.
2. **Run the CLI** — the tool auto-detects edges, crops, corrects perspective & slant, fixes text orientation via OCR, and merges both images into one `.flip` file.
3. **Open in any viewer** — web, iOS, or Android viewers let you flip between front and back with smooth 3D animations.

## Is `.flip` really a single file?

**Yes.** A `.flip` file appears as `card.flip` on your phone, computer, or any file manager. It is **not** a folder. The internal structure uses ZIP compression (the same technique `.docx`, `.epub`, and `.ipa` use), but to the user it's a single, self-contained file. Upload it, share it, AirDrop it — one file, both sides.

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
| Flag | Description |
|---|---|
| `--no-crop` | Skip auto-crop (if images are already cropped) |
| `--no-deskew` | Skip slant/skew correction |
| `--no-ocr` | Skip OCR-based orientation fix |
| `--quality 90` | WebP quality (default: 85) |
| `--label "..."` | Human-readable label stored in metadata |

### Inspect a `.flip` File

```bash
flip info my_card.flip
```

### Extract Contents

```bash
flip extract my_card.flip --outdir ./extracted
```

## Viewers

### Web Viewer

Open `viewer/index.html` in any browser and drop a `.flip` file onto it.

**Features:**
- Drag-and-drop or file picker
- Smooth 3D CSS flip animation
- Gallery view for multiple cards
- Touch swipe support on mobile
- Keyboard shortcuts: `Space` to flip, `Escape` to go back, `←`/`→` for navigation
- Fully responsive — works on phones, tablets, and desktops
- Single HTML file, no build step

### iOS Viewer (SwiftUI)

Located in `native/ios/`. See [`native/ios/README.md`](native/ios/README.md).

**Features:**
- Native SwiftUI with spring-physics flip animation
- Drag gesture to flip
- Gallery grid for multiple cards
- **File association**: registers `.flip` as a custom UTI — tapping any `.flip` file in Files opens FlipViewer
- Document browser support

### Android Viewer (Jetpack Compose)

Located in `native/android/`. See [`native/android/README.md`](native/android/README.md).

**Features:**
- Material 3 dark theme
- `animateFloatAsState` 3D flip with spring physics
- Horizontal swipe gesture
- Gallery grid
- **Intent filter**: opening `.flip` files from any file manager launches FlipViewer
- Supports Android 8.0+ (API 26+)

## Processing Pipeline

### Auto-Crop
1. Convert to grayscale + Gaussian blur
2. Canny edge detection
3. Find the largest quadrilateral contour (the card/paper)
4. Approximate corners and apply perspective warp
5. Output a flat, rectangular crop
6. Match dimensions across front and back

### Deskew (Slant Correction)
1. After perspective warp, run Hough line transform on edges
2. Compute median angle of detected lines
3. Rotate to correct slant (up to 15 degrees)
4. Trim rotation artifacts from borders

### OCR Orientation Fix
1. Run Tesseract OCR on the cropped image
2. Try all 4 rotations (0, 90, 180, 270) plus horizontal mirror
3. Pick the orientation that produces the most high-confidence readable text
4. Ensures text always reads correctly — no upside-down or mirrored cards

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

## Project Structure

```
.
├── src/flipformat/
│   ├── __init__.py          # Package entry
│   ├── flip_file.py         # Core FlipFile read/write class
│   ├── autocrop.py          # Auto-crop + deskew + OCR orientation fix
│   └── cli.py               # CLI (flip create / info / extract)
├── viewer/
│   └── index.html           # Web-based .flip viewer
├── native/
│   ├── ios/                 # SwiftUI iOS/iPadOS viewer
│   │   └── FlipViewer/
│   └── android/             # Jetpack Compose Android viewer
│       └── app/
├── spec/
│   └── FLIP_FORMAT_SPEC.md  # Formal format specification
├── tests/
│   └── test_flip.py         # Unit tests (15 passing)
├── pyproject.toml
├── requirements.txt
└── README.md
```

## System Requirements

**Python CLI:**
- Python 3.9+
- OpenCV (`opencv-python-headless`)
- Pillow
- pytesseract + Tesseract OCR engine

**iOS app:** Xcode 15+, iOS 17+, ZIPFoundation package

**Android app:** Android Studio, Kotlin 1.9+, API 26+, Compose BOM 2024.02+

## Roadmap

- [ ] Windows/macOS desktop viewer (Tauri)
- [ ] OS-level Quick Look / preview handlers
- [ ] Camera capture mode with guide overlay
- [ ] Batch processing (scan a stack of cards)
- [ ] OCR metadata extraction (read and store text from the card)
- [ ] IANA MIME type registration (`application/flip`)
- [ ] App Store / Play Store distribution

## License

MIT
