import Foundation
import SwiftData

// MARK: - Value types (Notion side)

/// One property in a database schema.
struct PropertySchema: Codable, Hashable, Identifiable {
    var name: String
    var type: String
    var id: String { name }
}

/// How a database maps onto the player UI. Stored per connection.
struct DatabaseMapping: Codable, Hashable {
    var mediaProperty: String
    var titleProperty: String
    /// Properties shown in list rows (ordered). The detail screen shows all.
    var displayProperties: [String]
    var sortProperty: String?
    var sortDescending: Bool = true

    static func suggested(from schema: [PropertySchema]) -> DatabaseMapping {
        let media = schema.first(where: { $0.type == "files" })?.name ?? ""
        let title = schema.first(where: { $0.type == "title" })?.name ?? schema.first?.name ?? ""
        var display = schema
            .filter { $0.type != "files" && $0.type != "title" }
            .prefix(3)
            .map(\.name)
        if display.isEmpty { display = [] }
        let sort = schema.first(where: { $0.type == "date" })?.name
            ?? schema.first(where: { $0.type == "created_time" })?.name
        return DatabaseMapping(
            mediaProperty: media,
            titleProperty: title,
            displayProperties: display,
            sortProperty: sort,
            sortDescending: true
        )
    }
}

/// A database the user can connect to (search result or pasted ID).
struct DatabaseRef: Codable, Hashable, Identifiable {
    var id: String
    var title: String
    var iconEmoji: String?
}

/// A media file attached to a page.
struct MediaFileRef: Codable, Hashable, Identifiable {
    var name: String
    /// Signed URL at fetch time. Notion `file` URLs expire in ~1 hour and
    /// are refreshed right before playback/download.
    var urlString: String
    var isExternal: Bool
    var id: String { name }

    var kind: MediaKind { MediaKind(fileName: name) }
}

enum MediaKind: String, Codable {
    case audio, video, other

    init(fileName: String) {
        let ext = (fileName as NSString).pathExtension.lowercased()
        switch ext {
        case "m4a", "mp3", "aac", "wav", "aif", "aiff", "flac", "ogg", "opus", "caf":
            self = .audio
        case "mp4", "mov", "m4v", "webm", "mkv":
            self = .video
        default:
            self = .other
        }
    }

    var systemImage: String {
        switch self {
        case .audio: return "waveform"
        case .video: return "film"
        case .other: return "doc"
        }
    }
}

/// One database row normalized for display and playback.
struct LibraryItem: Hashable, Identifiable {
    var pageID: String
    var databaseID: String
    var title: String
    /// All properties rendered as `name -> display text`, schema order kept
    /// in `propertyOrder`.
    var propertyTexts: [String: String]
    var propertyOrder: [String]
    var mediaFiles: [MediaFileRef]
    var pageURLString: String?
    var createdAt: Date?
    var lastEditedAt: Date?

    var id: String { pageID }
    var pageURL: URL? { pageURLString.flatMap(URL.init(string:)) }

    func displayText(_ mapping: DatabaseMapping) -> String {
        mapping.displayProperties
            .compactMap { propertyTexts[$0] }
            .filter { !$0.isEmpty }
            .joined(separator: " · ")
    }
}

/// What the player actually plays: one media file of one item.
struct QueueEntry: Hashable, Identifiable {
    var item: LibraryItem
    var file: MediaFileRef
    var id: String { "\(item.pageID)|\(file.name)" }
    var progressKey: String { id }
}

// MARK: - SwiftData records

@Model
final class ConnectionRecord {
    @Attribute(.unique) var databaseID: String
    var title: String
    var iconEmoji: String?
    var mappingJSON: String
    var addedAt: Date

    init(databaseID: String, title: String, iconEmoji: String?, mapping: DatabaseMapping) {
        self.databaseID = databaseID
        self.title = title
        self.iconEmoji = iconEmoji
        self.mappingJSON = ConnectionRecord.encode(mapping)
        self.addedAt = Date()
    }

    var mapping: DatabaseMapping {
        get { ConnectionRecord.decode(mappingJSON) }
        set { mappingJSON = ConnectionRecord.encode(newValue) }
    }

    private static func encode(_ mapping: DatabaseMapping) -> String {
        let data = (try? JSONEncoder().encode(mapping)) ?? Data()
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    private static func decode(_ json: String) -> DatabaseMapping {
        if let data = json.data(using: .utf8),
           let mapping = try? JSONDecoder().decode(DatabaseMapping.self, from: data) {
            return mapping
        }
        return DatabaseMapping(mediaProperty: "", titleProperty: "", displayProperties: [])
    }
}

@Model
final class DownloadRecord {
    /// "pageID|fileName"
    @Attribute(.unique) var key: String
    var pageID: String
    var databaseID: String
    var itemTitle: String
    var fileName: String
    /// Path relative to Application Support/Downloads.
    var relativePath: String
    var byteCount: Int64
    var downloadedAt: Date
    var kindRaw: String

    init(key: String, pageID: String, databaseID: String, itemTitle: String,
         fileName: String, relativePath: String, byteCount: Int64, kind: MediaKind) {
        self.key = key
        self.pageID = pageID
        self.databaseID = databaseID
        self.itemTitle = itemTitle
        self.fileName = fileName
        self.relativePath = relativePath
        self.byteCount = byteCount
        self.downloadedAt = Date()
        self.kindRaw = kind.rawValue
    }

    var kind: MediaKind { MediaKind(rawValue: kindRaw) ?? .other }
}

@Model
final class ProgressRecord {
    /// "pageID|fileName"
    @Attribute(.unique) var key: String
    var pageID: String
    var databaseID: String = ""
    var itemTitle: String
    var fileName: String
    var positionSeconds: Double
    var durationSeconds: Double
    var isFinished: Bool
    var isFavorite: Bool
    var lastPlayedAt: Date?

    init(key: String, pageID: String, databaseID: String = "", itemTitle: String, fileName: String) {
        self.key = key
        self.pageID = pageID
        self.databaseID = databaseID
        self.itemTitle = itemTitle
        self.fileName = fileName
        self.positionSeconds = 0
        self.durationSeconds = 0
        self.isFinished = false
        self.isFavorite = false
        self.lastPlayedAt = nil
    }

    var fraction: Double {
        guard durationSeconds > 0 else { return 0 }
        return min(1, max(0, positionSeconds / durationSeconds))
    }
}
