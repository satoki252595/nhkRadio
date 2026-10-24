import AVFoundation
import Foundation
import MediaPlayer
import Observation
import UIKit
import UniformTypeIdentifiers

enum MediaPlaybackError: LocalizedError {
    case unsupported(String)
    case unreadable
    case http(Int)
    case missingConnection

    var errorDescription: String? {
        switch self {
        case .unsupported(let name):
            return "「\(name)」の形式はこの端末では対応していません。「設定」→「対応ファイル形式」を確認してください。"
        case .unreadable:
            return "このファイルを開けませんでした。内部の音声・映像形式が未対応、またはファイルが破損している可能性があります。「設定」→「対応ファイル形式」を確認してください。"
        case .http(let status):
            return "音源を取得できませんでした（HTTP \(status)）。リンクの有効期限や共有権限を確認し、ライブラリを更新して再試行してください。"
        case .missingConnection:
            return "元のデータベースの接続設定がありません。「設定」からこの音源のデータベースを再接続してください。"
        }
    }
}

/// Use the device's decoders and the file's bytes, rather than trusting a
/// filename or an upload's Content-Type (older NHK recordings mislabel AAC).
enum PlaybackFormats {
    private static let inspectionSession = URLSession(configuration: .ephemeral)
    static let audioCandidates = ["m4a", "mp3", "aac", "wav", "aif", "aiff", "flac", "caf", "ogg", "opus"]
    static let videoCandidates = ["mp4", "mov", "m4v", "webm", "mkv"]
    private static let nativeExtensions: Set<String> = {
        let types: [UTType]
        if #available(iOS 26.0, *) {
            types = AVURLAsset.audiovisualContentTypes
        } else {
            types = AVURLAsset.audiovisualMIMETypes().compactMap { UTType(mimeType: $0) }
        }
        return Set(types.flatMap { $0.tags[.filenameExtension] ?? [] }.map { $0.lowercased() })
    }()
    static var audioExtensions: [String] { audioCandidates.filter { nativeExtensions.contains($0) } }
    static var videoExtensions: [String] { videoCandidates.filter { nativeExtensions.contains($0) } }
    static func supports(_ name: String) -> Bool {
        let ext = (name as NSString).pathExtension.lowercased()
        return (audioCandidates + videoCandidates).contains(ext) && nativeExtensions.contains(ext)
    }

    static func mimeOverride(header: Data) -> String? {
        let bytes = [UInt8](header)
        if bytes.starts(with: Array("fLaC".utf8)) { return "audio/flac" }
        if bytes.starts(with: Array("caff".utf8)) { return "audio/x-caf" }
        if bytes.count >= 12 {
            if bytes[0..<4].elementsEqual("RIFF".utf8), bytes[8..<12].elementsEqual("WAVE".utf8) { return "audio/wav" }
            if bytes[0..<4].elementsEqual("FORM".utf8),
               bytes[8..<12].elementsEqual("AIFF".utf8) || bytes[8..<12].elementsEqual("AIFC".utf8) { return "audio/aiff" }
        }
        var offset = 0
        while bytes.count >= offset + 10, bytes[offset..<offset + 3].elementsEqual("ID3".utf8) {
            let size = bytes[offset + 6..<offset + 10]
            guard size.allSatisfy({ $0 < 128 }) else { return nil }
            let footer = bytes[offset + 3] == 4 && bytes[offset + 5] & 0x10 != 0 ? 10 : 0
            offset += 10 + size.reduce(0) { ($0 << 7) | Int($1) } + footer
        }
        guard bytes.count >= offset + 2, bytes[offset] == 0xff else { return nil }
        if bytes[offset + 1] & 0xf6 == 0xf0 { return "audio/aac" }
        if bytes[offset + 1] & 0xe0 == 0xe0, bytes[offset + 1] & 0x06 != 0 { return "audio/mpeg" }
        return nil
    }

    static func asset(url: URL, fileName: String) async throws -> AVURLAsset {
        guard supports(fileName) else { throw MediaPlaybackError.unsupported(fileName) }
        var header = Data()
        if MediaKind(fileName: fileName) == .audio {
            // ponytail: inspect at most 64 KiB; larger ID3 tags fall back to
            // AVFoundation's parser instead of downloading a whole recording.
            let limit = 65_536
            if url.isFileURL {
                let file = try FileHandle(forReadingFrom: url)
                defer { try? file.close() }
                header = try file.read(upToCount: limit) ?? Data()
            } else {
                var request = URLRequest(url: url)
                request.timeoutInterval = 20
                request.cachePolicy = .reloadIgnoringLocalCacheData
                request.setValue("bytes=0-\(limit - 1)", forHTTPHeaderField: "Range")
                let (bytes, response) = try await inspectionSession.bytes(for: request)
                defer { bytes.task.cancel() }
                if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
                    throw MediaPlaybackError.http(http.statusCode)
                }
                for try await byte in bytes.prefix(limit) { header.append(byte) }
            }
        }
        let mime = mimeOverride(header: header)
        let asset = AVURLAsset(url: url, options: mime.map { [AVURLAssetOverrideMIMETypeKey: $0] })
        guard try await asset.load(.isPlayable) else { throw MediaPlaybackError.unreadable }
        return asset
    }
}

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
    private(set) var isBuffering = false
    private(set) var playbackFailure: String?
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
    private var itemStatusObserver: NSKeyValueObservation?
    private var playbackStatusObserver: NSKeyValueObservation?
    private var resolutionTask: Task<Void, Never>?

    var isWaiting: Bool { isLoading || isBuffering }

    static let availableRates: [Float] = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
    static let skipForwardSeconds: Double = 15
    static let skipBackwardSeconds: Double = 15

    var currentEntry: QueueEntry? {
        guard let currentIndex, queue.indices.contains(currentIndex) else { return nil }
        return queue[currentIndex]
    }
    var hasMedia: Bool { currentEntry != nil }
    var canGoNext: Bool { nextIndex(after: currentIndex) != nil }
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
        playbackStatusObserver = player.observe(\.timeControlStatus, options: [.new]) { [weak self] _, _ in
            Task { @MainActor in
                guard let self else { return }
                self.isBuffering = self.player.timeControlStatus == .waitingToPlayAtSpecifiedRate
            }
        }
    }

    // MARK: - Queue control

    func play(entry: QueueEntry, in newQueue: [QueueEntry]) {
        guard let index = newQueue.firstIndex(of: entry) else { return }
        playQueue(newQueue, startingAt: index)
    }

    func playQueue(_ entries: [QueueEntry], startingAt index: Int = 0) {
        guard entries.indices.contains(index) else { return }
        saveProgress(finished: false, force: true)
        // Save against the outgoing queue before its indices refer to new entries.
        currentIndex = nil
        queue = entries
        rebuildShuffleOrder()
        start(at: index, autoplay: true)
    }

    func togglePlayPause() {
        if isPlaying {
            pause()
        } else if currentEntry != nil {
            resume()
        }
    }

    func retry() {
        guard let currentIndex else { return }
        start(at: currentIndex, autoplay: true)
    }

    func resume() {
        guard let currentIndex else { return }
        if playbackFailure != nil || (!isLoading && player.currentItem == nil)
            || (duration > 0 && currentTime >= duration) {
            start(at: currentIndex, autoplay: true)
            return
        }
        // A pause during URL resolution must also cancel the pending autoplay.
        isPlaying = true
        guard !isLoading else { return }
        do {
            try activateAudioSession()
        } catch {
            failPlayback(error)
            return
        }
        player.rate = rate
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
        let generation = playbackGeneration
        let item = player.currentItem
        let target = CMTime(seconds: max(0, seconds), preferredTimescale: 600)
        player.seek(to: target, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] finished in
            Task { @MainActor in
                guard let self, finished, self.playbackGeneration == generation,
                      self.player.currentItem === item else { return }
                self.currentTime = self.player.currentTime().seconds
                self.updateNowPlayingInfo()
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
        resolutionTask?.cancel()
        resolutionTask = nil
        saveProgress(finished: false, force: true)
        player.pause()
        player.replaceCurrentItem(with: nil)
        queue = []
        currentIndex = nil
        isPlaying = false
        isLoading = false
        isBuffering = false
        playbackFailure = nil
        lastError = nil
        itemStatusObserver = nil
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
        resolutionTask?.cancel()
        saveProgress(finished: false, force: true)
        player.pause()
        itemStatusObserver = nil
        player.replaceCurrentItem(with: nil)
        currentIndex = index
        let entry = queue[index]
        let savedPosition = resumePositionProvider?(entry)
        isLoading = true
        isBuffering = false
        isPlaying = autoplay
        playbackFailure = nil
        lastError = nil
        currentTime = 0
        duration = 0
        updateNowPlayingInfo()
        resolutionTask = Task { [weak self] in
            guard let self else { return }
            do {
                guard let resolveURL = self.resolveURL else {
                    throw NotionError.network("再生URLのリゾルバが未設定です")
                }
                let url = try await resolveURL(entry)
                // The user may have skipped while resolving; only apply if current.
                guard self.playbackGeneration == generation, self.currentEntry == entry else { return }
                let asset = try await PlaybackFormats.asset(url: url, fileName: entry.file.name)
                let mediaDuration = (try? await asset.load(.duration))?.seconds
                guard self.playbackGeneration == generation, !Task.isCancelled else { return }
                let item = AVPlayerItem(asset: asset)
                item.audioTimePitchAlgorithm = .timeDomain
                self.replaceItem(item)
                self.isLoading = false
                if let mediaDuration, mediaDuration.isFinite, mediaDuration > 0 {
                    self.duration = mediaDuration
                }
                // Old versions could store another track's position here.
                if let resume = savedPosition, resume > 5,
                   self.duration == 0 || resume < self.duration - 1 {
                    self.seek(to: resume)
                }
                if self.isPlaying { self.resume() }
                self.updateNowPlayingInfo()
            } catch {
                guard self.playbackGeneration == generation else { return }
                self.failPlayback(error)
            }
        }
    }

    private func replaceItem(_ item: AVPlayerItem) {
        if let endObserver {
            NotificationCenter.default.removeObserver(endObserver)
        }
        player.replaceCurrentItem(with: item)
        itemStatusObserver = item.observe(\.status, options: [.initial, .new]) { [weak self] item, _ in
            Task { @MainActor in
                guard let self, self.player.currentItem === item, item.status == .failed else { return }
                self.failPlayback(item.error ?? NotionError.network("メディアを読み込めませんでした。"))
            }
        }
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self, weak item] _ in
            Task { @MainActor in
                guard let self, let item, self.player.currentItem === item else { return }
                self.handleItemEnded()
            }
        }
    }

    private func failPlayback(_ error: Error) {
        player.pause()
        isPlaying = false
        isLoading = false
        isBuffering = false
        let detail = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        let networkFailure = sequence(first: error as NSError, next: {
            $0.userInfo[NSUnderlyingErrorKey] as? NSError
        }).prefix(8).contains { $0.domain == NSURLErrorDomain }
        if error is MediaPlaybackError || error is NotionError {
            playbackFailure = detail
        } else if networkFailure {
            playbackFailure = "通信できませんでした。インターネット接続を確認し、再試行してください。\n\(detail)"
        } else {
            playbackFailure = MediaPlaybackError.unreadable.errorDescription
        }
        lastError = playbackFailure
        updateNowPlayingInfo()
    }

    private func handleItemEnded() {
        currentTime = duration
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
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] _ in
            Task { @MainActor in
                guard let self, !self.isLoading, self.player.currentItem != nil else { return }
                let seconds = self.player.currentTime().seconds
                self.currentTime = seconds.isFinite ? seconds : 0
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

    private func activateAudioSession() throws {
        try AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        try AVAudioSession.sharedInstance().setActive(true)
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
