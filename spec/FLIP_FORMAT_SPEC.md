# `.flip` File Format Specification — Version 1.0

## Overview

The `.flip` format encodes two images (front and back) of a physical object — such as a card, document, or sheet of paper — into a single, portable, compressed file. It is designed to be opened by any compatible viewer on any platform (iOS, Android, Windows, macOS, Linux, Web) and present the user with an interactive "flip" experience.

## Design Goals

1. **Single file** — one `.flip` file replaces two loose image files.
2. **Portable** — based on the ZIP container, universally decompressible.
3. **Compact** — images stored as WebP (lossy or lossless) for optimal compression.
4. **Self-describing** — JSON metadata embedded inside the archive.
5. **Extensible** — forward-compatible through versioned metadata.
6. **Viewer-friendly** — simple enough that a viewer can be implemented in <500 lines on any platform.

## File Structure

A `.flip` file is a **ZIP archive** (deflate) with the following internal layout:

```
my_card.flip
├── manifest.json        # Required — format metadata
├── front.webp           # Required — front-side image
├── back.webp            # Required — back-side image
└── thumbnail.webp       # Optional — 256px-wide preview thumbnail (front side)
```

### `manifest.json`

```json
{
  "format": "flip",
  "version": "1.0",
  "created": "2026-03-27T16:30:00Z",
  "generator": "flipformat-py/1.0",
  "object": {
    "label": "Business Card",
    "aspect_ratio": [3.5, 2.0],
    "unit": "in"
  },
  "images": {
    "front": {
      "file": "front.webp",
      "width": 1800,
      "height": 1024,
      "original_hash_sha256": "abcdef..."
    },
    "back": {
      "file": "back.webp",
      "width": 1800,
      "height": 1024,
      "original_hash_sha256": "123456..."
    }
  },
  "crop": {
    "method": "auto",
    "algorithm": "contour_detection_v1"
  },
  "thumbnail": {
    "file": "thumbnail.webp",
    "width": 256,
    "height": 146
  }
}
```

### Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `format` | string | Yes | Always `"flip"` |
| `version` | string | Yes | Semver format version, currently `"1.0"` |
| `created` | string | Yes | ISO 8601 timestamp |
| `generator` | string | Yes | Software that created the file |
| `object.label` | string | No | Human-readable label |
| `object.aspect_ratio` | [w, h] | No | Physical aspect ratio |
| `object.unit` | string | No | Unit of measurement (in, mm, cm) |
| `images.front.file` | string | Yes | Filename within archive |
| `images.front.width` | int | Yes | Pixel width |
| `images.front.height` | int | Yes | Pixel height |
| `images.front.original_hash_sha256` | string | No | SHA-256 of original uncropped source |
| `images.back.*` | — | Yes | Same schema as front |
| `crop.method` | string | No | `"auto"`, `"manual"`, or `"none"` |
| `crop.algorithm` | string | No | Algorithm identifier |
| `thumbnail.file` | string | No | Filename of thumbnail |
| `thumbnail.width` | int | No | Thumbnail pixel width |
| `thumbnail.height` | int | No | Thumbnail pixel height |

## Image Requirements

- **Codec**: WebP (lossy or lossless). Fallback: JPEG or PNG accepted for v1.0 compatibility, but WebP is the canonical format.
- **Dimensions**: Front and back images SHOULD have identical dimensions after cropping and alignment.
- **Orientation**: Images MUST be stored in upright orientation (no EXIF rotation).

## MIME Type

```
application/x-flip-image
```

Proposed registered type (future): `application/flip`

## File Extension

`.flip`

## Compression

The ZIP container uses DEFLATE. Since WebP is already compressed, images are stored with `ZIP_STORED` (no additional compression). The `manifest.json` uses `ZIP_DEFLATED`.

## Versioning

Viewers MUST check the `version` field. If the major version exceeds what the viewer supports, it SHOULD warn the user. Minor version bumps are backward-compatible.

## Security

- Viewers MUST NOT extract files outside the archive (zip-slip protection).
- Viewers SHOULD enforce a maximum decompressed size (e.g., 200 MB).
- Filenames within the archive MUST NOT contain path separators.
