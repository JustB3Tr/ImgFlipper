import SwiftUI
import UniformTypeIdentifiers

// Register .flip as a custom UTI so iOS treats it as our file type
extension UTType {
    static var flipImage: UTType {
        UTType(importedAs: "com.flipformat.flip-image", conformingTo: .data)
    }
}

@main
struct FlipViewerApp: App {
    @StateObject private var store = FlipStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
                .onOpenURL { url in
                    store.loadFile(url: url)
                }
        }
    }
}
