import SwiftData
import SwiftUI

struct HistoryView: View {
    @Environment(AppState.self) private var appState
    @Query(sort: \ProgressRecord.lastPlayedAt, order: .reverse) private var records: [ProgressRecord]
    @State private var segment: Segment = .continueListening

    enum Segment: String, CaseIterable {
        case continueListening = "続きから聴く"
        case favorites = "お気に入り"
        case history = "履歴"
    }

    private var visibleRecords: [ProgressRecord] {
        switch segment {
        case .continueListening:
            return records.filter { !$0.isFinished && $0.positionSeconds >= 5 && $0.lastPlayedAt != nil }
        case .favorites:
            return records.filter(\.isFavorite)
        case .history:
            return records.filter { $0.lastPlayedAt != nil }
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if visibleRecords.isEmpty {
                    ContentUnavailableView(
                        segment == .favorites ? "お気に入りはありません" : "履歴はまだありません",
                        systemImage: segment == .favorites ? "heart" : "clock.arrow.circlepath",
                        description: Text(
                            segment == .continueListening
                                ? "再生を途中で止めると、ここから続きを聴けます。"
                                : segment == .favorites
                                    ? "詳細画面でハートを付けたアイテムが集まります。"
                                    : "再生したアイテムが新しい順に表示されます。"
                        )
                    )
                } else {
                    List {
                        ForEach(visibleRecords) { record in
                            recordRow(record)
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("履歴")
            .safeAreaInset(edge: .top) {
                Picker("表示", selection: $segment) {
                    ForEach(Segment.allCases, id: \.self) { candidate in
                        Text(candidate.rawValue).tag(candidate)
                    }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .padding(.vertical, 6)
                .background(.bar)
            }
        }
    }

    private func recordRow(_ record: ProgressRecord) -> some View {
        let item = minimalItem(pageID: record.pageID, databaseID: record.databaseID,
                               title: record.itemTitle, fileName: record.fileName)
        let entry = QueueEntry(item: item, file: item.mediaFiles[0])
        let isCurrent = appState.player.currentEntry?.progressKey == entry.progressKey
        // Prefer the rich library item when it is loaded.
        let richItem = appState.items.first(where: { $0.pageID == record.pageID })
        return HStack(spacing: 12) {
            ArtworkTile(title: record.itemTitle, kind: MediaKind(fileName: record.fileName), size: 46)
            VStack(alignment: .leading, spacing: 3) {
                Text(record.itemTitle)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                Text(record.fileName)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                HStack(spacing: 6) {
                    if record.isFinished {
                        Label("再生済み", systemImage: "checkmark")
                    } else if record.durationSeconds > 0 {
                        Text(TimeFormat.remaining(position: record.positionSeconds,
                                                   duration: record.durationSeconds))
                    }
                    if record.isFavorite {
                        Label("お気に入り", systemImage: "heart.fill")
                    }
                    if appState.downloadRecord(forKey: record.key) != nil {
                        Label("保存済み", systemImage: "arrow.down.circle.fill")
                    }
                    if let last = record.lastPlayedAt {
                        Text(last.formatted(.relative(presentation: .named)))
                    }
                }
                .font(.caption2)
                .foregroundStyle(.tertiary)
                if !record.isFinished, record.fraction > 0.01 {
                    PlayedProgressBar(fraction: record.fraction)
                        .frame(maxWidth: 160)
                }
            }
            Spacer(minLength: 4)
            Button {
                if isCurrent {
                    appState.player.togglePlayPause()
                } else if let richItem,
                          let file = richItem.mediaFiles.first(where: { $0.name == record.fileName }) {
                    appState.play(item: richItem, file: file, in: appState.items)
                } else {
                    appState.player.playQueue([entry], startingAt: 0)
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
    }
}
