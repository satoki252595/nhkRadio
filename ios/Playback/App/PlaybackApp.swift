import SwiftData
import SwiftUI
import UIKit

/// Bridges background URLSession completion so downloads that finish while
/// the app is suspended are recorded before the system suspends us again.
final class AppDelegate: NSObject, UIApplicationDelegate {
    weak var appState: AppState?

    func application(_ application: UIApplication,
                     handleEventsForBackgroundURLSession identifier: String,
                     completionHandler: @escaping () -> Void) {
        Task { @MainActor in
            self.appState?.downloads.backgroundCompletionHandler = completionHandler
        }
    }
}

@main
struct PlaybackApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var appState = AppState()

    private let container: ModelContainer = {
        let schema = Schema([ConnectionRecord.self, DownloadRecord.self, ProgressRecord.self])
        let configuration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: false)
        do {
            return try ModelContainer(for: schema, configurations: [configuration])
        } catch {
            // Last-resort in-memory store so the app still launches; the
            // failure is surfaced in Settings > About via storeError.
            let memory = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true)
            return try! ModelContainer(for: schema, configurations: [memory])
        }
    }()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(appState)
                .modelContainer(container)
                .task {
                    appDelegate.appState = appState
                    appState.modelContext = container.mainContext
                }
        }
    }
}
