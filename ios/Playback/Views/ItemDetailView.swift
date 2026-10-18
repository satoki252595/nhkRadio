import SwiftUI

/// Detail screen: every property column of the page, plus per-file
/// playback/download controls.
struct ItemDetailView: View {
    @Environment(AppState.self) private var appState
    let pageID: String

    private var item: LibraryItem? {
        appState.items.first(where: { $0.pageID == pageID })
    }

    var body: some View {
        Group {
            if let item {
                detailContent(item)
            } else {
                ContentUnavailableView("アイテムがありません", systemImage: "doc.question")
            }
        }
        .navigationBarTitleDisplayMode(.inline)
    }

    private func detailContent(_ item: LibraryItem) -> some View {
        List {
            Section {
                header(item)
                    .listRowInsets(EdgeInsets(top: 16, leading: 16, bottom: 16, trailing: 16))
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }

            if !item.mediaFiles.isEmpty {
                Section("メディアファイル") {
                    ForEach(item.mediaFiles) { file in
                        mediaRow(item: item, file: file)
                    }
                }
            } else {
                Section("メディアファイル") {
                    Text("この行のメディア列にはファイルがありません。")
                        .foregroundStyle(.secondary)
                }
            }

            Section("プロパティ") {
                ForEach(item.propertyOrder, id: \.self) { name in
                    propertyRow(name: name, value: item.propertyTexts[name] ?? "")
                }
            }

            if let pageURL = item.pageURL {
                Section {
                    Link(destination: pageURL) {
                        Label("Notionで開く", systemImage: "arrow.up.forward.app")
                    }
                    ShareLink(item: pageURL) {
                        Label("リンクを共有", systemImage: "square.and.arrow.up")
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private func header(_ item: LibraryItem) -> some View {
        VStack(spacing: 14) {
            ArtworkTile(title: item.title, kind: item.mediaFiles.first?.kind ?? .audio, size: 120)
                .shadow(color: .black.opacity(0.18), radius: 12, y: 6)
            Text(item.title)
                .font(.title3.bold())
                .multilineTextAlignment(.center)
            if let file = item.mediaFiles.first {
                let entry = QueueEntry(item: item, file: file)
                HStack(spacing: 12) {
                    Button {
                        if appState.player.currentEntry?.progressKey == entry.progressKey {
                            appState.player.togglePlayPause()
                        } else {
                            appState.play(item: item, file: file, in: appState.items)
                        }
                    } label: {
                        Label(
                            appState.player.currentEntry?.progressKey == entry.progressKey
                                && appState.player.isPlaying ? "一時停止" : "再生",
                            systemImage: appState.player.currentEntry?.progressKey == entry.progressKey
                                && appState.player.isPlaying ? "pause.fill" : "play.fill"
                        )
                        .font(.headline)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)

                    Button {
                        appState.toggleFavorite(entry: entry)
                    } label: {
                        Image(systemName: appState.isFavorite(entry: entry) ? "heart.fill" : "heart")
                            .font(.title3)
                            .foregroundStyle(appState.isFavorite(entry: entry) ? Color.pink : Color.secondary)
                    }
                    .accessibilityLabel("お気に入り")

                    DownloadButton(entry: entry)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func mediaRow(item: LibraryItem, file: MediaFileRef) -> some View {
        let entry = QueueEntry(item: item, file: file)
        let progress = appState.progressRecord(forKey: entry.progressKey)
        let isCurrent = appState.player.currentEntry?.progressKey == entry.progressKey
        return HStack(spacing: 12) {
            Button {
                if isCurrent {
                    appState.player.togglePlayPause()
                } else {
                    appState.play(item: item, file: file, in: appState.items)
                }
            } label: {
                Image(systemName: isCurrent && appState.player.isPlaying
                      ? "pause.circle.fill" : "play.circle.fill")
                    .font(.system(size: 30))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(Color.accentColor)
            }
            .buttonStyle(.borderless)

            VStack(alignment: .leading, spacing: 3) {
                Text(file.name)
                    .font(.subheadline.weight(.medium))
                    .lineLimit(1)
                    .truncationMode(.middle)
                HStack(spacing: 6) {
                    Image(systemName: file.kind.systemImage)
                    if let progress, progress.durationSeconds > 0 {
                        if progress.isFinished {
                            Text("再生済み · \(TimeFormat.clock(progress.durationSeconds))")
                        } else {
                            Text("\(TimeFormat.clock(progress.positionSeconds)) / \(TimeFormat.clock(progress.durationSeconds)) · \(TimeFormat.remaining(position: progress.positionSeconds, duration: progress.durationSeconds))")
                        }
                    } else {
                        Text(file.kind == .video ? "動画" : file.kind == .audio ? "音声" : "ファイル")
                    }
                    if appState.downloadRecord(forKey: entry.progressKey) != nil {
                        Text("· 保存済み")
                    }
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
                if let progress, !progress.isFinished, progress.fraction > 0.01 {
                    PlayedProgressBar(fraction: progress.fraction)
                }
            }
            Spacer(minLength: 4)
            DownloadButton(entry: entry)
        }
        .contextMenu {
            Button {
                appState.setFinished(entry: entry, finished: false)
                appState.play(item: item, file: file, in: appState.items)
            } label: {
                Label("最初から再生", systemImage: "arrow.counterclockwise")
            }
            Button {
                appState.toggleFavorite(entry: entry)
            } label: {
                Label(appState.isFavorite(entry: entry) ? "お気に入り解除" : "お気に入りに追加",
                      systemImage: "heart")
            }
            Button {
                appState.setFinished(entry: entry, finished: !(progress?.isFinished ?? false))
            } label: {
                Label(progress?.isFinished == true ? "未再生に戻す" : "再生済みにする",
                      systemImage: "checkmark.circle")
            }
        }
    }

    private func propertyRow(name: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(name)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            if value.isEmpty {
                Text("—").foregroundStyle(.tertiary)
            } else if let url = URL(string: value),
                      value.hasPrefix("http://") || value.hasPrefix("https://") {
                Link(value, destination: url)
                    .font(.subheadline)
                    .lineLimit(2)
            } else {
                Text(value)
                    .font(.subheadline)
                    .textSelection(.enabled)
            }
        }
        .padding(.vertical, 2)
    }
}
