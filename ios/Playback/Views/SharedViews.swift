import SwiftData
import SwiftUI
import UIKit

/// Deterministic gradient artwork tile with a media glyph.
struct ArtworkTile: View {
    let title: String
    let kind: MediaKind
    var size: CGFloat = 52

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: gradientColors,
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
            Image(systemName: kind == .video ? "film.fill" : "waveform")
                .font(.system(size: size * 0.42, weight: .medium))
                .foregroundStyle(.white.opacity(0.92))
        }
        .frame(width: size, height: size)
    }

    private var gradientColors: [Color] {
        let hue = Double(abs(title.hashValue) % 360) / 360.0
        return [
            Color(hue: hue, saturation: 0.55, brightness: 0.42),
            Color(hue: fmod(hue + 0.12, 1.0), saturation: 0.65, brightness: 0.24),
        ]
    }
}

/// Thin progress bar shown under rows that are partially played.
struct PlayedProgressBar: View {
    let fraction: Double
    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.secondary.opacity(0.25))
                Capsule().fill(Color.accentColor)
                    .frame(width: max(2, proxy.size.width * fraction))
            }
        }
        .frame(height: 3)
    }
}

/// Download state for one queue entry, resolved from SwiftData + manager.
enum DownloadState {
    case notDownloaded
    case downloading(Double) // -1 = indeterminate
    case downloaded
}

/// Circular download button reflecting not-downloaded / downloading /
/// downloaded. Tapping a downloaded file offers deletion via context menu.
struct DownloadButton: View {
    @Environment(AppState.self) private var appState
    let entry: QueueEntry

    var body: some View {
        content
    }

    private var state: DownloadState {
        if let fraction = appState.downloads.progress[entry.progressKey] {
            return .downloading(fraction)
        }
        if appState.downloadRecord(forKey: entry.progressKey) != nil {
            return .downloaded
        }
        return .notDownloaded
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .notDownloaded:
            Button {
                appState.enqueueDownload(entry)
            } label: {
                Image(systemName: "arrow.down.circle")
                    .font(.title3)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("ダウンロード")
        case .downloading(let fraction):
            Button {
                appState.downloads.cancel(key: entry.progressKey)
            } label: {
                ZStack {
                    if fraction >= 0 {
                        Circle()
                            .trim(from: 0, to: fraction)
                            .stroke(Color.accentColor, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                            .rotationEffect(.degrees(-90))
                    } else {
                        ProgressView().controlSize(.small)
                    }
                    Image(systemName: "xmark")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(.secondary)
                }
                .frame(width: 22, height: 22)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("ダウンロードを中止")
        case .downloaded:
            Menu {
                Button(role: .destructive) {
                    if let record = appState.downloadRecord(forKey: entry.progressKey) {
                        appState.deleteDownload(record)
                    }
                } label: {
                    Label("ダウンロードを削除", systemImage: "trash")
                }
            } label: {
                Image(systemName: "arrow.down.circle.fill")
                    .font(.title3)
                    .foregroundStyle(Color.accentColor)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("ダウンロード済み")
        }
    }
}

/// One library row: artwork, title, selected property columns, badges.
struct LibraryRowView: View {
    @Environment(AppState.self) private var appState
    let item: LibraryItem
    let mapping: DatabaseMapping
    var showsSelectionCheckbox: Bool = false
    var isSelected: Bool = false

    private var firstFile: MediaFileRef? { item.mediaFiles.first }
    private var firstEntry: QueueEntry? {
        firstFile.map { QueueEntry(item: item, file: $0) }
    }

    private var progress: ProgressRecord? {
        firstEntry.flatMap { appState.progressRecord(forKey: $0.progressKey) }
    }

    private var isCurrent: Bool {
        guard let firstEntry else { return false }
        return appState.player.currentEntry?.progressKey == firstEntry.progressKey
    }

    private var isDownloaded: Bool {
        item.mediaFiles.contains {
            appState.downloadRecord(forKey: "\(item.pageID)|\($0.name)") != nil
        }
    }

    var body: some View {
        HStack(spacing: 12) {
            if showsSelectionCheckbox {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(isSelected ? Color.accentColor : Color.secondary)
            }
            ArtworkTile(title: item.title, kind: firstFile?.kind ?? .audio)
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                    .foregroundStyle(progress?.isFinished == true ? .secondary : .primary)
                let detail = item.displayText(mapping)
                if !detail.isEmpty {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                HStack(spacing: 8) {
                    if item.mediaFiles.count > 1 {
                        Label("\(item.mediaFiles.count)ファイル", systemImage: "doc.on.doc")
                    }
                    if item.mediaFiles.isEmpty {
                        Label("メディアなし", systemImage: "exclamationmark.circle")
                    }
                    if isDownloaded {
                        Label("保存済み", systemImage: "arrow.down.circle.fill")
                    }
                    if progress?.isFavorite == true {
                        Label("お気に入り", systemImage: "heart.fill")
                    }
                    if progress?.isFinished == true {
                        Label("再生済み", systemImage: "checkmark")
                    }
                }
                .font(.caption2)
                .foregroundStyle(.tertiary)
                if let progress, !progress.isFinished, progress.fraction > 0.01 {
                    PlayedProgressBar(fraction: progress.fraction)
                        .frame(maxWidth: 160)
                }
            }
            Spacer(minLength: 4)
            if !showsSelectionCheckbox, let firstEntry {
                Button {
                    if isCurrent {
                        appState.player.togglePlayPause()
                    } else {
                        appState.play(item: item, file: firstEntry.file, in: appState.items)
                    }
                } label: {
                    Image(systemName: isCurrent && appState.player.isPlaying
                          ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 34))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(Color.accentColor)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(isCurrent && appState.player.isPlaying ? "一時停止" : "再生")
            }
        }
        .contentShape(Rectangle())
        .padding(.vertical, 2)
    }
}

/// Builds a minimal LibraryItem from stored records (downloads/history).
func minimalItem(pageID: String, databaseID: String, title: String, fileName: String) -> LibraryItem {
    LibraryItem(
        pageID: pageID,
        databaseID: databaseID,
        title: title,
        propertyTexts: [:],
        propertyOrder: [],
        mediaFiles: [MediaFileRef(name: fileName, urlString: "", isExternal: false)],
        pageURLString: nil,
        createdAt: nil,
        lastEditedAt: nil
    )
}

enum TimeFormat {
    static func clock(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0 else { return "0:00" }
        let total = Int(seconds.rounded())
        let h = total / 3600
        let m = (total % 3600) / 60
        let s = total % 60
        if h > 0 { return String(format: "%d:%02d:%02d", h, m, s) }
        return String(format: "%d:%02d", m, s)
    }

    static func remaining(position: Double, duration: Double) -> String {
        let left = max(0, duration - position)
        return "残り \(clock(left))"
    }
}

enum ByteFormat {
    static func string(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}
