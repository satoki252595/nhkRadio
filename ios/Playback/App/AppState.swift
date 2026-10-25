import Foundation
import Observation
import SwiftData

enum AuthState: Equatable {
    case signedOut
    case demo
    case notion(workspaceName: String?, kind: String)
}

/// Central coordinator: auth, the Notion client, the player, downloads and
/// the currently loaded library. Views read records via SwiftData @Query and
/// call into here for actions.
@MainActor
@Observable
final class AppState {
    private(set) var authState: AuthState = .signedOut

    let client: NotionClient
    let auth = AuthService()
    let player = PlayerEngine()
    let downloads = DownloadManager()

    /// Set once from the root view (SwiftData environment).
    var modelContext: ModelContext?

    // A fetch alone does not observe SwiftData insertions/deletions in SwiftUI.
    private var downloadRecordsVersion = 0

    // Library state for the selected connection.
    private(set) var items: [LibraryItem] = []
    private(set) var isLoadingLibrary = false
    private(set) var isLoadingMore = false
    var libraryError: String?
    private var nextCursor: String?
    var selectedDatabaseID: String? {
        didSet { UserDefaults.standard.set(selectedDatabaseID, forKey: "library.selectedDatabaseID") }
    }
    private var schemaCache: [String: [PropertySchema]] = [:]
    /// Mapping that produced `items` (used for URL refresh + display).
    private(set) var activeMapping: DatabaseMapping?

    var isDemo: Bool { authState == .demo }

    init(client: NotionClient = NotionClient()) {
        self.client = client
        selectedDatabaseID = UserDefaults.standard.string(forKey: "library.selectedDatabaseID")
        restoreSession()
        wireServices()
    }

    // MARK: - Session

    func restoreSession() {
        if UserDefaults.standard.bool(forKey: "auth.demoMode") {
            authState = .demo
            items = DemoData.items
            activeMapping = DemoData.mapping
            return
        }
        if let token = Keychain.get(CredentialKey.accessToken), !token.isEmpty {
            let kind = UserDefaults.standard.string(forKey: CredentialKey.authKind) ?? "token"
            let workspace = UserDefaults.standard.string(forKey: CredentialKey.workspaceName)
            authState = .notion(workspaceName: workspace, kind: kind)
        } else {
            authState = .signedOut
        }
    }

    func enterDemoMode() {
        UserDefaults.standard.set(true, forKey: "auth.demoMode")
        authState = .demo
        items = DemoData.items
        activeMapping = DemoData.mapping
        nextCursor = nil
    }

    func completeSignIn(_ success: AuthSuccess) {
        UserDefaults.standard.set(false, forKey: "auth.demoMode")
        let kind = UserDefaults.standard.string(forKey: CredentialKey.authKind) ?? "token"
        authState = .notion(workspaceName: success.workspaceName, kind: kind)
        items = []
        activeMapping = nil
    }

    func signOut() {
        player.stop()
        auth.signOut()
        UserDefaults.standard.set(false, forKey: "auth.demoMode")
        authState = .signedOut
        items = []
        activeMapping = nil
        nextCursor = nil
    }

    // MARK: - Library loading

    func loadLibrary(connection: ConnectionRecord) async {
        if isDemo {
            items = DemoData.items
            activeMapping = DemoData.mapping
            return
        }
        selectedDatabaseID = connection.databaseID
        isLoadingLibrary = true
        libraryError = nil
        defer { isLoadingLibrary = false }
        do {
            let schema = try await schema(for: connection.databaseID)
            let page = try await client.query(
                databaseID: connection.databaseID, schema: schema, mapping: connection.mapping)
            items = page.items
            nextCursor = page.nextCursor
            activeMapping = connection.mapping
        } catch {
            libraryError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            items = []
        }
    }

    func loadMore(connection: ConnectionRecord) async {
        guard !isDemo, let cursor = nextCursor, !isLoadingMore else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        do {
            let schema = try await schema(for: connection.databaseID)
            let page = try await client.query(
                databaseID: connection.databaseID, schema: schema,
                mapping: connection.mapping, cursor: cursor)
            let known = Set(items.map(\.pageID))
            items += page.items.filter { !known.contains($0.pageID) }
            nextCursor = page.nextCursor
        } catch {
            libraryError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    var hasMorePages: Bool { nextCursor != nil }

    func schema(for databaseID: String) async throws -> [PropertySchema] {
        if databaseID == DemoData.databaseID { return DemoData.schema }
        if let cached = schemaCache[databaseID] { return cached }
        let result = try await client.database(id: databaseID)
        schemaCache[databaseID] = result.schema
        return result.schema
    }

    func invalidateSchema(databaseID: String) {
        schemaCache[databaseID] = nil
    }

    // MARK: - Playback

    var playbackStatusMessage: String? {
        if let failure = player.playbackFailure { return failure }
        guard player.isWaiting, let entry = player.currentEntry else { return nil }
        if let fraction = downloads.progress[entry.progressKey] {
            let progress = fraction >= 0 ? "（\(Int(fraction * 100))%）" : ""
            return "ダウンロード中\(progress)です。現在、再生データの読み込みを待っています。完了まで待つか、ダウンロードを中止して再試行してください。"
        }
        return "再生データを読み込み中です。時間がかかる場合は通信環境を確認して再試行してください。"
    }

    /// Builds a queue starting at the chosen file, then the rest of the
    /// item's files, then subsequent items in the given list.
    func play(item: LibraryItem, file: MediaFileRef, in list: [LibraryItem]) {
        var queue: [QueueEntry] = []
        let startIndex = list.firstIndex(where: { $0.pageID == item.pageID }) ?? 0
        for (offset, candidate) in list.enumerated() where offset >= startIndex {
            if candidate.pageID == item.pageID {
                queue.append(QueueEntry(item: candidate, file: file))
                for extra in candidate.mediaFiles where extra.name != file.name {
                    queue.append(QueueEntry(item: candidate, file: extra))
                }
            } else {
                for media in candidate.mediaFiles {
                    queue.append(QueueEntry(item: candidate, file: media))
                }
            }
        }
        if queue.isEmpty {
            queue = [QueueEntry(item: item, file: file)]
        }
        player.playQueue(queue, startingAt: 0)
    }

    func resolveURL(for entry: QueueEntry) async throws -> URL {
        // 1. Local download wins (offline, no network, no expiry).
        if let record = downloadRecord(forKey: entry.progressKey),
           let url = DownloadStorage.fileURL(relativePath: record.relativePath),
           FileManager.default.fileExists(atPath: url.path) {
            return url
        }
        return try await resolveOriginalURL(for: entry)
    }

    // MARK: - Downloads & progress (SwiftData)

    func downloadRecord(forKey key: String) -> DownloadRecord? {
        _ = downloadRecordsVersion
        guard let modelContext else { return nil }
        let descriptor = FetchDescriptor<DownloadRecord>(
            predicate: #Predicate { $0.key == key })
        return try? modelContext.fetch(descriptor).first
    }

    func progressRecord(forKey key: String) -> ProgressRecord? {
        guard let modelContext else { return nil }
        let descriptor = FetchDescriptor<ProgressRecord>(
            predicate: #Predicate { $0.key == key })
        return try? modelContext.fetch(descriptor).first
    }

    func enqueueDownload(_ entry: QueueEntry) {
        downloads.enqueue(entry: entry) { [weak self] entry in
            guard let self else { throw NotionError.network("アプリ状態が破棄されました") }
            return try await self.resolveOriginalURL(for: entry)
        }
    }

    /// Downloads must never resolve to an already-local file.
    private func resolveOriginalURL(for entry: QueueEntry) async throws -> URL {
        if entry.item.databaseID == DemoData.databaseID || entry.item.pageID.hasPrefix("demo-page") {
            if let url = DemoData.bundleURL(forFileName: entry.file.name) { return url }
            throw NotionError.decoding("デモファイルが見つかりません")
        }
        if entry.file.isExternal, let url = URL(string: entry.file.urlString) {
            return url
        }
        // History and queued entries may belong to a different database than
        // the visible library. Always use the entry's saved connection.
        let databaseID = entry.item.databaseID
        let descriptor = FetchDescriptor<ConnectionRecord>(predicate: #Predicate { $0.databaseID == databaseID })
        guard let connection = try modelContext?.fetch(descriptor).first else {
            throw MediaPlaybackError.missingConnection
        }
        return try await client.freshMediaURL(
            pageID: entry.item.pageID,
            mediaProperty: connection.mapping.mediaProperty,
            fileName: entry.file.name
        )
    }

    func deleteDownload(_ record: DownloadRecord) {
        if let url = DownloadStorage.fileURL(relativePath: record.relativePath) {
            player.invalidateLocalFile(url, progressKey: record.key)
            try? FileManager.default.removeItem(at: url)
        }
        modelContext?.delete(record)
        try? modelContext?.save()
        downloadRecordsVersion += 1
    }

    func deleteAllDownloads(records: [DownloadRecord]) {
        for record in records {
            if let url = DownloadStorage.fileURL(relativePath: record.relativePath) {
                player.invalidateLocalFile(url, progressKey: record.key)
                try? FileManager.default.removeItem(at: url)
            }
            modelContext?.delete(record)
        }
        try? modelContext?.save()
        downloadRecordsVersion += 1
    }

    func toggleFavorite(entry: QueueEntry) {
        let record = progressRecord(forKey: entry.progressKey) ?? {
            let created = ProgressRecord(
                key: entry.progressKey, pageID: entry.item.pageID,
                databaseID: entry.item.databaseID,
                itemTitle: entry.item.title, fileName: entry.file.name)
            modelContext?.insert(created)
            return created
        }()
        record.isFavorite.toggle()
        try? modelContext?.save()
    }

    func isFavorite(entry: QueueEntry) -> Bool {
        progressRecord(forKey: entry.progressKey)?.isFavorite ?? false
    }

    func setFinished(entry: QueueEntry, finished: Bool) {
        let record = progressRecord(forKey: entry.progressKey) ?? {
            let created = ProgressRecord(
                key: entry.progressKey, pageID: entry.item.pageID,
                databaseID: entry.item.databaseID,
                itemTitle: entry.item.title, fileName: entry.file.name)
            modelContext?.insert(created)
            return created
        }()
        record.isFinished = finished
        if !finished { record.positionSeconds = 0 }
        try? modelContext?.save()
    }

    // MARK: - Wiring

    private func wireServices() {
        client.accessTokenProvider = { Keychain.get(CredentialKey.accessToken) }
        client.refreshHandler = { [weak self] in
            guard let self else { return false }
            return await self.auth.refreshOAuthToken()
        }
        player.resolveURL = { [weak self] entry in
            guard let self else { throw NotionError.network("アプリ状態が破棄されました") }
            return try await self.resolveURL(for: entry)
        }
        player.resumePositionProvider = { [weak self] entry in
            guard let self, let record = self.progressRecord(forKey: entry.progressKey),
                  !record.isFinished else { return nil }
            return record.positionSeconds
        }
        player.progressHandler = { [weak self] entry, position, duration, finished in
            guard let self, let modelContext = self.modelContext else { return }
            let record = self.progressRecord(forKey: entry.progressKey) ?? {
                let created = ProgressRecord(
                    key: entry.progressKey, pageID: entry.item.pageID,
                    databaseID: entry.item.databaseID,
                    itemTitle: entry.item.title, fileName: entry.file.name)
                modelContext.insert(created)
                return created
            }()
            record.positionSeconds = position
            record.durationSeconds = duration
            record.isFinished = finished
            record.lastPlayedAt = Date()
            try? modelContext.save()
        }
        downloads.onDownloaded = { [weak self] pending, relativePath, byteCount in
            guard let self, let modelContext = self.modelContext else { return }
            if let existing = self.downloadRecord(forKey: pending.key) {
                modelContext.delete(existing)
            }
            let record = DownloadRecord(
                key: pending.key, pageID: pending.pageID, databaseID: pending.databaseID,
                itemTitle: pending.itemTitle, fileName: pending.fileName,
                relativePath: relativePath, byteCount: byteCount,
                kind: MediaKind(rawValue: pending.kindRaw) ?? .other)
            modelContext.insert(record)
            try? modelContext.save()
            self.downloadRecordsVersion += 1
        }
    }
}
