import SwiftData
import SwiftUI

struct RootView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.modelContext) private var modelContext
    @State private var showNowPlaying = false
    @State private var selectedTab = 0

    var body: some View {
        Group {
            if appState.authState == .signedOut {
                OnboardingView()
            } else {
                mainTabs
            }
        }
        .task { appState.modelContext = modelContext }
    }

    private var mainTabs: some View {
        TabView(selection: $selectedTab) {
            LibraryView()
                .safeAreaInset(edge: .bottom) { miniPlayer }
                .tabItem { Label("ライブラリ", systemImage: "music.note.list") }
                .tag(0)
            DownloadsView()
                .safeAreaInset(edge: .bottom) { miniPlayer }
                .tabItem { Label("ダウンロード", systemImage: "arrow.down.circle") }
                .tag(1)
            HistoryView()
                .safeAreaInset(edge: .bottom) { miniPlayer }
                .tabItem { Label("履歴", systemImage: "clock.arrow.circlepath") }
                .tag(2)
            SettingsView()
                .safeAreaInset(edge: .bottom) { miniPlayer }
                .tabItem { Label("設定", systemImage: "gearshape") }
                .tag(3)
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.85), value: appState.player.hasMedia)
        .sheet(isPresented: $showNowPlaying) {
            NowPlayingView()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .alert("再生エラー", isPresented: errorBinding) {
            Button("OK") { appState.player.lastError = nil }
        } message: {
            Text(appState.player.lastError ?? "")
        }
        .alert("ダウンロード", isPresented: downloadErrorBinding) {
            Button("OK") { appState.downloads.lastError = nil }
        } message: {
            Text(appState.downloads.lastError ?? "")
        }
    }

    @ViewBuilder
    private var miniPlayer: some View {
        if appState.player.hasMedia {
            MiniPlayerView { showNowPlaying = true }
                .padding(.horizontal, 10)
                .padding(.bottom, 2)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { appState.player.lastError != nil },
            set: { if !$0 { appState.player.lastError = nil } }
        )
    }

    private var downloadErrorBinding: Binding<Bool> {
        Binding(
            get: { appState.downloads.lastError != nil },
            set: { if !$0 { appState.downloads.lastError = nil } }
        )
    }
}
