import AVFoundation
import Foundation
import MediaPlayer
import Observation
import UIKit

enum RepeatMode: String, CaseIterable {
    case off, all, one
    var systemImage: String {
        switch self {
        case .off, .all: return "repeat"
        case .one: return "repeat.1"
        }
    }
}

enum SleepTimerOption: Equatable {
    case off
    case minutes(Int)
    case endOfTrack

    var label: String {
        switch self {
        case .off: return "オフ"
        case .minutes(let m): return "\(m)分後"
        case .endOfTrack: return "この曲の終了時"
        }
    }
}

/// AVPlayer-based playback engine: queue, background audio, lock-screen
/// controls, speed, skip, resume, repeat/shuffle and a sleep timer.
@MainActor
@Observable
final class PlayerEngine {
    // Injected by AppState.
    var resolveURL: ((QueueEntry) async throws -> URL)?
    var progressHandler: ((QueueEntry, Double, Double, Bool) -> Void)?
    var resumePositionProvider: ((QueueEntry) -> Double?)?
    var favoriteProvider: ((QueueEntry) -> Bool)?

    private(set) var queue: [QueueEntry] = []
    private(set) var currentIndex: Int?
    private(set) var isPlaying = false
    private(set) var isLoading = false
    private(set) var currentTime: Double = 0
    private(set) var duration: Double = 0
    var lastError: String?

    var rate: Float {
        didSet {
            UserDefaults.standard.set(rate, forKey: "player.rate")
            if isPlaying { player.rate = rate }
            updateNowPlayingInfo()
        }
    }
    var repeatMode: RepeatMode = .off {
        didSet { UserDefaults.standard.set(repeatMode.rawValue, forKey: "player.repeatMode") }
    }
    var shuffleEnabled = false {
        didSet { rebuildShuffleOrder() }
    }
    private(set) var sleepTimer: SleepTimerOption = .off

    let player = AVPlayer()
    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?
    private var sleepTimerTask: Task<Void, Never>?
    private var shuffledOrder: [Int] = []
    private var wasPlayingBeforeInterruption = false
    private var lastProgressSave = Date.distantPast
    private var playbackGeneration = UUID()

    static let availableRates: [Float] = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
    static let skipForwardSeconds: Double = 15
    static let skipBackwardSeconds: Double = 15

    var currentEntry: QueueEntry? {
        guard let currentIndex, queue.indices.contains(currentIndex) else { return nil }
        return queue[currentIndex]
    }
    var hasMedia: Bool { currentEntry != nil }
    var progressFraction: Double { duration > 0 ? min(1, currentTime / duration) : 0 }

    init() {
        let storedRate = UserDefaults.standard.float(forKey: "player.rate")
        self.rate = storedRate == 0 ? 1.0 : storedRate
        if let raw = UserDefaults.standard.string(forKey: "player.repeatMode"),
           let mode = RepeatMode(rawValue: raw) {
            self.repeatMode = mode
        }
        player.automaticallyWaitsToMinimizeStalling = true
        configureAudioSession()
        configureRemoteCommands()
        observeTime()
        observeInterruptions()
    }

    // MARK: - Queue control

    func play(entry: QueueEntry, in newQueue: [QueueEntry]) {
        queue = newQueue
        rebuildShuffleOrder()
        if let index = newQueue.firstIndex(of: entry) {
            start(at: index, autoplay: true)
        }
    }

    func playQueue(_ entries: [QueueEntry], startingAt index: Int = 0) {
        queue = entries
        rebuildShuffleOrder()
        guard entries.indices.contains(index) else { return }
        start(at: index, autoplay: true)
    }

    func togglePlayPause() {
        if isPlaying {
            pause()
        } else if currentEntry != nil {
            resume()
        }
    }

    func resume() {
        activateAudioSession()
        player.rate = rate
        isPlaying = true
        updateNowPlayingInfo()
    }

    func pause() {
        player.pause()
        isPlaying = false
        saveProgress(finished: false, force: true)
        updateNowPlayingInfo()
    }

    func next() {
        guard let nextIndex = nextIndex(after: currentIndex) else { return }
        start(at: nextIndex, autoplay: true)
    }

    func previous() {
        // Restart the track when more than 3 seconds in, like most players.
        if currentTime > 3 {
            seek(to: 0)
            return
        }
        guard let previousIndex = previousIndex(before: currentIndex) else {
            seek(to: 0)
            return
        }
        start(at: previousIndex, autoplay: true)
    }

    func seek(to seconds: Double) {
        let target = CMTime(seconds: max(0, seconds), preferredTimescale: 600)
        player.seek(to: target, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] _ in
            Task { @MainActor in
                self?.currentTime = max(0, seconds)
                self?.updateNowPlayingInfo()
            }
        }
    }

    func skip(by delta: Double) {
        seek(to: currentTime + delta)
    }

    func cycleRepeatMode() {
        switch repeatMode {
        case .off: repeatMode = .all
        case .all: repeatMode = .one
        case .one: repeatMode = .off
        }
    }

    func setSleepTimer(_ option: SleepTimerOption) {
        sleepTimer = option
        sleepTimerTask?.cancel()
        sleepTimerTask = nil
        if case .minutes(let minutes) = option {
            sleepTimerTask = Task { [weak self] in
                try? await Task.sleep(for: .seconds(minutes * 60))
                guard !Task.isCancelled else { return }
                self?.pause()
                self?.sleepTimer = .off
            }
        }
    }

    func stop() {
        playbackGeneration = UUID()
        saveProgress(finished: false, force: true)
        player.pause()
        player.replaceCurrentItem(with: nil)
        queue = []
        currentIndex = nil
        isPlaying = false
        isLoading = false
        currentTime = 0
        duration = 0
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
    }

    func invalidateLocalFile(_ url: URL, progressKey: String) {
        if (isLoading && currentEntry?.progressKey == progressKey)
            || (player.currentItem?.asset as? AVURLAsset)?.url == url {
            stop()
        }
    }

    // MARK: - Internals

    private func start(at index: Int, autoplay: Bool) {
        guard queue.indices.contains(index) else { return }
        let generation = UUID()
        playbackGeneration = generation
        saveProgress(finished: false, force: true)
        currentIndex = index
        let entry = queue[index]
        isLoading = true
        lastError = nil
        currentTime = 0
        duration = 0
        Task { [weak self] in
            guard let self else { return }
            do {
                guard let resolveURL = self.resolveURL else {
                    throw NotionError.network("再生URLのリゾルバが未設定です")
                }
                let url = try await resolveURL(entry)
                // The user may have skipped while resolving; only apply if current.
                guard self.playbackGeneration == generation, self.currentEntry == entry else { return }
                let item = AVPlayerItem(url: url)
                item.audioTimePitchAlgorithm = .timeDomain
                self.replaceItem(item)
                self.isLoading = false
                if let resume = self.resumePositionProvider?(entry), resume > 5 {
                    self.seek(to: resume)
                }
                if autoplay { self.resume() }
                self.updateNowPlayingInfo()
            } catch {
                guard self.playbackGeneration == generation else { return }
                self.isLoading = false
                self.lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    private func replaceItem(_ item: AVPlayerItem) {
        if let endObserver {
            NotificationCenter.default.removeObserver(endObserver)
        }
        player.replaceCurrentItem(with: item)
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.handleItemEnded() }
        }
    }

    private func handleItemEnded() {
        saveProgress(finished: true, force: true)
        if sleepTimer == .endOfTrack {
            sleepTimer = .off
            isPlaying = false
            updateNowPlayingInfo()
            return
        }
        if repeatMode == .one, let currentIndex {
            start(at: currentIndex, autoplay: true)
            return
        }
        if let next = nextIndex(after: currentIndex) {
            start(at: next, autoplay: true)
        } else if repeatMode == .all, !queue.isEmpty {
            start(at: orderedIndices.first ?? 0, autoplay: true)
        } else {
            isPlaying = false
            currentTime = duration
            updateNowPlayingInfo()
        }
    }

    private var orderedIndices: [Int] {
        shuffleEnabled && !shuffledOrder.isEmpty ? shuffledOrder : Array(queue.indices)
    }

    private func rebuildShuffleOrder() {
        guard shuffleEnabled else { shuffledOrder = []; return }
        var indices = Array(queue.indices)
        if let currentIndex, indices.contains(currentIndex) {
            indices.removeAll { $0 == currentIndex }
            indices.shuffle()
            shuffledOrder = [currentIndex] + indices
        } else {
            shuffledOrder = indices.shuffled()
        }
    }

    private func nextIndex(after index: Int?) -> Int? {
        guard let index else { return orderedIndices.first }
        let order = orderedIndices
        guard let position = order.firstIndex(of: index), position + 1 < order.count else { return nil }
        return order[position + 1]
    }

    private func previousIndex(before index: Int?) -> Int? {
        guard let index else { return nil }
        let order = orderedIndices
        guard let position = order.firstIndex(of: index), position > 0 else { return nil }
        return order[position - 1]
    }

    private func observeTime() {
        let interval = CMTime(seconds: 0.5, preferredTimescale: 600)
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] time in
            Task { @MainActor in
                guard let self else { return }
                self.currentTime = time.seconds.isFinite ? time.seconds : 0
                if let d = self.player.currentItem?.duration.seconds, d.isFinite, d > 0 {
                    self.duration = d
                }
                self.saveProgress(finished: false, force: false)
            }
        }
    }

    private func saveProgress(finished: Bool, force: Bool) {
        guard let entry = currentEntry, duration > 0 else { return }
        if !force, Date().timeIntervalSince(lastProgressSave) < 5 { return }
        lastProgressSave = Date()
        let done = finished || (duration > 0 && currentTime >= duration - 1)
        progressHandler?(entry, done ? duration : currentTime, duration, done)
    }

    // MARK: - Audio session / remote controls / Now Playing

    private func configureAudioSession() {
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
    }

    private func activateAudioSession() {
        try? AVAudioSession.sharedInstance().setActive(true)
    }

    private func observeInterruptions() {
        NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            guard let info = notification.userInfo,
                  let raw = info[AVAudioSessionInterruptionTypeKey] as? UInt,
                  let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
            Task { @MainActor in
                guard let self else { return }
                switch type {
                case .began:
                    self.wasPlayingBeforeInterruption = self.isPlaying
                    self.player.pause()
                    self.isPlaying = false
                case .ended:
                    let optionsRaw = info[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
                    let options = AVAudioSession.InterruptionOptions(rawValue: optionsRaw)
                    if options.contains(.shouldResume), self.wasPlayingBeforeInterruption {
                        self.resume()
                    }
                @unknown default:
                    break
                }
                self.updateNowPlayingInfo()
            }
        }
    }

    private func configureRemoteCommands() {
        let center = MPRemoteCommandCenter.shared()
        center.playCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.resume() }
            return .success
        }
        center.pauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.pause() }
            return .success
        }
        center.togglePlayPauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.togglePlayPause() }
            return .success
        }
        center.nextTrackCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.next() }
            return .success
        }
        center.previousTrackCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.previous() }
            return .success
        }
        center.skipForwardCommand.preferredIntervals = [NSNumber(value: Self.skipForwardSeconds)]
        center.skipForwardCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.skip(by: Self.skipForwardSeconds) }
            return .success
        }
        center.skipBackwardCommand.preferredIntervals = [NSNumber(value: Self.skipBackwardSeconds)]
        center.skipBackwardCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.skip(by: -Self.skipBackwardSeconds) }
            return .success
        }
        center.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackPositionCommandEvent else { return .commandFailed }
            Task { @MainActor in self?.seek(to: event.positionTime) }
            return .success
        }
        center.changePlaybackRateCommand.supportedPlaybackRates = Self.availableRates.map { NSNumber(value: $0) }
        center.changePlaybackRateCommand.addTarget { [weak self] event in
            guard let event = event as? MPChangePlaybackRateCommandEvent else { return .commandFailed }
            Task { @MainActor in self?.rate = event.playbackRate }
            return .success
        }
    }

    func updateNowPlayingInfo() {
        guard let entry = currentEntry else {
            MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
            return
        }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: entry.item.title,
            MPMediaItemPropertyArtist: entry.file.name,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: currentTime,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? Double(rate) : 0,
            MPNowPlayingInfoPropertyIsLiveStream: false,
        ]
        if duration > 0 {
            info[MPMediaItemPropertyPlaybackDuration] = duration
        }
        info[MPMediaItemPropertyMediaType] = entry.file.kind == .video
            ? MPNowPlayingInfoMediaType.video.rawValue
            : MPNowPlayingInfoMediaType.audio.rawValue
        if let artwork = Self.artwork(for: entry) {
            info[MPMediaItemPropertyArtwork] = MPMediaItemArtwork(boundsSize: artwork.size) { _ in artwork }
        }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    /// Generated placeholder artwork so the lock screen always looks complete.
    private static var artworkCache: [String: UIImage] = [:]
    static func artwork(for entry: QueueEntry) -> UIImage? {
        artwork(title: entry.item.title, kind: entry.file.kind)
    }

    static func artwork(title: String, kind: MediaKind) -> UIImage? {
        let key = "\(title)|\(kind.rawValue)"
        if let cached = artworkCache[key] { return cached }
        let size = CGSize(width: 512, height: 512)
        let renderer = UIGraphicsImageRenderer(size: size)
        let image = renderer.image { context in
            let hue = CGFloat(abs(title.hashValue) % 360) / 360.0
            let start = UIColor(hue: hue, saturation: 0.55, brightness: 0.35, alpha: 1)
            let end = UIColor(hue: fmod(hue + 0.12, 1.0), saturation: 0.65, brightness: 0.18, alpha: 1)
            let gradient = CGGradient(
                colorsSpace: CGColorSpaceCreateDeviceRGB(),
                colors: [start.cgColor, end.cgColor] as CFArray,
                locations: [0, 1]
            )!
            context.cgContext.drawLinearGradient(
                gradient,
                start: .zero,
                end: CGPoint(x: size.width, y: size.height),
                options: []
            )
            let symbolName = kind == .video ? "film.fill" : "waveform"
            let config = UIImage.SymbolConfiguration(pointSize: 180, weight: .regular)
            if let symbol = UIImage(systemName: symbolName, withConfiguration: config)?
                .withTintColor(.white.withAlphaComponent(0.9), renderingMode: .alwaysOriginal) {
                let origin = CGPoint(
                    x: (size.width - symbol.size.width) / 2,
                    y: (size.height - symbol.size.height) / 2
                )
                symbol.draw(at: origin)
            }
        }
        artworkCache[key] = image
        return image
    }
}
