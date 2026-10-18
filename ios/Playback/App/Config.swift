import Foundation

/// Compile-time configuration. Secrets never live here: the Notion OAuth
/// client secret exists only as a Worker secret, and user tokens live
/// only in the Keychain.
enum Config {
    /// Cloudflare Worker that performs the OAuth code exchange.
    static let authWorkerBaseURL = URL(string: "https://playback-auth.satoki252595.workers.dev")!

    /// OAuth client ID of the Notion public connection. This value is not a
    /// secret. Fill in after registering the public connection, or override
    /// with the NOTION_CLIENT_ID info-plist key / scheme environment.
    static var notionClientID: String {
        if let value = Bundle.main.object(forInfoDictionaryKey: "NOTION_CLIENT_ID") as? String,
           !value.isEmpty, !value.hasPrefix("$(") {
            return value
        }
        return bundledNotionClientID
    }

    /// Public OAuth client ID (safe to ship).
    static let bundledNotionClientID = "3fdd872b-594c-81c5-a259-0037b004178a"

    static var oauthRedirectURI: String {
        authWorkerBaseURL.appendingPathComponent("oauth/callback").absoluteString
    }

    static let oauthCallbackScheme = "playbacknotion"
    static let notionAPIVersion = "2022-06-28"
    static let notionAPIBaseURL = URL(string: "https://api.notion.com/v1")!
    static let notionConnectionsURL = URL(string: "https://app.notion.com/developers/connections")!
    static var privacyPolicyURL: URL { authWorkerBaseURL.appendingPathComponent("privacy") }
    static var supportURL: URL { authWorkerBaseURL.appendingPathComponent("support") }

    static var oauthIsConfigured: Bool { !notionClientID.isEmpty }
}
