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
  │  + auto-label + size detection  │
  └──────────────┬───────────────────┘
                 │
                 ▼
          ┌────────────┐
          │  card.flip  │  (single file)
          └────────────┘
                 │
    ┌────────┬───┼───┬────────┐
    ▼        ▼   ▼   ▼        ▼
 ┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐
 │ Web  ││Capture││ iOS  ││Droid ││ Desk │
 │Viewer││ Mode  ││ App  ││ App  ││ App  │
 └──────┘└──────┘└──────┘└──────┘└──────┘
```

## Quick Start

### Install

```bash
pip install -e .
```

### Create a `.flip` File

```bash
python run.py create --front photo_front.jpg --back photo_back.jpg -o my_card.flip
```

The tool automatically: crops the card from the background, straightens any slant, fixes text orientation, picks a label from the card text, and detects the object type and size.

> **Windows:** Use `python run.py` instead of `flip`. See [Troubleshooting](#troubleshooting).

### Batch Process a Folder

```bash
python run.py batch ./photos/ -o ./flip_files/
```

Pairs images by `_front`/`_back` naming (e.g. `card1_front.jpg` + `card1_back.jpg`) or processes every two files as a pair.

### View in Browser

Open `viewer/index.html` — drop a `.flip` file onto it.

### Capture Mode

Open `viewer/capture.html` on your phone — guided camera flow to photograph front and back, produces a `.flip` file entirely in-browser.

## CLI Reference

| Command | Description |
|---|---|
| `python run.py create -f front.jpg -b back.jpg -o card.flip` | Create from two images |
| `python run.py batch ./dir/ -o ./out/` | Batch process a directory of pairs |
| `python run.py info card.flip` | Show manifest metadata |
| `python run.py extract card.flip -d ./out` | Extract archive contents |

### Create Options

| Flag | Description |
|---|---|
| `--label "..."` | Manual label (otherwise auto-detected from OCR) |
| `--no-crop` | Skip auto-crop |
| `--no-deskew` | Skip slant correction |
| `--no-ocr` | Skip OCR orientation fix |
| `--quality 90` | WebP quality (default: 85) |

## Viewers

### Web Viewer + Capture (`viewer/`)

- **Viewer** (`index.html`): Drag-and-drop, 3D flip, gallery, metadata badges, keyboard/touch/swipe
- **Capture** (`capture.html`): Camera UI with guide overlay, front/back flow, in-browser `.flip` creation
- **PWA**: Installable as an app, works offline, registers `.flip` file handler
- Single HTML files, no build step

### iOS App (`native/ios/`)

SwiftUI app with spring-physics flip animation, drag gesture, gallery, metadata badges, `.flip` UTI registration. See [`native/ios/README.md`](native/ios/README.md).

### Android App (`native/android/`)

Jetpack Compose with Material 3, 3D flip animation, swipe gesture, gallery, metadata badges, intent filters for `.flip` files. See [`native/android/README.md`](native/android/README.md).

### Desktop App (`native/desktop/`)

Tauri wrapper (Rust) — wraps the web viewer in a native window. ~5 MB binary, `.flip` file association on Windows/macOS. See [`native/desktop/README.md`](native/desktop/README.md).

## Smart Metadata

When creating a `.flip` file, the CLI automatically:

- **Auto-labels** from OCR — reads the card text and picks the most prominent line (name, title, company)
- **Detects object type** — Card, Document, Receipt, Postcard, Photo
- **Estimates physical size** — matches aspect ratio against standard sizes:

| Detected | Size (inches) |
|---|---|
| Credit/ID Card | 3.375 x 2.125 |
| Business Card | 3.5 x 2.0 |
| Passport | 4.92 x 3.47 |
| US Letter | 11.0 x 8.5 |
| A4 | 11.69 x 8.27 |
| Receipt | 3.15 x 8.0 |
| Postcard | 5.83 x 4.13 |

All metadata is stored in the manifest and displayed in the viewer UI.

## Processing Pipeline

1. **GrabCut segmentation** — primary detection, models card vs table color distribution
2. **Mask refinement** — tightens GrabCut mask using brightness thresholding
3. **Contour fallback** — multi-strategy edge detection (Canny, CLAHE, adaptive threshold, per-channel, Otsu, Laplacian)
4. **Quad validation** — angle checks, aspect ratio bounds, border rejection, edge-contrast verification
5. **Perspective warp** — flatten to rectangle
6. **Deskew** — Hough line transform residual rotation correction
7. **OCR orientation** — try all rotations, pick one where text reads correctly
8. **Auto-label + size detection** — OCR text extraction + aspect ratio matching

## File Format

```
card.flip (single ZIP file)
├── manifest.json     # Metadata, label, type, size, dimensions
├── front.webp        # Front image
├── back.webp         # Back image
└── thumbnail.webp    # 256px preview
```

See [spec/FLIP_FORMAT_SPEC.md](spec/FLIP_FORMAT_SPEC.md) for the full specification.

## Project Structure

```
.
├── run.py                          # Zero-install entry point
├── src/flipformat/
│   ├── __init__.py
│   ├── __main__.py                 # python -m flipformat
│   ├── flip_file.py                # FlipFile reader/writer
│   ├── autocrop.py                 # GrabCut + contour crop pipeline
│   ├── smartmeta.py                # Auto-label, size, type detection
│   ├── image_io.py                 # HEIC/HEIF support
│   └── cli.py                      # CLI (create/batch/info/extract)
├── viewer/
│   ├── index.html                  # Web viewer (PWA)
│   ├── capture.html                # Camera capture flow
│   ├── manifest.json               # PWA manifest
│   └── sw.js                       # Service worker (offline)
├── native/
│   ├── ios/FlipViewer/             # SwiftUI iOS app
│   ├── android/app/                # Jetpack Compose Android app
│   └── desktop/                    # Tauri desktop app
├── spec/FLIP_FORMAT_SPEC.md
├── tests/test_flip.py              # 25 tests
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Troubleshooting

### `flip` not recognized / `No module named flipformat.__main__`

Use `run.py` — works on any OS without installation:

```powershell
pip install -r requirements.txt
python run.py create --front front.jpg --back back.jpg -o card.flip
```

### Tesseract not found

- **Windows:** [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki), add to PATH
- **macOS:** `brew install tesseract`
- **Linux:** `sudo apt install tesseract-ocr`

Or skip OCR: `python run.py create -f front.jpg -b back.jpg -o card.flip --no-ocr`

## License

MIT
