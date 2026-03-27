import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var store: FlipStore

    @State private var showFilePicker = false

    var body: some View {
        NavigationStack {
            Group {
                if store.cards.isEmpty {
                    LandingView(showFilePicker: $showFilePicker)
                } else if let card = store.selectedCard {
                    CardViewerView(card: card)
                } else {
                    GalleryView()
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("FlipViewer")
                        .font(.headline)
                        .fontWeight(.bold)
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        showFilePicker = true
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
        }
        .fileImporter(
            isPresented: $showFilePicker,
            allowedContentTypes: [.flipImage, .data],
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case .success(let urls):
                if let url = urls.first {
                    store.loadFile(url: url)
                }
            case .failure(let error):
                store.errorMessage = error.localizedDescription
            }
        }
        .alert("Error", isPresented: .init(
            get: { store.errorMessage != nil },
            set: { if !$0 { store.errorMessage = nil } }
        )) {
            Button("OK") { store.errorMessage = nil }
        } message: {
            Text(store.errorMessage ?? "")
        }
        .preferredColorScheme(.dark)
    }
}

// MARK: - Landing

struct LandingView: View {
    @Binding var showFilePicker: Bool

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            VStack(spacing: 12) {
                Image(systemName: "rectangle.portrait.on.rectangle.portrait.angled.fill")
                    .font(.system(size: 56))
                    .foregroundStyle(.indigo)

                Text("View any .flip file")
                    .font(.title)
                    .fontWeight(.bold)

                Text("Open a .flip file to see both sides\nof a card or document.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            Button {
                showFilePicker = true
            } label: {
                Label("Open .flip File", systemImage: "doc.badge.plus")
                    .font(.headline)
                    .frame(maxWidth: 280)
                    .padding(.vertical, 14)
            }
            .buttonStyle(.borderedProminent)
            .tint(.indigo)
            .controlSize(.large)

            Spacer()

            HStack(spacing: 6) {
                Circle()
                    .fill(.green)
                    .frame(width: 6, height: 6)
                Text("Supports .flip format v1.0+")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.bottom, 16)
        }
        .padding(.horizontal, 24)
    }
}

// MARK: - Gallery

struct GalleryView: View {
    @EnvironmentObject var store: FlipStore

    let columns = [GridItem(.adaptive(minimum: 160))]

    var body: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 16) {
                ForEach(store.cards) { card in
                    Button {
                        store.selectedCard = card
                    } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Image(uiImage: card.frontImage)
                                .resizable()
                                .aspectRatio(contentMode: .fill)
                                .frame(height: 120)
                                .clipped()
                                .cornerRadius(10)

                            Text(card.label)
                                .font(.caption)
                                .fontWeight(.medium)
                                .foregroundStyle(.primary)
                                .lineLimit(1)

                            Text("\(card.width) x \(card.height)")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding()
        }
        .navigationTitle("Your Cards")
    }
}

// MARK: - Card Viewer

struct CardViewerView: View {
    let card: FlipCard
    @EnvironmentObject var store: FlipStore

    @State private var isFlipped = false
    @State private var dragOffset: CGFloat = 0

    var body: some View {
        VStack(spacing: 24) {
            HStack {
                Text(card.label)
                    .font(.headline)

                Spacer()

                Text(isFlipped ? "BACK" : "FRONT")
                    .font(.caption2)
                    .fontWeight(.semibold)
                    .tracking(1)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Color.indigo.opacity(0.15))
                    .foregroundStyle(.indigo)
                    .cornerRadius(12)
            }
            .padding(.horizontal)

            Spacer()

            // 3D flip card
            ZStack {
                if !isFlipped {
                    Image(uiImage: card.frontImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .cornerRadius(16)
                        .shadow(color: .black.opacity(0.4), radius: 20, y: 10)
                }

                if isFlipped {
                    Image(uiImage: card.backImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .cornerRadius(16)
                        .shadow(color: .black.opacity(0.4), radius: 20, y: 10)
                        .scaleEffect(x: -1) // mirror to simulate flip
                }
            }
            .rotation3DEffect(
                .degrees(isFlipped ? 180 : 0) + .degrees(Double(dragOffset) * 0.3),
                axis: (x: 0, y: 1, z: 0),
                perspective: 0.5
            )
            .gesture(
                DragGesture()
                    .onChanged { value in
                        dragOffset = value.translation.width
                    }
                    .onEnded { value in
                        if abs(value.translation.width) > 60 {
                            withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) {
                                isFlipped.toggle()
                            }
                        }
                        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
                            dragOffset = 0
                        }
                    }
            )
            .onTapGesture {
                withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) {
                    isFlipped.toggle()
                }
            }
            .padding(.horizontal, 20)

            Spacer()

            HStack(spacing: 12) {
                Button {
                    withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) {
                        isFlipped.toggle()
                    }
                } label: {
                    Label("Flip", systemImage: "arrow.left.arrow.right")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                }
                .buttonStyle(.borderedProminent)
                .tint(.indigo)

                if store.cards.count > 1 {
                    Button {
                        store.selectedCard = nil
                    } label: {
                        Label("Gallery", systemImage: "square.grid.2x2")
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                    }
                    .buttonStyle(.bordered)
                }
            }
            .padding(.horizontal)

            Text("Tap card or swipe to flip")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical)
    }
}
