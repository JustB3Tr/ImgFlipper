import SwiftUI
import UIKit
import ZIPFoundation

struct FlipCard: Identifiable {
    let id = UUID()
    var label: String
    var frontImage: UIImage
    var backImage: UIImage
    var width: Int
    var height: Int
    var created: String
    var objectType: String
    var sizeName: String
    var sizeInches: (Double, Double)?
}

struct FlipManifest: Codable {
    let format: String
    let version: String
    let created: String
    let generator: String
    let object: ManifestObject?
    let images: ManifestImages
    let crop: ManifestCrop?
    let thumbnail: ManifestThumbnail?

    struct ManifestObject: Codable {
        let label: String?
        let type: String?
        let size_name: String?
        let size_inches: [Double]?
    }

    struct ManifestImages: Codable {
        let front: ImageEntry
        let back: ImageEntry
    }

    struct ImageEntry: Codable {
        let file: String
        let width: Int
        let height: Int
    }

    struct ManifestCrop: Codable {
        let method: String?
        let algorithm: String?
    }

    struct ManifestThumbnail: Codable {
        let file: String?
        let width: Int?
        let height: Int?
    }
}

@MainActor
class FlipStore: ObservableObject {
    @Published var cards: [FlipCard] = []
    @Published var selectedCard: FlipCard?
    @Published var errorMessage: String?

    func loadFile(url: URL) {
        let accessing = url.startAccessingSecurityScopedResource()
        defer { if accessing { url.stopAccessingSecurityScopedResource() } }

        do {
            let card = try Self.parseFlipFile(at: url)
            cards.append(card)
            selectedCard = card
        } catch {
            errorMessage = "Could not open file: \(error.localizedDescription)"
        }
    }

    static func parseFlipFile(at url: URL) throws -> FlipCard {
        guard let archive = Archive(url: url, accessMode: .read) else {
            throw FlipError.invalidArchive
        }

        guard let manifestEntry = archive["manifest.json"] else {
            throw FlipError.missingManifest
        }

        var manifestData = Data()
        _ = try archive.extract(manifestEntry) { data in
            manifestData.append(data)
        }

        let manifest = try JSONDecoder().decode(FlipManifest.self, from: manifestData)

        guard manifest.format == "flip" else {
            throw FlipError.wrongFormat
        }

        let frontImage = try extractImage(from: archive, filename: manifest.images.front.file)
        let backImage = try extractImage(from: archive, filename: manifest.images.back.file)

        let sizeArr = manifest.object?.size_inches
        let sizeInches: (Double, Double)? = (sizeArr != nil && sizeArr!.count == 2) ? (sizeArr![0], sizeArr![1]) : nil

        return FlipCard(
            label: manifest.object?.label ?? url.deletingPathExtension().lastPathComponent,
            frontImage: frontImage,
            backImage: backImage,
            width: manifest.images.front.width,
            height: manifest.images.front.height,
            created: manifest.created,
            objectType: manifest.object?.type ?? "",
            sizeName: manifest.object?.size_name ?? "",
            sizeInches: sizeInches
        )
    }

    private static func extractImage(from archive: Archive, filename: String) throws -> UIImage {
        guard let entry = archive[filename] else {
            throw FlipError.missingImage(filename)
        }

        var imageData = Data()
        _ = try archive.extract(entry) { data in
            imageData.append(data)
        }

        guard let image = UIImage(data: imageData) else {
            throw FlipError.corruptImage(filename)
        }

        return image
    }
}

enum FlipError: LocalizedError {
    case invalidArchive
    case missingManifest
    case wrongFormat
    case missingImage(String)
    case corruptImage(String)

    var errorDescription: String? {
        switch self {
        case .invalidArchive: return "Not a valid archive."
        case .missingManifest: return "Missing manifest.json."
        case .wrongFormat: return "Not a .flip file."
        case .missingImage(let f): return "Missing image: \(f)"
        case .corruptImage(let f): return "Corrupt image: \(f)"
        }
    }
}
