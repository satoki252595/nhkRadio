import AuthenticationServices
import SwiftData
import SwiftUI

/// Step 1: pick a database (search results or pasted URL/ID).
/// Step 2: choose the media column and other mapping, preview, save.
struct ConnectDatabaseView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.modelContext) private var modelContext
    @Environment(\.dismiss) private var dismiss
    @Environment(\.webAuthenticationSession) private var webAuthenticationSession

    @State private var searchResults: [DatabaseRef] = []
    @State private var isSearching = false
    @State private var searchError: String?
    @State private var pasteText = ""
    @State private var pasteError: String?
    @State private var resolvingInput: String?
    @State private var resolvedDatabase: DatabaseRef?
    @State private var needsDatabaseAccess = false
    @State private var isAuthorizing = false

    private var isResolvingPaste: Bool { resolvingInput != nil }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("NotionのデータベースURL または ID", text: $pasteText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .submitLabel(.search)
                        .disabled(isAuthorizing)
                        .onSubmit { Task { await resolvePaste() } }
                        .onChange(of: pasteText) { _, _ in
                            resolvedDatabase = nil
                            pasteError = nil
                            needsDatabaseAccess = false
                        }
                        .task(id: pasteText) {
                            guard NotionID.extract(from: pasteText) != nil else { return }
                            do { try await Task.sleep(for: .milliseconds(350)) }
                            catch { return }
                            await resolvePaste()
                        }
                    if let pasteError {
                        Label(pasteError, systemImage: "xmark.octagon.fill")
                            .foregroundStyle(.red)
                            .font(.caption)
                    }
                    if needsDatabaseAccess {
                        Text("URLは読み取れました。NotionでこのDBをPlaybackに共有し、再検索してください。すでに許可したDBも引き続き使う場合は、認可画面で一緒に選択してください。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if case .notion(_, "oauth") = appState.authState {
                            Button("Notionでアクセスを許可して再検索") {
                                Task { await authorizeAndResolve() }
                            }
                            .disabled(isAuthorizing || isResolvingPaste)
                        } else {
                            Text("Notionの対象DBで「…」→「接続を追加」から、お使いの接続を追加してください。")
                                .font(.caption)
                        }
                    }
                    Button {
                        Task { await resolvePaste() }
                    } label: {
                        HStack {
                            if isResolvingPaste || isAuthorizing { ProgressView().controlSize(.small) }
                            Text("このURL / IDで検索")
                        }
                    }
                    .disabled(pasteText.trimmingCharacters(in: .whitespaces).isEmpty || isResolvingPaste || isAuthorizing)
                    if let database = resolvedDatabase {
                        NavigationLink {
                            MappingEditorView(database: database) { dismiss() }
                        } label: {
                            Label(database.title, systemImage: "tablecells")
                        }
                    }
                } header: {
                    Text("URLまたはIDを貼る")
                } footer: {
                    Text("Notionの「リンクをコピー」で取得したURLをそのまま貼ると自動検索します。app.notion.com・notion.soの共有リンク（ビュー指定付き）に対応しています。")
                }

                Section("アクセス可能なデータベース") {
                    if isSearching {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small)
                            Text("検索中…").foregroundStyle(.secondary)
                        }
                    } else if let searchError {
                        Label(searchError, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                            .font(.subheadline)
                        Button("再試行") { Task { await search() } }
                    } else if searchResults.isEmpty {
                        Text("見つかりませんでした。聴きたいページで「…」→「接続を追加」から、この接続を共有してください。")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Button("再検索") { Task { await search() } }
                    } else {
                        ForEach(searchResults) { database in
                            NavigationLink {
                                MappingEditorView(database: database) { dismiss() }
                            } label: {
                                HStack(spacing: 10) {
                                    Text(database.iconEmoji ?? "🗂️")
                                    Text(database.title)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("データベースを接続")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("キャンセル") { dismiss() }
                }
            }
            .task { await search() }
        }
    }

    private func search() async {
        isSearching = true
        searchError = nil
        defer { isSearching = false }
        do {
            searchResults = try await appState.client.searchDatabases()
        } catch {
            searchError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func resolvePaste() async {
        let input = pasteText
        guard !isAuthorizing, resolvingInput != input else { return }
        pasteError = nil
        resolvedDatabase = nil
        needsDatabaseAccess = false
        guard let id = NotionID.extract(from: input) else {
            pasteError = "URL / IDからデータベースIDを判別できませんでした。"
            return
        }
        resolvingInput = input
        defer { if resolvingInput == input { resolvingInput = nil } }
        do {
            let info = try await appState.client.database(id: id)
            guard pasteText == input, !Task.isCancelled else { return }
            resolvedDatabase = DatabaseRef(id: id, title: info.title, iconEmoji: info.iconEmoji)
        } catch {
            guard pasteText == input, !Task.isCancelled else { return }
            pasteError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            if let error = error as? NotionError {
                switch error {
                case .databaseNotFoundOrNotShared, .http(403, _), .http(404, _):
                    needsDatabaseAccess = true
                default: break
                }
            }
        }
    }

    private func authorizeAndResolve() async {
        isAuthorizing = true
        do {
            let (url, state) = try appState.auth.makeAuthorizeURL()
            let callbackURL = try await webAuthenticationSession.authenticate(
                using: url, callbackURLScheme: Config.oauthCallbackScheme)
            let success = try await appState.auth.completeOAuth(
                callbackURL: callbackURL, expectedState: state)
            appState.completeSignIn(success)
            await search()
            isAuthorizing = false
            await resolvePaste()
        } catch let error as ASWebAuthenticationSessionError where error.code == .canceledLogin {
            isAuthorizing = false
        } catch {
            isAuthorizing = false
            pasteError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

/// Step 2 (also reused to edit an existing connection): media-column
/// picker, display columns, sort, live preview, save.
struct MappingEditorView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.modelContext) private var modelContext
    @Environment(\.dismiss) private var dismiss

    let database: DatabaseRef
    /// Non-nil when editing an existing connection.
    var existing: ConnectionRecord?
    var onSaved: () -> Void = {}

    @State private var schema: [PropertySchema] = []
    @State private var isLoading = true
    @State private var loadError: String?
    @State private var mapping = DatabaseMapping(mediaProperty: "", titleProperty: "", displayProperties: [])
    @State private var previewItems: [LibraryItem] = []
    @State private var isPreviewing = false
    @State private var previewError: String?

    private var filesProperties: [PropertySchema] {
        schema.filter { $0.type == "files" }
    }
    private var canSave: Bool {
        !mapping.mediaProperty.isEmpty && !mapping.titleProperty.isEmpty
    }

    var body: some View {
        Form {
            if isLoading {
                Section {
                    HStack(spacing: 10) {
                        ProgressView().controlSize(.small)
                        Text("列の情報を取得中…").foregroundStyle(.secondary)
                    }
                }
            } else if let loadError {
                Section {
                    Label(loadError, systemImage: "xmark.octagon.fill")
                        .foregroundStyle(.red)
                    Button("再試行") { Task { await loadSchema() } }
                }
            } else {
                mediaSection
                titleSection
                displaySection
                sortSection
                previewSection
            }
        }
        .navigationTitle(database.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("保存") { save() }
                    .disabled(!canSave || isLoading)
                    .bold()
            }
        }
        .task { await loadSchema() }
    }

    private var mediaSection: some View {
        Section {
            if filesProperties.isEmpty {
                Label("ファイル型の列が見つかりません。このデータベースには再生できるメディア列がありません。",
                      systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.subheadline)
            } else {
                Picker("音声・動画ファイルの列", selection: $mapping.mediaProperty) {
                    ForEach(filesProperties) { property in
                        Text(property.name).tag(property.name)
                    }
                }
                .onChange(of: mapping.mediaProperty) { _, _ in Task { await preview() } }
            }
        } header: {
            Text("メディア列")
        } footer: {
            Text("ここで選んだ列のファイルが再生・ダウンロード対象になります。")
        }
    }

    private var titleSection: some View {
        Section("タイトル列") {
            Picker("タイトル列", selection: $mapping.titleProperty) {
                ForEach(schema.filter { $0.type == "title" }) { property in
                    Text(property.name).tag(property.name)
                }
            }
            .onChange(of: mapping.titleProperty) { _, _ in Task { await preview() } }
        }
    }

    private var displaySection: some View {
        Section {
            ForEach(schema.filter { $0.name != mapping.mediaProperty && $0.name != mapping.titleProperty }) { property in
                Toggle(isOn: displayBinding(for: property.name)) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(property.name)
                        Text(propertyTypeLabel(property.type))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
        } header: {
            Text("一覧に表示する列")
        } footer: {
            Text("詳細画面では、ここで選ばなくてもすべての列を確認できます。")
        }
    }

    private var sortSection: some View {
        Section("並び順") {
            Picker("並び替えの列", selection: sortPropertyBinding) {
                Text("指定なし").tag("")
                ForEach(schema.filter { ["date", "created_time", "last_edited_time", "number", "title"].contains($0.type) }) { property in
                    Text(property.name).tag(property.name)
                }
            }
            Picker("方向", selection: $mapping.sortDescending) {
                Text("新しい順").tag(true)
                Text("古い順").tag(false)
            }
            .pickerStyle(.segmented)
        }
    }

    private var previewSection: some View {
        Section {
            if isPreviewing {
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text("読み込み中…").foregroundStyle(.secondary)
                }
            } else if let previewError {
                Label(previewError, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
                    .font(.caption)
            } else if previewItems.isEmpty {
                Text("行がありません（またはメディア列が未選択です）。")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(previewItems.prefix(3)) { item in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                        let detail = item.displayText(mapping)
                        if !detail.isEmpty {
                            Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                        Text(item.mediaFiles.isEmpty
                             ? "⚠️ メディアファイルなし"
                             : "🎧 \(item.mediaFiles.map(\.name).joined(separator: ", "))")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                }
            }
        } header: {
            Text("プレビュー（先頭3行）")
        }
    }

    private var sortPropertyBinding: Binding<String> {
        Binding(
            get: { mapping.sortProperty ?? "" },
            set: { mapping.sortProperty = $0.isEmpty ? nil : $0 }
        )
    }

    private func displayBinding(for name: String) -> Binding<Bool> {
        Binding(
            get: { mapping.displayProperties.contains(name) },
            set: { enabled in
                if enabled {
                    // Keep schema order for display properties.
                    mapping.displayProperties = schema
                        .map(\.name)
                        .filter { mapping.displayProperties.contains($0) || $0 == name }
                } else {
                    mapping.displayProperties.removeAll { $0 == name }
                }
            }
        )
    }

    private func propertyTypeLabel(_ type: String) -> String {
        switch type {
        case "title": return "タイトル"
        case "rich_text": return "テキスト"
        case "select": return "セレクト"
        case "multi_select": return "マルチセレクト"
        case "date": return "日付"
        case "number": return "数値"
        case "files": return "ファイル"
        case "checkbox": return "チェックボックス"
        case "status": return "ステータス"
        case "people": return "ユーザー"
        case "created_time": return "作成日時"
        case "last_edited_time": return "最終更新日時"
        case "url": return "URL"
        case "formula": return "数式"
        case "relation": return "リレーション"
        case "rollup": return "ロールアップ"
        default: return type
        }
    }

    private func loadSchema() async {
        isLoading = true
        loadError = nil
        defer { isLoading = false }
        do {
            let info = try await appState.client.database(id: database.id)
            schema = info.schema
            if let existing {
                mapping = existing.mapping
            } else {
                mapping = DatabaseMapping.suggested(from: info.schema)
            }
            await preview()
        } catch {
            loadError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func preview() async {
        guard canSave else { previewItems = []; return }
        isPreviewing = true
        previewError = nil
        defer { isPreviewing = false }
        do {
            let page = try await appState.client.query(
                databaseID: database.id, schema: schema, mapping: mapping, pageSize: 3)
            previewItems = page.items
        } catch {
            previewError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func save() {
        if let existing {
            existing.mapping = mapping
            existing.title = database.title
            existing.iconEmoji = database.iconEmoji
        } else {
            // Replace any previous record for the same database.
            let id = database.id
            let descriptor = FetchDescriptor<ConnectionRecord>(
                predicate: #Predicate { $0.databaseID == id })
            for old in (try? modelContext.fetch(descriptor)) ?? [] {
                modelContext.delete(old)
            }
            modelContext.insert(ConnectionRecord(
                databaseID: database.id, title: database.title,
                iconEmoji: database.iconEmoji, mapping: mapping))
        }
        try? modelContext.save()
        appState.invalidateSchema(databaseID: database.id)
        appState.selectedDatabaseID = database.id
        onSaved()
        dismiss()
    }
}
