# FlipViewer — iOS

Native SwiftUI viewer for `.flip` dual-sided image files.

## Requirements

- Xcode 15+
- iOS 17+ / iPadOS 17+
- Swift 5.9+

## Dependencies

- [ZIPFoundation](https://github.com/weichsel/ZIPFoundation) — ZIP archive handling  
  Add via Swift Package Manager: `https://github.com/weichsel/ZIPFoundation.git`

## Setup

1. Open the project in Xcode
2. Add the ZIPFoundation package dependency
3. Build and run on a device or simulator

## File Association

The app registers `com.flipformat.flip-image` as a custom UTI with the `.flip` extension. Once installed:

- `.flip` files in the Files app will show the FlipViewer icon
- Tapping a `.flip` file opens it directly in FlipViewer
- AirDrop / share sheet support works automatically
- The document browser is supported via `UISupportsDocumentBrowser`

## Features

- Single-file import: tap or drag a `.flip` file to open
- 3D flip animation with spring physics
- Swipe gesture to flip between front and back
- Gallery view for multiple loaded cards
- Dark mode UI matching the web viewer aesthetic
