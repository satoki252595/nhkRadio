import Foundation

/// Extracts a Notion object ID from a URL or raw ID string.
enum NotionID {
    static func extract(from text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        // Dashed UUID anywhere in the string.
        if let range = trimmed.range(
            of: "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            options: .regularExpression
        ) {
            return String(trimmed[range]).lowercased()
        }
        // 32 hex chars (Notion URLs embed this form, often after a title slug).
        if let range = trimmed.range(of: "[0-9a-fA-F]{32}", options: .regularExpression) {
            return dashed(String(trimmed[range]))
        }
        return nil
    }

    static func dashed(_ hex32: String) -> String {
        let s = hex32.lowercased()
        guard s.count == 32 else { return s }
        let parts = [
            s.prefix(8),
            s.dropFirst(8).prefix(4),
            s.dropFirst(12).prefix(4),
            s.dropFirst(16).prefix(4),
            s.dropFirst(20).prefix(12),
        ]
        return parts.joined(separator: "-")
    }
}

/// Turns raw Notion API JSON into display values. Works on JSONSerialization
/// dictionaries so every property type can be rendered generically.
enum NotionParsing {
    typealias JSONObject = [String: Any]

    static func plainText(_ richText: Any?) -> String {
        guard let array = richText as? [JSONObject] else { return "" }
        return array.compactMap { $0["plain_text"] as? String }.joined()
    }

    /// Renders one property *value* object (as returned inside a page).
    static func displayString(forPropertyValue value: JSONObject) -> String {
        guard let type = value["type"] as? String else { return "" }
        switch type {
        case "title", "rich_text":
            return plainText(value[type])
        case "select":
            return (value["select"] as? JSONObject)?["name"] as? String ?? ""
        case "multi_select":
            let options = value["multi_select"] as? [JSONObject] ?? []
            return options.compactMap { $0["name"] as? String }.joined(separator: ", ")
        case "status":
            return (value["status"] as? JSONObject)?["name"] as? String ?? ""
        case "date":
            guard let date = value["date"] as? JSONObject,
                  let start = date["start"] as? String else { return "" }
            if let end = date["end"] as? String, !end.isEmpty {
                return "\(formatDate(start)) – \(formatDate(end))"
            }
            return formatDate(start)
        case "number":
            if let n = value["number"] as? NSNumber { return formatNumber(n) }
            return ""
        case "checkbox":
            return (value["checkbox"] as? Bool ?? false) ? "完了" : ""
        case "url", "email", "phone_number":
            return value[type] as? String ?? ""
        case "people":
            let people = value["people"] as? [JSONObject] ?? []
            return people.compactMap { $0["name"] as? String }.joined(separator: ", ")
        case "created_time", "last_edited_time":
            return formatDate(value[type] as? String ?? "")
        case "created_by", "last_edited_by":
            return (value[type] as? JSONObject)?["name"] as? String ?? ""
        case "files":
            let files = value["files"] as? [JSONObject] ?? []
            return files.compactMap { $0["name"] as? String }.joined(separator: ", ")
        case "formula":
            guard let formula = value["formula"] as? JSONObject,
                  let ftype = formula["type"] as? String else { return "" }
            switch ftype {
            case "string": return formula["string"] as? String ?? ""
            case "number":
                return (formula["number"] as? NSNumber).map(formatNumber) ?? ""
            case "boolean": return (formula["boolean"] as? Bool ?? false) ? "はい" : "いいえ"
            case "date":
                let start = (formula["date"] as? JSONObject)?["start"] as? String ?? ""
                return formatDate(start)
            default: return ""
            }
        case "rollup":
            guard let rollup = value["rollup"] as? JSONObject,
                  let rtype = rollup["type"] as? String else { return "" }
            switch rtype {
            case "number": return (rollup["number"] as? NSNumber).map(formatNumber) ?? ""
            case "date":
                let start = (rollup["date"] as? JSONObject)?["start"] as? String ?? ""
                return formatDate(start)
            case "array":
                let items = rollup["array"] as? [JSONObject] ?? []
                return items.map { displayString(forPropertyValue: $0) }
                    .filter { !$0.isEmpty }.joined(separator: ", ")
            default: return ""
            }
        case "relation":
            let relations = value["relation"] as? [JSONObject] ?? []
            return relations.isEmpty ? "" : "\(relations.count)件"
        case "unique_id":
            guard let uid = value["unique_id"] as? JSONObject,
                  let number = uid["number"] as? NSNumber else { return "" }
            let prefix = uid["prefix"] as? String ?? ""
            return prefix.isEmpty ? "\(number)" : "\(prefix)-\(number)"
        default:
            return ""
        }
    }

    /// Extracts media file references from a `files` property value.
    static func mediaFiles(forPropertyValue value: JSONObject) -> [MediaFileRef] {
        guard (value["type"] as? String) == "files",
              let files = value["files"] as? [JSONObject] else { return [] }
        return files.compactMap { entry in
            guard let name = entry["name"] as? String,
                  let kind = entry["type"] as? String else { return nil }
            if kind == "file", let file = entry["file"] as? JSONObject,
               let url = file["url"] as? String {
                return MediaFileRef(name: name, urlString: url, isExternal: false)
            }
            if kind == "external", let external = entry["external"] as? JSONObject,
               let url = external["url"] as? String {
                return MediaFileRef(name: name, urlString: url, isExternal: true)
            }
            return nil
        }
    }

    /// Parses a page object into a LibraryItem using a mapping.
    static func libraryItem(from page: JSONObject, schema: [PropertySchema],
                            mapping: DatabaseMapping, databaseID: String) -> LibraryItem? {
        guard let pageID = page["id"] as? String,
              let properties = page["properties"] as? [String: JSONObject] else { return nil }
        var texts: [String: String] = [:]
        for (name, value) in properties {
            texts[name] = displayString(forPropertyValue: value)
        }
        let order = schema.map(\.name).filter { properties[$0] != nil }
        let title = {
            let raw = texts[mapping.titleProperty] ?? ""
            return raw.isEmpty ? "（無題）" : raw
        }()
        var media: [MediaFileRef] = []
        if let mediaValue = properties[mapping.mediaProperty] {
            media = mediaFiles(forPropertyValue: mediaValue)
        }
        return LibraryItem(
            pageID: pageID,
            databaseID: databaseID,
            title: title,
            propertyTexts: texts,
            propertyOrder: order.isEmpty ? Array(properties.keys.sorted()) : order,
            mediaFiles: media,
            pageURLString: page["url"] as? String,
            createdAt: parseISO(page["created_time"] as? String),
            lastEditedAt: parseISO(page["last_edited_time"] as? String)
        )
    }

    /// Parses the schema list from a database object.
    static func schema(from database: JSONObject) -> [PropertySchema] {
        guard let properties = database["properties"] as? [String: JSONObject] else { return [] }
        return properties
            .map { PropertySchema(name: $0.key, type: $0.value["type"] as? String ?? "") }
            .sorted { $0.name.localizedCompare($1.name) == .orderedAscending }
    }

    static func databaseTitle(from database: JSONObject) -> String {
        let title = plainText(database["title"])
        return title.isEmpty ? "（無題のデータベース）" : title
    }

    static func iconEmoji(from object: JSONObject) -> String? {
        guard let icon = object["icon"] as? JSONObject,
              (icon["type"] as? String) == "emoji" else { return nil }
        return icon["emoji"] as? String
    }

    // MARK: formatting helpers

    private static func formatNumber(_ n: NSNumber) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 2
        return formatter.string(from: n) ?? "\(n)"
    }

    static func parseISO(_ string: String?) -> Date? {
        guard let string, !string.isEmpty else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = withFraction.date(from: string) { return date }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let date = plain.date(from: string) { return date }
        let dateOnly = DateFormatter()
        dateOnly.calendar = Calendar(identifier: .gregorian)
        dateOnly.locale = Locale(identifier: "en_US_POSIX")
        dateOnly.timeZone = TimeZone(secondsFromGMT: 0)
        dateOnly.dateFormat = "yyyy-MM-dd"
        return dateOnly.date(from: String(string.prefix(10)))
    }

    private static func formatDate(_ string: String) -> String {
        guard let date = parseISO(string) else { return string }
        let hasTime = string.contains("T")
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ja_JP")
        formatter.dateStyle = .medium
        formatter.timeStyle = hasTime ? .short : .none
        return formatter.string(from: date)
    }
}
