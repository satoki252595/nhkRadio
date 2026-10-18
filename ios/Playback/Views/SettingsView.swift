import SwiftData
import SwiftUI

struct SettingsView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \ConnectionRecord.addedAt) private var connections: [ConnectionRecord]
    @Query private var downloadRecords: [DownloadRecord]

    @State private var showConnect = false
    @State private var confirmSignOut = false
    @State private var confirmDeleteDownloads = false

    private var totalBytes: Int64 { downloadRecords.reduce(0) { $0 + $1.byteCount } }

    private var accountLabel: (title: String, detail: String) {
        switch appState.authState {
        case .signedOut:
            return ("サインインしていません", "")
        case .demo:
            return ("デモモード", "アカウントなしでサンプルを再生中")
        case .notion(let workspace, let kind):
            let method = kind == "oauth" ? "Notionでサインイン" : "トークンで接続"
            return (workspace ?? "Notion", method)
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                accountSection
                if !appState.isDemo {
                    connectionsSection
                }
                playbackSection
                storageSection
                aboutSection
            }
            .navigationTitle("設定")
            .sheet(isPresented: $showConnect) {
                ConnectDatabaseView()
            }
            .confirmationDialog("サインアウトしますか？", isPresented: $confirmSignOut,
                                titleVisibility: .visible) {
                Button("サインアウト", role: .destructive) { appState.signOut() }
                Button("キャンセル", role: .cancel) {}
            } message: {
                Text("端末内のトークンは削除されます。ダウンロード済みファイルと再生履歴は残ります。")
            }
            .confirmationDialog("すべてのダウンロードを削除しますか？",
                                isPresented: $confirmDeleteDownloads,
                                titleVisibility: .visible) {
                Button("削除する", role: .destructive) {
                    appState.deleteAllDownloads(records: downloadRecords)
                }
                Button("キャンセル", role: .cancel) {}
            }
        }
    }

    private var accountSection: some View {
        Section("アカウント") {
            HStack(spacing: 12) {
                Image(systemName: "person.crop.circle.fill")
                    .font(.largeTitle)
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text(accountLabel.title).font(.headline)
                    if !accountLabel.detail.isEmpty {
                        Text(accountLabel.detail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            Button(role: .destructive) {
                confirmSignOut = true
            } label: {
                Text(appState.isDemo ? "デモを終了してサインイン" : "サインアウト")
            }
        }
    }

    private var connectionsSection: some View {
        Section {
            ForEach(connections) { connection in
                NavigationLink {
                    MappingEditorView(
                        database: DatabaseRef(id: connection.databaseID,
                                              title: connection.title,
                                              iconEmoji: connection.iconEmoji),
                        existing: connection
                    )
                } label: {
                    HStack(spacing: 10) {
                        Text(connection.iconEmoji ?? "🗂️")
                        VStack(alignment: .leading, spacing: 2) {
                            Text(connection.title)
                            Text("メディア列: \(connection.mapping.mediaProperty)")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                        if appState.selectedDatabaseID == connection.databaseID {
                            Spacer()
                            Image(systemName: "checkmark")
                                .foregroundStyle(Color.accentColor)
                                .font(.caption.bold())
                        }
                    }
                }
            }
            .onDelete { offsets in
                for index in offsets {
                    let connection = connections[index]
                    if appState.selectedDatabaseID == connection.databaseID {
                        appState.selectedDatabaseID = nil
                    }
                    modelContext.delete(connection)
                }
                try? modelContext.save()
            }
            Button {
                showConnect = true
            } label: {
                Label("データベースを追加", systemImage: "plus")
            }
        } header: {
            Text("接続中のデータベース")
        } footer: {
            Text("タップするとメディア列などの対応づけを変更できます。左スワイプで接続を削除できます。")
        }
    }

    private var playbackSection: some View {
        Section {
            Picker("既定の再生速度", selection: rateBinding) {
                ForEach(PlayerEngine.availableRates, id: \.self) { rate in
                    Text(rate == 1.0 ? "1倍速" : String(format: "%g倍速", rate)).tag(rate)
                }
            }
            Picker("リピート", selection: repeatBinding) {
                Text("オフ").tag(RepeatMode.off)
                Text("すべて").tag(RepeatMode.all)
                Text("1件").tag(RepeatMode.one)
            }
        } header: {
            Text("再生")
        } footer: {
            Text("スキップは ±15秒 です。速度とリピートは再生画面からも変更できます。")
        }
    }

    private var rateBinding: Binding<Float> {
        Binding(get: { appState.player.rate }, set: { appState.player.rate = $0 })
    }
    private var repeatBinding: Binding<RepeatMode> {
        Binding(get: { appState.player.repeatMode }, set: { appState.player.repeatMode = $0 })
    }

    private var storageSection: some View {
        Section {
            LabeledContent("ダウンロード", value: "\(downloadRecords.count)件")
            LabeledContent("使用容量", value: ByteFormat.string(totalBytes))
            if !downloadRecords.isEmpty {
                Button(role: .destructive) {
                    confirmDeleteDownloads = true
                } label: {
                    Text("すべてのダウンロードを削除")
                }
            }
        } header: {
            Text("ストレージ")
        } footer: {
            Text("ダウンロードしたファイルはiCloudバックアップの対象外です。")
        }
    }

    private var aboutSection: some View {
        Section("このアプリについて") {
            LabeledContent("バージョン", value: versionString)
            if let commit = Bundle.main.object(forInfoDictionaryKey: "BuildSourceCommit") as? String,
               !commit.isEmpty, commit != "UNSET" {
                LabeledContent("ビルド") {
                    Text(String(commit.prefix(12)))
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
            Link(destination: Config.privacyPolicyURL) {
                Label("プライバシーポリシー", systemImage: "hand.raised")
            }
            Link(destination: Config.supportURL) {
                Label("サポート", systemImage: "questionmark.circle")
            }
            Text("Playback for Notion は独立したサードパーティアプリであり、Notion Labs, Inc. とは提携していません。「Notion」は Notion Labs, Inc. の商標です。")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
    }

    private var versionString: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "-"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "-"
        return "\(version) (\(build))"
    }
}
