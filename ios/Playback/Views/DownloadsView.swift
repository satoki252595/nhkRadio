import SwiftData
import SwiftUI

struct DownloadsView: View {
    @Environment(AppState.self) private var appState
    @Query(sort: \DownloadRecord.downloadedAt, order: .reverse) private var records: [DownloadRecord]
    @State private var confirmDeleteAll = false

    private var totalBytes: Int64 { records.reduce(0) { $0 + $1.byteCount } }

    private var activeKeys: [String] {
        appState.downloads.progress.keys.sorted()
    }

    var body: some View {
        NavigationStack {
            Group {
                if records.isEmpty && activeKeys.isEmpty {
                    ContentUnavailableView {
                        Label("ダウンロードはありません", systemImage: "arrow.down.circle")
                    } description: {
                        Text("ライブラリでダウンロードした音声・動画は、オフラインでも再生できます。")
                    }
                } else {
                    list
                }
            }
            .navigationTitle("ダウンロード")
            .toolbar {
                if !records.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button(role: .destructive) {
                                confirmDeleteAll = true
                            } label: {
                                Label("すべて削除", systemImage: "trash")
                            }
                        } label: {
                            Image(systemName: "ellipsis.circle")
                        }
                    }
                }
            }
            .confirmationDialog("すべてのダウンロードを削除しますか？",
                                isPresented: $confirmDeleteAll,
                                titleVisibility: .visible) {
                Button("削除する", role: .destructive) {
                    appState.deleteAllDownloads(records: records)
                }
                Button("キャンセル", role: .cancel) {}
            } message: {
                Text("\(records.count)件・\(ByteFormat.string(totalBytes)) のファイルが端末から削除されます。")
            }
        }
    }

    private var list: some View {
        List {
            if !activeKeys.isEmpty {
                Section {
                    ForEach(activeKeys, id: \.self) { key in
                        activeRow(key: key)
                    }
                } header: {
                    Text("ダウンロード中")
                } footer: {
                    Text("保存が完了するまでオフライン再生はできません。再生の読み込みが進まない場合は、完了を待つか、右の×で中止して再試行してください。")
                }
            }
            if !records.isEmpty {
                Section {
                    ForEach(records) { record in
                        recordRow(record)
                    }
                    .onDelete { offsets in
                        for index in offsets {
                            appState.deleteDownload(records[index])
                        }
                    }
                } header: {
                    Text("保存済み（\(records.count)件）")
                } footer: {
                    Text("使用容量: \(ByteFormat.string(totalBytes))")
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private func activeRow(key: String) -> some View {
        let fraction = appState.downloads.progress[key] ?? -1
        let pending = DownloadManager.loadPending()[key]
        return HStack(spacing: 12) {
            ArtworkTile(title: pending?.itemTitle ?? key,
                        kind: MediaKind(rawValue: pending?.kindRaw ?? "") ?? .audio, size: 42)
            VStack(alignment: .leading, spacing: 4) {
                Text(pending?.itemTitle ?? "ダウンロード")
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                Text(pending?.fileName ?? "")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                if fraction >= 0 {
                    PlayedProgressBar(fraction: fraction)
                    Text("\(Int(fraction * 100))%")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.tertiary)
                } else {
                    Text("準備中…").font(.caption2).foregroundStyle(.tertiary)
                }
            }
            Spacer()
            Button {
                appState.downloads.cancel(key: key)
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("中止")
        }
    }

    private func recordRow(_ record: DownloadRecord) -> some View {
        let item = minimalItem(pageID: record.pageID, databaseID: record.databaseID,
                               title: record.itemTitle, fileName: record.fileName)
        let entry = QueueEntry(item: item, file: item.mediaFiles[0])
        let isCurrent = appState.player.currentEntry?.progressKey == entry.progressKey
        return HStack(spacing: 12) {
            ArtworkTile(title: record.itemTitle, kind: record.kind, size: 46)
            VStack(alignment: .leading, spacing: 3) {
                Text(record.itemTitle)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                Text(record.fileName)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text("\(ByteFormat.string(record.byteCount)) · \(record.downloadedAt.formatted(date: .abbreviated, time: .omitted))")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer(minLength: 4)
            Button {
                if isCurrent {
                    appState.player.togglePlayPause()
                } else {
                    playFrom(record)
                }
            } label: {
                Image(systemName: isCurrent && appState.player.isPlaying
                      ? "pause.circle.fill" : "play.circle.fill")
                    .font(.system(size: 32))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(Color.accentColor)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("再生")
        }
        .contextMenu {
            Button(role: .destructive) {
                appState.deleteDownload(record)
            } label: {
                Label("ダウンロードを削除", systemImage: "trash")
            }
        }
    }

    private func playFrom(_ record: DownloadRecord) {
        let entries = records.map { rec -> QueueEntry in
            let item = minimalItem(pageID: rec.pageID, databaseID: rec.databaseID,
                                   title: rec.itemTitle, fileName: rec.fileName)
            return QueueEntry(item: item, file: item.mediaFiles[0])
        }
        let index = records.firstIndex(where: { $0.key == record.key }) ?? 0
        appState.player.playQueue(entries, startingAt: index)
    }
}
