import SwiftData
import SwiftUI

enum LibraryFilter: String, CaseIterable, Identifiable {
    case all = "すべて"
    case unplayed = "未再生"
    case inProgress = "再生中"
    case downloaded = "保存済み"
    case favorites = "お気に入り"
    var id: String { rawValue }
}

struct LibraryView: View {
    @Environment(AppState.self) private var appState
    @Query(sort: \ConnectionRecord.addedAt) private var connections: [ConnectionRecord]

    @State private var searchText = ""
    @State private var filter: LibraryFilter = .all
    @State private var isSelecting = false
    @State private var selection: Set<String> = []
    @State private var showConnect = false

    private var selectedConnection: ConnectionRecord? {
        if let id = appState.selectedDatabaseID,
           let match = connections.first(where: { $0.databaseID == id }) {
            return match
        }
        return connections.first
    }

    private var activeMapping: DatabaseMapping {
        if appState.isDemo { return DemoData.mapping }
        return selectedConnection?.mapping
            ?? DatabaseMapping(mediaProperty: "", titleProperty: "", displayProperties: [])
    }

    private var visibleItems: [LibraryItem] {
        var result = appState.items
        if !searchText.isEmpty {
            let needle = searchText.lowercased()
            result = result.filter { item in
                item.title.lowercased().contains(needle)
                    || item.propertyTexts.values.contains { $0.lowercased().contains(needle) }
                    || item.mediaFiles.contains { $0.name.lowercased().contains(needle) }
            }
        }
        switch filter {
        case .all:
            break
        case .unplayed:
            result = result.filter { item in
                guard let file = item.mediaFiles.first else { return true }
                let record = appState.progressRecord(forKey: "\(item.pageID)|\(file.name)")
                return record == nil || (record!.positionSeconds < 5 && !record!.isFinished)
            }
        case .inProgress:
            result = result.filter { item in
                item.mediaFiles.contains { file in
                    guard let record = appState.progressRecord(forKey: "\(item.pageID)|\(file.name)")
                    else { return false }
                    return !record.isFinished && record.positionSeconds >= 5
                }
            }
        case .downloaded:
            result = result.filter { item in
                item.mediaFiles.contains {
                    appState.downloadRecord(forKey: "\(item.pageID)|\($0.name)") != nil
                }
            }
        case .favorites:
            result = result.filter { item in
                item.mediaFiles.contains { file in
                    appState.progressRecord(forKey: "\(item.pageID)|\(file.name)")?.isFavorite == true
                }
            }
        }
        return result
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(navigationTitle)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { toolbarContent }
                .searchable(text: $searchText, prompt: "タイトル・列の値を検索")
                .sheet(isPresented: $showConnect) {
                    ConnectDatabaseView()
                }
                .task(id: selectedConnection?.databaseID) {
                    if !appState.isDemo, let connection = selectedConnection {
                        await appState.loadLibrary(connection: connection)
                    }
                }
                .onChange(of: connections.map(\.databaseID)) { _, _ in
                    if let connection = selectedConnection,
                       appState.selectedDatabaseID != connection.databaseID {
                        appState.selectedDatabaseID = connection.databaseID
                    }
                }
        }
    }

    private var navigationTitle: String {
        if appState.isDemo { return DemoData.databaseTitle }
        return selectedConnection?.title ?? "ライブラリ"
    }

    @ViewBuilder
    private var content: some View {
        if !appState.isDemo, connections.isEmpty {
            emptyConnectionsView
        } else if appState.isLoadingLibrary, appState.items.isEmpty {
            ProgressView("読み込み中…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = appState.libraryError, appState.items.isEmpty {
            ContentUnavailableView {
                Label("読み込めませんでした", systemImage: "exclamationmark.triangle")
            } description: {
                Text(error)
            } actions: {
                Button("再試行") {
                    if let connection = selectedConnection {
                        Task { await appState.loadLibrary(connection: connection) }
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        } else {
            libraryList
        }
    }

    private var emptyConnectionsView: some View {
        ContentUnavailableView {
            Label("データベース未接続", systemImage: "tablecells.badge.ellipsis")
        } description: {
            Text("音声・動画ファイルのあるNotionデータベースを接続すると、ここに一覧が表示されます。")
        } actions: {
            Button {
                showConnect = true
            } label: {
                Label("データベースを接続", systemImage: "plus.circle.fill")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }

    private var libraryList: some View {
        List {
            if let error = appState.libraryError {
                Section {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
            Section {
                if visibleItems.isEmpty {
                    Text(searchText.isEmpty && filter == .all
                         ? "行がありません。"
                         : "条件に一致する行がありません。")
                        .foregroundStyle(.secondary)
                }
                ForEach(visibleItems) { item in
                    row(for: item)
                        .onAppear {
                            if item.pageID == visibleItems.last?.pageID,
                               let connection = selectedConnection {
                                Task { await appState.loadMore(connection: connection) }
                            }
                        }
                }
                if appState.isLoadingMore {
                    HStack {
                        Spacer()
                        ProgressView().controlSize(.small)
                        Spacer()
                    }
                }
            }
        }
        .listStyle(.plain)
        .refreshable {
            if !appState.isDemo, let connection = selectedConnection {
                await appState.loadLibrary(connection: connection)
            }
        }
        .safeAreaInset(edge: .top) { filterChips }
        .safeAreaInset(edge: .bottom) {
            if isSelecting { selectionBar }
        }
    }

    @ViewBuilder
    private func row(for item: LibraryItem) -> some View {
        if isSelecting {
            Button {
                toggleSelection(item.pageID)
            } label: {
                LibraryRowView(
                    item: item, mapping: activeMapping,
                    showsSelectionCheckbox: true,
                    isSelected: selection.contains(item.pageID)
                )
            }
            .buttonStyle(.plain)
        } else {
            NavigationLink {
                ItemDetailView(pageID: item.pageID)
            } label: {
                LibraryRowView(item: item, mapping: activeMapping)
            }
            .swipeActions(edge: .leading, allowsFullSwipe: false) {
                if let file = item.mediaFiles.first {
                    let entry = QueueEntry(item: item, file: file)
                    Button {
                        appState.enqueueDownload(entry)
                    } label: {
                        Label("保存", systemImage: "arrow.down.circle")
                    }
                    .tint(.blue)
                    Button {
                        appState.toggleFavorite(entry: entry)
                    } label: {
                        Label("お気に入り", systemImage: "heart")
                    }
                    .tint(.pink)
                }
            }
        }
    }

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(LibraryFilter.allCases) { candidate in
                    Button(candidate.rawValue) { filter = candidate }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .tint(filter == candidate ? Color.accentColor : Color.secondary)
                        .fontWeight(filter == candidate ? .bold : .regular)
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 6)
        }
        .background(.bar)
    }

    private var selectionBar: some View {
        HStack(spacing: 16) {
            Button(selection.count == visibleItems.count ? "すべて解除" : "すべて選択") {
                if selection.count == visibleItems.count {
                    selection.removeAll()
                } else {
                    selection = Set(visibleItems.map(\.pageID))
                }
            }
            .font(.subheadline.weight(.semibold))
            Spacer()
            Button {
                downloadSelected()
            } label: {
                Label("\(selection.count)件をダウンロード", systemImage: "arrow.down.circle.fill")
                    .font(.subheadline.bold())
            }
            .disabled(selection.isEmpty)
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.bar)
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            if !appState.isDemo, connections.count > 1 {
                Menu {
                    ForEach(connections) { connection in
                        Button {
                            appState.selectedDatabaseID = connection.databaseID
                        } label: {
                            if connection.databaseID == selectedConnection?.databaseID {
                                Label(connection.title, systemImage: "checkmark")
                            } else {
                                Text(connection.title)
                            }
                        }
                    }
                } label: {
                    Label("データベース切替", systemImage: "arrow.triangle.2.circlepath")
                        .labelStyle(.iconOnly)
                }
            }
        }
        ToolbarItemGroup(placement: .topBarTrailing) {
            if isSelecting {
                Button("完了") {
                    isSelecting = false
                    selection.removeAll()
                }
                .bold()
            } else {
                Menu {
                    Button {
                        isSelecting = true
                    } label: {
                        Label("選択してダウンロード", systemImage: "checkmark.circle")
                    }
                    if !appState.isDemo {
                        Button {
                            showConnect = true
                        } label: {
                            Label("データベースを追加", systemImage: "plus")
                        }
                    }
                    if let connection = selectedConnection {
                        Button {
                            Task { await appState.loadLibrary(connection: connection) }
                        } label: {
                            Label("再読み込み", systemImage: "arrow.clockwise")
                        }
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
    }

    private func toggleSelection(_ pageID: String) {
        if selection.contains(pageID) {
            selection.remove(pageID)
        } else {
            selection.insert(pageID)
        }
    }

    private func downloadSelected() {
        for item in visibleItems where selection.contains(item.pageID) {
            for file in item.mediaFiles {
                let entry = QueueEntry(item: item, file: file)
                if appState.downloadRecord(forKey: entry.progressKey) == nil {
                    appState.enqueueDownload(entry)
                }
            }
        }
        selection.removeAll()
        isSelecting = false
    }
}
