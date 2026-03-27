# FlipViewer — Android

Native Jetpack Compose viewer for `.flip` dual-sided image files.

## Requirements

- Android Studio Hedgehog (2023.1.1) or later
- Kotlin 1.9+
- Android API 26+ (Android 8.0 Oreo)
- Compose BOM 2024.02+

## Setup

1. Open the `native/android` directory in Android Studio
2. Sync Gradle
3. Build and run on a device or emulator

## File Association

The app registers intent filters for `.flip` files:

- **MIME type**: `application/x-flip-image`
- **File extension**: `.flip`
- Opening a `.flip` file from any file manager or share intent launches FlipViewer
- The system file picker (via `ActivityResultContracts.OpenDocument`) allows browsing for `.flip` files

## Features

- Single-file import: tap to browse or receive via intent
- Smooth 3D flip animation with spring physics
- Horizontal swipe gesture to flip between sides
- Gallery grid for multiple loaded cards
- Material 3 dark theme matching the web viewer
- Back navigation between gallery and card viewer

## Architecture

- `FlipFileParser` — reads `.flip` ZIP archives and extracts manifest + images
- `MainActivity` — handles file intents and the document picker
- `FlipViewerApp` — top-level Compose UI with navigation between landing, gallery, and viewer
- `CardViewerScreen` — 3D flip card with `animateFloatAsState` rotation + swipe gestures
