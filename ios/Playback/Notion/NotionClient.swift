import Foundation

enum NotionError: LocalizedError {
    case notAuthenticated
    case http(status: Int, message: String)
    case network(String)
    case decoding(String)
    case databaseNotFoundOrNotShared

    var errorDescription: String? {
        switch self {
        case .notAuthenticated:
            return "Notionにサインインしていません。"
        case .http(401, _):
            return "認証に失敗しました。トークンが無効か、権限がありません。「設定」から再接続してください。"
        case .http(403, _):
            return "アクセスが許可されていません。対象ページに接続（Connection）が追加されているか確認してください。"
        case .http(404, _), .databaseNotFoundOrNotShared:
            return "データベースが見つかりません。IDが正しいか、そのデータベースに接続が共有されているか確認してください。"
        case .http(429, _):
            return "Notion APIのレート制限に達しました。少し待ってから再試行してください。"
        case .http(let status, let message):
            return "Notion APIエラー（\(status)）: \(message)"
        case .network(let message):
            return "通信に失敗しました: \(message)"
        case .decoding(let message):
            return "応答を読み取れませんでした: \(message)"
        }
    }
}

/// Thin Notion REST client. Token supply and 401-refresh are injected by
/// AppState so OAuth and bring-your-own-token flows share this code.
final class NotionClient {
    var accessTokenProvider: () -> String? = { Keychain.get(CredentialKey.accessToken) }
    /// Called once on a 401; return true if a fresh token is now available.
    var refreshHandler: () async -> Bool = { false }

    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 60
        return URLSession(configuration: config)
    }()

    // MARK: - Public API

    struct MeInfo {
        var name: String
        var workspaceName: String?
    }

    func me() async throws -> MeInfo {
        let object = try await request(method: "GET", path: "users/me")
        let name = object["name"] as? String ?? "Notionユーザー"
        var workspace: String?
        if let bot = object["bot"] as? NotionParsing.JSONObject {
            workspace = bot["workspace_name"] as? String
        }
        return MeInfo(name: name, workspaceName: workspace)
    }

    func searchDatabases() async throws -> [DatabaseRef] {
        var results: [DatabaseRef] = []
        var cursor: String?
        repeat {
            var body: [String: Any] = [
                "filter": ["value": "database", "property": "object"],
                "page_size": 100,
                "sort": ["direction": "descending", "timestamp": "last_edited_time"],
            ]
            if let cursor { body["start_cursor"] = cursor }
            let object = try await request(method: "POST", path: "search", body: body)
            let items = object["results"] as? [NotionParsing.JSONObject] ?? []
            for item in items {
                guard let id = item["id"] as? String else { continue }
                results.append(DatabaseRef(
                    id: id,
                    title: NotionParsing.databaseTitle(from: item),
                    iconEmoji: NotionParsing.iconEmoji(from: item)
                ))
            }
            cursor = (object["has_more"] as? Bool ?? false) ? object["next_cursor"] as? String : nil
        } while cursor != nil
        return results
    }

    func database(id: String) async throws -> (title: String, iconEmoji: String?, schema: [PropertySchema]) {
        do {
            let object = try await request(method: "GET", path: "databases/\(id)")
            return (
                NotionParsing.databaseTitle(from: object),
                NotionParsing.iconEmoji(from: object),
                NotionParsing.schema(from: object)
            )
        } catch NotionError.http(404, _) {
            throw NotionError.databaseNotFoundOrNotShared
        }
    }

    struct QueryPage {
        var items: [LibraryItem]
        var nextCursor: String?
    }

    func query(databaseID: String, schema: [PropertySchema], mapping: DatabaseMapping,
               cursor: String? = nil, pageSize: Int = 50) async throws -> QueryPage {
        do {
            return try await queryOnce(databaseID: databaseID, schema: schema, mapping: mapping,
                                       cursor: cursor, pageSize: pageSize, useSort: mapping.sortProperty != nil)
        } catch NotionError.http(400, _) where mapping.sortProperty != nil {
            // Some property types cannot be sorted; fall back silently.
            return try await queryOnce(databaseID: databaseID, schema: schema, mapping: mapping,
                                       cursor: cursor, pageSize: pageSize, useSort: false)
        }
    }

    private func queryOnce(databaseID: String, schema: [PropertySchema], mapping: DatabaseMapping,
                           cursor: String?, pageSize: Int, useSort: Bool) async throws -> QueryPage {
        var body: [String: Any] = ["page_size": pageSize]
        if let cursor { body["start_cursor"] = cursor }
        if useSort, let sortProperty = mapping.sortProperty {
            body["sorts"] = [[
                "property": sortProperty,
                "direction": mapping.sortDescending ? "descending" : "ascending",
            ]]
        }
        let object = try await request(method: "POST", path: "databases/\(databaseID)/query", body: body)
        let pages = object["results"] as? [NotionParsing.JSONObject] ?? []
        let items = pages.compactMap {
            NotionParsing.libraryItem(from: $0, schema: schema, mapping: mapping, databaseID: databaseID)
        }
        let next = (object["has_more"] as? Bool ?? false) ? object["next_cursor"] as? String : nil
        return QueryPage(items: items, nextCursor: next)
    }

    /// Re-fetches one page and returns the *current* signed URL for a file,
    /// because Notion file URLs expire about an hour after issue.
    func freshMediaURL(pageID: String, mediaProperty: String, fileName: String) async throws -> URL {
        let object = try await request(method: "GET", path: "pages/\(pageID)")
        guard let properties = object["properties"] as? [String: NotionParsing.JSONObject],
              let value = properties[mediaProperty] else {
            throw NotionError.decoding("メディア列「\(mediaProperty)」が見つかりません")
        }
        let files = NotionParsing.mediaFiles(forPropertyValue: value)
        guard let match = files.first(where: { $0.name == fileName }) ?? files.first,
              let url = URL(string: match.urlString) else {
            throw NotionError.decoding("ファイル「\(fileName)」のURLを取得できません")
        }
        return url
    }

    // MARK: - Transport

    private func request(method: String, path: String,
                         body: [String: Any]? = nil, isRetry: Bool = false) async throws -> NotionParsing.JSONObject {
        guard let token = accessTokenProvider(), !token.isEmpty else {
            throw NotionError.notAuthenticated
        }
        var req = URLRequest(url: Config.notionAPIBaseURL.appendingPathComponent(path))
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue(Config.notionAPIVersion, forHTTPHeaderField: "Notion-Version")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw NotionError.network(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw NotionError.network("無効な応答です")
        }
        if http.statusCode == 401, !isRetry, await refreshHandler() {
            return try await request(method: method, path: path, body: body, isRetry: true)
        }
        guard (200..<300).contains(http.statusCode) else {
            var message = HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            if let object = try? JSONSerialization.jsonObject(with: data) as? NotionParsing.JSONObject,
               let apiMessage = object["message"] as? String {
                message = apiMessage
            }
            throw NotionError.http(status: http.statusCode, message: message)
        }
        guard let object = try? JSONSerialization.jsonObject(with: data) as? NotionParsing.JSONObject else {
            throw NotionError.decoding("JSONオブジェクトではありません")
        }
        return object
    }
}
