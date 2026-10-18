import AuthenticationServices
import SwiftUI

/// First-run experience: value proposition, then three ways in —
/// Notion OAuth (primary), bring-your-own-token (guided), and a demo
/// library that needs no account at all.
struct OnboardingView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.webAuthenticationSession) private var webAuthenticationSession
    @State private var isSigningIn = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    header
                    featureList
                    signInSection
                    Text("Playback for Notion は独立したサードパーティアプリであり、Notion Labs, Inc. とは提携していません。")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .padding(.top, 4)
                }
                .padding(24)
            }
            .background(Color(.systemGroupedBackground))
            .navigationDestination(for: String.self) { destination in
                if destination == "token" {
                    TokenSignInView()
                }
            }
            .alert("サインイン", isPresented: alertBinding) {
                Button("OK") { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: "waveform.circle.fill")
                .font(.system(size: 56))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.tint)
            Text("Playback for Notion")
                .font(.largeTitle.bold())
            Text("Notionのデータベースにある音声・動画を、iPhoneでそのまま再生。ダウンロードすればオフラインでも聴けます。")
                .font(.body)
                .foregroundStyle(.secondary)
        }
    }

    private var featureList: some View {
        VStack(spacing: 14) {
            featureRow("play.circle.fill", "タップで再生",
                       "バックグラウンド再生・ロック画面操作・倍速・スリープタイマー対応")
            featureRow("arrow.down.circle.fill", "オフライン再生",
                       "必要な回だけ選んでダウンロード。容量管理もできます")
            featureRow("tablecells.fill", "どんなデータベースでも",
                       "音声ファイル列を選ぶだけ。その他の列も一覧・詳細で確認できます")
            featureRow("lock.shield.fill", "トークンは端末内だけ",
                       "認証情報はKeychainに保存され、開発者のサーバーには送られません")
        }
    }

    private func featureRow(_ icon: String, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(.tint)
                .frame(width: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }

    private var signInSection: some View {
        VStack(spacing: 12) {
            Button {
                Task { await signInWithOAuth() }
            } label: {
                HStack {
                    if isSigningIn { ProgressView().tint(.white) }
                    Text("Notionでサインイン")
                        .font(.headline)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(isSigningIn)

            if !Config.oauthIsConfigured {
                Text("OAuth接続は準備中です。下のトークン接続、またはデモをご利用ください。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            NavigationLink(value: "token") {
                Label("自分のトークンで接続", systemImage: "key.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)

            Button {
                appState.enterDemoMode()
            } label: {
                Label("デモライブラリで試す（アカウント不要）", systemImage: "play.rectangle.on.rectangle")
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 4)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.tint)
        }
    }

    private var alertBinding: Binding<Bool> {
        Binding(get: { errorMessage != nil }, set: { if !$0 { errorMessage = nil } })
    }

    private func signInWithOAuth() async {
        isSigningIn = true
        defer { isSigningIn = false }
        do {
            let (url, state) = try appState.auth.makeAuthorizeURL()
            let callbackURL = try await webAuthenticationSession.authenticate(
                using: url, callbackURLScheme: Config.oauthCallbackScheme)
            let success = try await appState.auth.completeOAuth(
                callbackURL: callbackURL, expectedState: state)
            appState.completeSignIn(success)
        } catch let error as ASWebAuthenticationSessionError where error.code == .canceledLogin {
            // User cancelled: stay silent.
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

/// Guided bring-your-own-token flow. Steps, a deep link to the Notion
/// connections page, and live validation with friendly Japanese errors.
struct TokenSignInView: View {
    @Environment(AppState.self) private var appState
    @State private var tokenText = ""
    @State private var isValidating = false
    @State private var errorMessage: String?
    @FocusState private var tokenFocused: Bool

    private var looksLikeToken: Bool {
        let trimmed = tokenText.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.hasPrefix("ntn_") || trimmed.hasPrefix("secret_")
    }

    var body: some View {
        Form {
            Section {
                stepRow(1, "Notionの接続（Connection）を作成")
                stepRow(2, "表示されるトークンをコピー")
                stepRow(3, "下の欄に貼り付け")
                stepRow(4, "聴きたいデータベースの「…」メニュー →「接続を追加」で、その接続を許可")
                Link(destination: Config.notionConnectionsURL) {
                    Label("Notionの接続ページを開く", systemImage: "arrow.up.forward.app")
                }
            } header: {
                Text("手順")
            } footer: {
                Text("トークンは端末のKeychainにのみ保存され、Notion API以外へは送信されません。")
            }

            Section("トークン") {
                SecureField("ntn_… / secret_…", text: $tokenText)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($tokenFocused)
                    .font(.body.monospaced())
                if !tokenText.isEmpty && !looksLikeToken {
                    Label("トークンは通常 ntn_ または secret_ で始まります", systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
                if case .some = UIPasteboard.general.string, tokenText.isEmpty {
                    Button {
                        tokenText = UIPasteboard.general.string ?? ""
                    } label: {
                        Label("クリップボードから貼り付け", systemImage: "doc.on.clipboard")
                    }
                }
            }

            if let errorMessage {
                Section {
                    Label(errorMessage, systemImage: "xmark.octagon.fill")
                        .foregroundStyle(.red)
                        .font(.subheadline)
                }
            }

            Section {
                Button {
                    Task { await validate() }
                } label: {
                    HStack {
                        Spacer()
                        if isValidating {
                            ProgressView()
                            Text("確認中…")
                        } else {
                            Text("検証して接続").bold()
                        }
                        Spacer()
                    }
                }
                .disabled(isValidating || tokenText.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .navigationTitle("トークンで接続")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func stepRow(_ number: Int, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text("\(number)")
                .font(.caption.bold())
                .foregroundStyle(.white)
                .frame(width: 20, height: 20)
                .background(Circle().fill(Color.accentColor))
            Text(text).font(.subheadline)
        }
    }

    private func validate() async {
        tokenFocused = false
        isValidating = true
        errorMessage = nil
        defer { isValidating = false }
        do {
            let success = try await appState.auth.signInWithToken(tokenText)
            tokenText = ""
            appState.completeSignIn(success)
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}
