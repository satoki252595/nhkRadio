import Foundation
import Observation

/// Metadata persisted alongside a background download so completion can be
/// recorded even if the app was relaunched while downloading.
struct PendingDownload: Codable {
    var pageID: String
    var databaseID: String
    var itemTitle: String
    var fileName: String
    var kindRaw: String
    var requestID: UUID? = UUID()
    var key: String { "\(pageID)|\(fileName)" }
}

/// File layout for downloaded media:
/// Application Support/Downloads/<pageID>/<fileName> (excluded from backup).
enum DownloadStorage {
    static func downloadsDirectory() throws -> URL {
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true
        )
        let dir = base.appendingPathComponent("Downloads", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutable = dir
        try? mutable.setResourceValues(values)
        return dir
    }

    static func relativePath(pageID: String, fileName: String) -> String {
        "\(pageID)/\(sanitized(fileName))"
    }

    static func fileURL(relativePath: String) -> URL? {
        guard let dir = try? downloadsDirectory() else { return nil }
        return dir.appendingPathComponent(relativePath)
    }

    static func sanitized(_ name: String) -> String {
        let invalid = CharacterSet(charactersIn: "/:\\?%*|\"<>")
        let cleaned = name.unicodeScalars.map { invalid.contains($0) ? Character("_") : Character($0) }
        let result = String(cleaned).trimmingCharacters(in: .whitespaces)
        return result.isEmpty ? "download" : result
    }

    static func totalBytes() -> Int64 {
        guard let dir = try? downloadsDirectory(),
              let enumerator = FileManager.default.enumerator(
                at: dir, includingPropertiesForKeys: [.fileSizeKey]) else { return 0 }
        var total: Int64 = 0
        for case let url as URL in enumerator {
            total += Int64((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        }
        return total
    }
}

/// Background downloads with progress, cancel and relaunch recovery.
@MainActor
@Observable
final class DownloadManager: NSObject {
    /// Progress fractions keyed by "pageID|fileName" (0...1, -1 = unknown size).
    private(set) var progress: [String: Double] = [:]
    var lastError: String?

    // Injected by AppState.
    var onDownloaded: ((PendingDownload, String, Int64) -> Void)?
    var backgroundCompletionHandler: (() -> Void)?

    private var session: URLSession!
    private var tasks: [String: URLSessionDownloadTask] = [:]
    private var resolvingTasks: [String: Task<Void, Never>] = [:]

    private static let pendingDefaultsKey = "downloads.pending"

    override init() {
        super.init()
        let config = URLSessionConfiguration.background(withIdentifier: "dev.satoki.playback.downloads")
        config.isDiscretionary = false
        config.sessionSendsLaunchEvents = true
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        restoreTaskState()
    }

    func isDownloading(_ key: String) -> Bool { progress[key] != nil }

    func enqueue(entry: QueueEntry, resolveURL: @escaping (QueueEntry) async throws -> URL) {
        let pending = PendingDownload(
            pageID: entry.item.pageID,
            databaseID: entry.item.databaseID,
            itemTitle: entry.item.title,
            fileName: entry.file.name,
            kindRaw: entry.file.kind.rawValue
        )
        guard !isDownloading(pending.key) else { return }
        progress[pending.key] = -1
        storePending(pending)
        resolvingTasks[pending.key] = Task { [weak self] in
            do {
                let url = try await resolveURL(entry)
                guard !Task.isCancelled, let self else { return }
                self.resolvingTasks[pending.key] = nil
                // Background URLSessions cannot fetch file:// URLs (demo
                // bundle media, already-local sources): copy directly.
                if url.isFileURL {
                    try self.completeLocalFileDownload(pending: pending, source: url)
                    return
                }
                let task = self.session.downloadTask(with: url)
                task.taskDescription = String(data: try JSONEncoder().encode(pending), encoding: .utf8)
                task.countOfBytesClientExpectsToSend = 0
                self.tasks[pending.key] = task
                task.resume()
            } catch {
                guard !Task.isCancelled else { return }
                self?.resolvingTasks[pending.key] = nil
                self?.fail(pending: pending, message: (error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
            }
        }
    }

    func cancel(key: String) {
        resolvingTasks[key]?.cancel()
        resolvingTasks[key] = nil
        tasks[key]?.cancel()
        tasks[key] = nil
        progress[key] = nil
        removePending(key: key)
    }

    /// Completes a "download" whose source is already a local file by
    /// copying it into the downloads directory.
    private func completeLocalFileDownload(pending: PendingDownload, source: URL) throws {
        let relative = DownloadStorage.relativePath(pageID: pending.pageID, fileName: pending.fileName)
        guard let destination = DownloadStorage.fileURL(relativePath: relative) else {
            throw NotionError.network("保存先を作成できませんでした")
        }
        try FileManager.default.createDirectory(
            at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        if FileManager.default.fileExists(atPath: destination.path) {
            try FileManager.default.removeItem(at: destination)
        }
        try FileManager.default.copyItem(at: source, to: destination)
        let size = (try? destination.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        progress[pending.key] = nil
        removePending(key: pending.key)
        onDownloaded?(pending, relative, Int64(size))
    }

    private func fail(pending: PendingDownload, message: String) {
        progress[pending.key] = nil
        tasks[pending.key] = nil
        removePending(key: pending.key)
        lastError = "「\(pending.fileName)」のダウンロードに失敗しました: \(message)"
    }

    // MARK: - Pending persistence

    nonisolated static func loadPending() -> [String: PendingDownload] {
        guard let data = UserDefaults.standard.data(forKey: pendingDefaultsKey),
              let decoded = try? JSONDecoder().decode([String: PendingDownload].self, from: data) else {
            return [:]
        }
        return decoded
    }

    nonisolated static func savePending(_ pending: [String: PendingDownload]) {
        if let data = try? JSONEncoder().encode(pending) {
            UserDefaults.standard.set(data, forKey: pendingDefaultsKey)
        }
    }

    /// Persisted identity works before getAllTasks completes after relaunch,
    /// and rejects late callbacks from a cancelled attempt.
    nonisolated static func pending(for task: URLSessionTask) -> PendingDownload? {
        guard let description = task.taskDescription else { return nil }
        if let encoded = description.data(using: .utf8),
           let tagged = try? JSONDecoder().decode(PendingDownload.self, from: encoded),
           let current = loadPending()[tagged.key], current.requestID == tagged.requestID {
            return current
        }
        // Downloads created by earlier versions used just the key.
        guard let legacy = loadPending()[description], legacy.requestID == nil else { return nil }
        return legacy
    }

    private func storePending(_ pending: PendingDownload) {
        var all = Self.loadPending()
        all[pending.key] = pending
        Self.savePending(all)
    }

    private func removePending(key: String) {
        var all = Self.loadPending()
        all[key] = nil
        Self.savePending(all)
    }

    private func restoreTaskState() {
        session.getAllTasks { [weak self] tasks in
            Task { @MainActor in
                guard let self else { return }
                for case let task as URLSessionDownloadTask in tasks {
                    if task.state != .canceling, task.state != .completed,
                       let key = Self.pending(for: task)?.key {
                        self.tasks[key] = task
                        if self.progress[key] == nil { self.progress[key] = -1 }
                    }
                }
            }
        }
    }
}

extension DownloadManager: URLSessionDownloadDelegate {
    nonisolated func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                                didFinishDownloadingTo location: URL) {
        // The system deletes `location` when this method returns: move now.
        guard let pending = DownloadManager.pending(for: downloadTask) else { return }
        let key = pending.key
        let relative = DownloadStorage.relativePath(pageID: pending.pageID, fileName: pending.fileName)
        do {
            if let response = downloadTask.response as? HTTPURLResponse,
               !(200...299).contains(response.statusCode) {
                throw NotionError.network("ファイルを取得できませんでした（HTTP \(response.statusCode)）。ライブラリを更新して再試行してください。")
            }
            guard let destination = DownloadStorage.fileURL(relativePath: relative) else {
                throw NotionError.network("保存先を作成できませんでした。端末の空き容量を確認してください。")
            }
            try FileManager.default.createDirectory(
                at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: destination.path) {
                try FileManager.default.removeItem(at: destination)
            }
            try FileManager.default.moveItem(at: location, to: destination)
            let size = (try? destination.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            Task { @MainActor in
                guard Self.pending(for: downloadTask) != nil else { return }
                self.progress[key] = nil
                self.tasks[key] = nil
                self.removePending(key: key)
                self.onDownloaded?(pending, relative, Int64(size))
            }
        } catch {
            Task { @MainActor in
                guard Self.pending(for: downloadTask) != nil else { return }
                self.fail(pending: pending, message: error.localizedDescription)
            }
        }
    }

    nonisolated func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                                didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
                                totalBytesExpectedToWrite: Int64) {
        let fraction = totalBytesExpectedToWrite > 0
            ? Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
            : -1
        Task { @MainActor in
            guard let pending = Self.pending(for: downloadTask) else { return }
            self.progress[pending.key] = fraction
        }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                                didCompleteWithError error: Error?) {
        guard let error else { return }
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain, nsError.code == NSURLErrorCancelled { return }
        Task { @MainActor in
            guard let pending = Self.pending(for: task) else { return }
            self.fail(pending: pending, message: error.localizedDescription)
        }
    }

    nonisolated func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        Task { @MainActor in
            self.backgroundCompletionHandler?()
            self.backgroundCompletionHandler = nil
        }
    }
}
