import Foundation

enum AuthError: LocalizedError {
    case oauthNotConfigured
    case invalidState
    case missingCode
    case denied(String)
    case exchangeFailed(Int, String)
    case network(String)
    case emptyToken
    case tokenRejected(String)

    var errorDescription: String? {
        switch self {
        case .oauthNotConfigured:
            return "OAuth接続はまだ有効化されていません（開発者のNotion接続登録待ち）。下の「トークンで接続」をご利用ください。"
        case .invalidState:
            return "認証の検証に失敗しました。もう一度お試しください。"
        case .missingCode:
            return "認可コードを取得できませんでした。もう一度お試しください。"
        case .denied(let detail):
            return "アクセスが許可されませんでした（\(detail)）。"
        case .exchangeFailed(let status, let message):
            return "トークン交換に失敗しました（\(status)）: \(message)"
        case .network(let message):
            return "通信に失敗しました: \(message)"
        case .emptyToken:
            return "トークンが入力されていません。"
        case .tokenRejected(let message):
            return message
        }
    }
}

struct AuthSuccess {
    var workspaceName: String?
    var userName: String?
}

/// Handles OAuth (via the playback-auth Worker) and bring-your-own-token
/// sign-in. Credentials are stored only in the Keychain.
final class AuthService {
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 60
        return URLSession(configuration: config)
    }()

    // MARK: OAuth

    /// Builds the Notion authorization URL and a state value to verify.
    func makeAuthorizeURL() throws -> (url: URL, state: String) {
        guard Config.oauthIsConfigured else { throw AuthError.oauthNotConfigured }
        var bytes = [UInt8](repeating: 0, count: 16)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        let state = bytes.map { String(format: "%02x", $0) }.joined()
        var components = URLComponents(string: "https://api.notion.com/v1/oauth/authorize")!
        components.queryItems = [
            URLQueryItem(name: "owner", value: "user"),
            URLQueryItem(name: "client_id", value: Config.notionClientID),
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "redirect_uri", value: Config.oauthRedirectURI),
            URLQueryItem(name: "state", value: state),
        ]
        return (components.url!, state)
    }

    /// Exchanges the callback URL (received through the custom scheme) for
    /// tokens, storing them in the Keychain.
    func completeOAuth(callbackURL: URL, expectedState: String) async throws -> AuthSuccess {
        let items = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? { items.first(where: { $0.name == name })?.value }
        if let error = value("error") {
            throw AuthError.denied(value("error_description") ?? error)
        }
        guard value("state") == expectedState else { throw AuthError.invalidState }
        guard let code = value("code"), !code.isEmpty else { throw AuthError.missingCode }

        let object = try await postWorker(path: "oauth/exchange", body: [
            "code": code,
            "redirect_uri": Config.oauthRedirectURI,
        ])
        return try storeTokenResponse(object, kind: "oauth")
    }

    /// Refreshes the OAuth access token through the Worker. Returns false
    /// when no refresh token exists or the refresh fails.
    func refreshOAuthToken() async -> Bool {
        guard UserDefaults.standard.string(forKey: CredentialKey.authKind) == "oauth",
              let refresh = Keychain.get(CredentialKey.refreshToken), !refresh.isEmpty else {
            return false
        }
        do {
            let object = try await postWorker(path: "oauth/refresh", body: ["refresh_token": refresh])
            _ = try storeTokenResponse(object, kind: "oauth")
            return true
        } catch {
            return false
        }
    }

    // MARK: Bring your own token

    /// Validates a pasted integration / personal access token against the
    /// Notion API, then stores it in the Keychain.
    func signInWithToken(_ rawToken: String) async throws -> AuthSuccess {
        let token = rawToken.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { throw AuthError.emptyToken }
        let client = NotionClient()
        client.accessTokenProvider = { token }
        do {
            let me = try await client.me()
            Keychain.set(token, for: CredentialKey.accessToken)
            Keychain.remove(CredentialKey.refreshToken)
            UserDefaults.standard.set("token", forKey: CredentialKey.authKind)
            if let workspace = me.workspaceName {
                UserDefaults.standard.set(workspace, forKey: CredentialKey.workspaceName)
            } else {
                UserDefaults.standard.removeObject(forKey: CredentialKey.workspaceName)
            }
            return AuthSuccess(workspaceName: me.workspaceName, userName: me.name)
        } catch let error as NotionError {
            throw AuthError.tokenRejected(error.localizedDescription)
        }
    }

    // MARK: Session

    func signOut() {
        Keychain.remove(CredentialKey.accessToken)
        Keychain.remove(CredentialKey.refreshToken)
        UserDefaults.standard.removeObject(forKey: CredentialKey.authKind)
        UserDefaults.standard.removeObject(forKey: CredentialKey.workspaceName)
    }

    // MARK: Helpers

    private func storeTokenResponse(_ object: NotionParsing.JSONObject, kind: String) throws -> AuthSuccess {
        guard let access = object["access_token"] as? String, !access.isEmpty else {
            throw AuthError.exchangeFailed(200, "access_token が応答に含まれていません")
        }
        Keychain.set(access, for: CredentialKey.accessToken)
        if let refresh = object["refresh_token"] as? String, !refresh.isEmpty {
            Keychain.set(refresh, for: CredentialKey.refreshToken)
        }
        UserDefaults.standard.set(kind, forKey: CredentialKey.authKind)
        let workspace = object["workspace_name"] as? String
        if let workspace {
            UserDefaults.standard.set(workspace, forKey: CredentialKey.workspaceName)
        }
        var userName: String?
        if let owner = object["owner"] as? NotionParsing.JSONObject,
           let user = owner["user"] as? NotionParsing.JSONObject {
            userName = user["name"] as? String
        }
        return AuthSuccess(workspaceName: workspace, userName: userName)
    }

    private func postWorker(path: String, body: [String: Any]) async throws -> NotionParsing.JSONObject {
        var req = URLRequest(url: Config.authWorkerBaseURL.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw AuthError.network(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw AuthError.network("無効な応答です")
        }
        let object = (try? JSONSerialization.jsonObject(with: data)) as? NotionParsing.JSONObject
        guard (200..<300).contains(http.statusCode), let object else {
            let message = (object?["message"] as? String)
                ?? (object?["error"] as? String)
                ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            if object?["error"] as? String == "server_not_configured" {
                throw AuthError.oauthNotConfigured
            }
            throw AuthError.exchangeFailed(http.statusCode, message)
        }
        return object
    }
}
