import AVKit
import SwiftUI
import UIKit

/// AVPlayerViewController surface for video (system controls + PiP).
struct VideoSurface: UIViewControllerRepresentable {
    let player: AVPlayer

    func makeUIViewController(context: Context) -> AVPlayerViewController {
        let controller = AVPlayerViewController()
        controller.player = player
        controller.allowsPictureInPicturePlayback = true
        controller.canStartPictureInPictureAutomaticallyFromInline = true
        controller.showsPlaybackControls = true
        return controller
    }

    func updateUIViewController(_ controller: AVPlayerViewController, context: Context) {
        if controller.player !== player {
            controller.player = player
        }
    }
}

/// AirPlay route picker.
struct RoutePickerView: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView {
        let view = AVRoutePickerView()
        view.activeTintColor = .systemBlue
        view.tintColor = .secondaryLabel
        view.prioritizesVideoDevices = false
        return view
    }

    func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
}

/// Floating mini player above the tab bar.
struct MiniPlayerView: View {
    @Environment(AppState.self) private var appState
    var onExpand: () -> Void

    private var player: PlayerEngine { appState.player }

    var body: some View {
        if let entry = player.currentEntry {
            VStack(spacing: 0) {
                PlayedProgressBar(fraction: player.progressFraction)
                    .opacity(player.duration > 0 ? 1 : 0)
                HStack(spacing: 12) {
                    ArtworkTile(title: entry.item.title, kind: entry.file.kind, size: 42)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(entry.item.title)
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(1)
                        Text(entry.file.name)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Spacer(minLength: 4)
                    if player.isLoading {
                        ProgressView().controlSize(.small)
                    } else {
                        Button {
                            player.togglePlayPause()
                        } label: {
                            Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                                .font(.title2)
                        }
                        .accessibilityLabel(player.isPlaying ? "一時停止" : "再生")
                    }
                    Button {
                        player.next()
                    } label: {
                        Image(systemName: "forward.end.fill")
                            .font(.title3)
                    }
                    .accessibilityLabel("次へ")
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            }
            .background(.ultraThickMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: .black.opacity(0.16), radius: 12, y: 4)
            .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .onTapGesture { onExpand() }
        }
    }
}

/// Full Now Playing sheet: artwork/video, scrubber, transport, speed,
/// sleep timer, repeat/shuffle, AirPlay and the queue.
struct NowPlayingView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss
    @State private var scrubPosition: Double?
    @State private var showQueue = false

    private var player: PlayerEngine { appState.player }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 22) {
                    mediaSurface
                    titleBlock
                    scrubber
                    transport
                    optionsRow
                    if showQueue { queueList }
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 32)
            }
            .background(Color(.systemGroupedBackground))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("閉じる") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        withAnimation { showQueue.toggle() }
                    } label: {
                        Label("キュー", systemImage: "list.bullet")
                            .labelStyle(.iconOnly)
                    }
                    .tint(showQueue ? Color.accentColor : .secondary)
                }
            }
        }
    }

    @ViewBuilder
    private var mediaSurface: some View {
        if let entry = player.currentEntry {
            if entry.file.kind == .video {
                VideoSurface(player: player.player)
                    .aspectRatio(16 / 9, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .shadow(color: .black.opacity(0.2), radius: 14, y: 6)
            } else if let image = PlayerEngine.artwork(for: entry) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: 300)
                    .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .shadow(color: .black.opacity(0.22), radius: 18, y: 8)
                    .scaleEffect(player.isPlaying ? 1.0 : 0.94)
                    .animation(.spring(response: 0.45, dampingFraction: 0.7), value: player.isPlaying)
                    .padding(.top, 12)
            }
        } else {
            ContentUnavailableView("再生中のメディアはありません", systemImage: "waveform.slash")
                .padding(.top, 60)
        }
    }

    private var titleBlock: some View {
        VStack(spacing: 6) {
            if let entry = player.currentEntry {
                Text(entry.item.title)
                    .font(.title3.bold())
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
                Text(entry.file.name)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                HStack(spacing: 18) {
                    Button {
                        appState.toggleFavorite(entry: entry)
                    } label: {
                        Image(systemName: appState.isFavorite(entry: entry) ? "heart.fill" : "heart")
                            .foregroundStyle(appState.isFavorite(entry: entry) ? Color.pink : Color.secondary)
                    }
                    .accessibilityLabel("お気に入り")
                    DownloadButton(entry: entry)
                }
                .font(.title3)
                .padding(.top, 2)
            }
        }
    }

    private var scrubber: some View {
        VStack(spacing: 6) {
            Slider(
                value: Binding(
                    get: { scrubPosition ?? player.currentTime },
                    set: { scrubPosition = $0 }
                ),
                in: 0...max(player.duration, 1),
                onEditingChanged: { editing in
                    if !editing, let target = scrubPosition {
                        player.seek(to: target)
                        scrubPosition = nil
                    }
                }
            )
            .disabled(player.duration <= 0)
            HStack {
                Text(TimeFormat.clock(scrubPosition ?? player.currentTime))
                Spacer()
                if player.duration > 0 {
                    Text("-\(TimeFormat.clock(player.duration - (scrubPosition ?? player.currentTime)))")
                } else {
                    Text("--:--")
                }
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
        }
    }

    private var transport: some View {
        HStack(spacing: 26) {
            Button { player.previous() } label: {
                Image(systemName: "backward.end.fill").font(.title2)
            }
            .accessibilityLabel("前へ")
            Button { player.skip(by: -PlayerEngine.skipBackwardSeconds) } label: {
                Image(systemName: "gobackward.15").font(.title)
            }
            .accessibilityLabel("15秒戻る")
            Button { player.togglePlayPause() } label: {
                if player.isLoading {
                    ProgressView().controlSize(.large)
                } else {
                    Image(systemName: player.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 64))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(Color.accentColor)
                }
            }
            .accessibilityLabel(player.isPlaying ? "一時停止" : "再生")
            Button { player.skip(by: PlayerEngine.skipForwardSeconds) } label: {
                Image(systemName: "goforward.15").font(.title)
            }
            .accessibilityLabel("15秒進む")
            Button { player.next() } label: {
                Image(systemName: "forward.end.fill").font(.title2)
            }
            .accessibilityLabel("次へ")
        }
        .foregroundStyle(.primary)
    }

    private var optionsRow: some View {
        HStack(spacing: 0) {
            Menu {
                ForEach(PlayerEngine.availableRates, id: \.self) { rate in
                    Button {
                        player.rate = rate
                    } label: {
                        if player.rate == rate {
                            Label(rateLabel(rate), systemImage: "checkmark")
                        } else {
                            Text(rateLabel(rate))
                        }
                    }
                }
            } label: {
                optionLabel(icon: "gauge.with.needle", text: rateLabel(player.rate))
            }

            Menu {
                Button("オフ") { player.setSleepTimer(.off) }
                ForEach([5, 10, 15, 30, 45, 60], id: \.self) { minutes in
                    Button("\(minutes)分後") { player.setSleepTimer(.minutes(minutes)) }
                }
                Button("この曲の終了時") { player.setSleepTimer(.endOfTrack) }
            } label: {
                optionLabel(
                    icon: "moon.zzz",
                    text: player.sleepTimer == .off ? "スリープ" : player.sleepTimer.label,
                    active: player.sleepTimer != .off
                )
            }

            Button { player.cycleRepeatMode() } label: {
                optionLabel(icon: player.repeatMode.systemImage, text: "リピート",
                            active: player.repeatMode != .off)
            }

            Button { player.shuffleEnabled.toggle() } label: {
                optionLabel(icon: "shuffle", text: "シャッフル", active: player.shuffleEnabled)
            }

            RoutePickerView()
                .frame(width: 44, height: 44)
        }
        .frame(maxWidth: .infinity)
    }

    private func optionLabel(icon: String, text: String, active: Bool = false) -> some View {
        VStack(spacing: 3) {
            Image(systemName: icon).font(.title3)
            Text(text).font(.caption2).lineLimit(1)
        }
        .frame(maxWidth: .infinity)
        .foregroundStyle(active ? Color.accentColor : Color.secondary)
        .contentShape(Rectangle())
    }

    private var queueList: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("再生キュー")
                .font(.headline)
                .frame(maxWidth: .infinity, alignment: .leading)
            ForEach(Array(player.queue.enumerated()), id: \.element.id) { index, entry in
                Button {
                    player.play(entry: entry, in: player.queue)
                } label: {
                    HStack(spacing: 10) {
                        if index == player.currentIndex {
                            Image(systemName: "speaker.wave.2.fill")
                                .foregroundStyle(Color.accentColor)
                                .font(.caption)
                        } else {
                            Text("\(index + 1)")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.tertiary)
                                .frame(width: 18)
                        }
                        VStack(alignment: .leading, spacing: 1) {
                            Text(entry.item.title)
                                .font(.subheadline.weight(index == player.currentIndex ? .bold : .regular))
                                .lineLimit(1)
                            Text(entry.file.name)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        Spacer()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Divider()
            }
        }
        .padding()
        .background(Color(.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func rateLabel(_ rate: Float) -> String {
        rate == 1.0 ? "1倍速" : String(format: "%g倍速", rate)
    }
}
