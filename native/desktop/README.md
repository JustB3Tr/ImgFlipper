# FlipViewer — Desktop (Tauri)

Cross-platform desktop application for viewing `.flip` files on Windows and macOS.

## Requirements

- [Rust](https://rustup.rs/) (stable)
- [Node.js](https://nodejs.org/) 18+
- Platform-specific build tools:
  - **Windows:** Visual Studio Build Tools (C++ workload)
  - **macOS:** Xcode Command Line Tools

## Setup

```bash
cd native/desktop
npm install
npm run build
```

## Development

```bash
npm run dev
```

## File Association

The Tauri config registers `.flip` files with MIME type `application/x-flip-image`. After installing:

- **Windows:** Double-clicking a `.flip` file opens FlipViewer
- **macOS:** `.flip` files show the FlipViewer icon and open on double-click

## How It Works

The desktop app wraps the web viewer (`viewer/index.html`) in a native window using Tauri's WebView. It provides:

- Native window chrome with resize/minimize/maximize
- File association for `.flip` files at the OS level
- File→Open dialog via Tauri's dialog API
- Small binary (~5 MB) compared to Electron (~150 MB)
