#!/usr/bin/env python3
"""Render and QA the Playback for Notion App Store App Preview from real app footage.

Run inside `nix develop` so ffmpeg/ffprobe/python come from the project flake.
Inputs and outputs are always explicit; nothing is auto-selected.

  render_app_preview.py sheet  --input SRC --out SHEET.jpg [--start S --duration D --crop x:y:w:h]
  render_app_preview.py render --edl EDL.json --input SRC --output-dir DIR [--font FONT]
  render_app_preview.py qa     --edl EDL.json --input SRC --output-dir DIR   (re-run QA only)

The EDL (JSON) holds cut points, crop, captions and provenance. Unless the EDL
declares footage of the exact target build that was verified on device, the
render is forced into DRAFT mode: a visible watermark, DRAFT in every filename
and status DRAFT_NOT_FOR_UPLOAD in the report.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"

# Apple App Preview specification (App Store Connect Help, "App preview specifications").
SPEC = {
    "url": "https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications/",
    "iphone_portrait": (886, 1920),
    "min_seconds": 15.0,
    "max_seconds": 30.0,
    "max_fps": 30.0,
    "max_bytes": 500 * 1000 * 1000,
    "h264_max_level": 40,
    "audio_sample_rates": (44100, 48000),
    "audio_bitrate": 256000,
}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def quote(value: str) -> str:
    """Quote a filtergraph option value (single quotes cannot be escaped inside)."""
    if "'" in value:
        raise SystemExit(f"single quote not allowed in filter value: {value!r}")
    return f"'{value}'"


def tool_identity(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"{name} not found; run inside `nix develop`")
    resolved = Path(path).resolve()
    version = run([path, "-version"]).stdout.splitlines()[0]
    return {"path": path, "resolved": str(resolved), "sha256": sha256(resolved), "version": version}


def load_edl(path: Path) -> dict:
    edl = json.loads(path.read_text(encoding="utf-8"))
    for key in ("name", "target", "footage", "crop", "segments"):
        if key not in edl:
            raise SystemExit(f"EDL missing {key!r}")
    if not edl["segments"]:
        raise SystemExit("EDL has no segments")
    for seg in edl["segments"]:
        if seg["out"] <= seg["in"]:
            raise SystemExit(f"segment {seg['id']}: out must be after in")
    return edl


def is_draft(edl: dict) -> bool:
    footage, target = edl["footage"], edl["target"]
    exact = (
        str(footage.get("build")) == str(target.get("build"))
        and footage.get("version") == target.get("version")
        and footage.get("verified_on_device") is True
    )
    return edl.get("draft", False) or not exact


def timeline(edl: dict) -> tuple[list[dict], float]:
    """Return per-segment output start times and total duration after dissolves."""
    fade = float(edl.get("transition_seconds", 0.4))
    placed, cursor = [], 0.0
    for index, seg in enumerate(edl["segments"]):
        length = round(seg["out"] - seg["in"], 3)
        start = cursor if index == 0 else cursor - fade
        placed.append({**seg, "length": length, "out_start": round(start, 3), "out_end": round(start + length, 3)})
        cursor = start + length
    return placed, round(cursor, 3)


def output_names(edl: dict, draft: bool) -> dict:
    stem = edl["name"] + ("-DRAFT" if draft else "")
    return {
        "video": f"{stem}.mp4",
        "poster": f"{stem}-poster.png",
        "report_json": f"{stem}-report.json",
        "report_md": f"{stem}-report.md",
    }


# ---------------------------------------------------------------- render

def caption_filters(lines: list[dict], seg_len: float, font: str, work: Path, key: str, style: dict) -> list[str]:
    """drawtext per caption line.

    Optional per-line keys (all default to the original full-segment boxed caption):
    `start`/`end` (seconds within the segment), `font` (file name next to --font),
    `box` (false for bare text), `rise` (px the line drifts up while fading in),
    `shadow` (px offset of a soft black shadow).
    """
    filters = []
    fade = float(style.get("fade_seconds", 0.3))
    for n, line in enumerate(lines):
        text_file = work / f"caption-{key}-{n}.txt"
        text_file.write_text(line["text"], encoding="utf-8")
        size = int(line.get("size", style.get("fontsize", 40)))
        start = float(line.get("start", 0.0))
        end = float(line.get("end", seg_len))
        if start == 0.0 and end == seg_len:
            alpha = f"if(lt(t,{fade}),t/{fade},if(gt(t,{seg_len - fade}),max(0,({seg_len}-t)/{fade}),1))"
        else:
            alpha = (f"if(lt(t,{start}),0,if(lt(t,{start + fade}),(t-{start})/{fade},"
                     f"if(gt(t,{end - fade}),max(0,({end}-t)/{fade}),1)))")
        rise = float(line.get("rise", 0))
        if rise:
            y = f"h*{float(line['y'])}+{rise}*pow(1-clip((t-{start})/{fade * 1.6},0,1),2)"
            y_opt = f"y={quote(y)}"
        else:
            y_opt = f"y=h*{float(line['y'])}"
        line_font = str(Path(font).with_name(line["font"])) if line.get("font") else font
        if not Path(line_font).is_file():
            raise SystemExit(f"font not found: {line_font}")
        opts = [
            f"fontfile={quote(line_font)}",
            f"textfile={quote(str(text_file))}",
            f"fontsize={size}",
            f"fontcolor={line.get('fontcolor', 'white')}",
        ]
        if line.get("box", True):
            opts += [
                "box=1",
                f"boxcolor={line.get('boxcolor', style.get('boxcolor', 'black@0.66'))}",
                f"boxborderw={int(line.get('boxborderw', style.get('boxborderw', 18)))}",
            ]
        if line.get("shadow"):
            opts += [f"shadowcolor={line.get('shadowcolor', 'black@0.55')}",
                     f"shadowx=0", f"shadowy={int(line['shadow'])}"]
        opts += ["x=(w-text_w)/2", y_opt, f"alpha={quote(alpha)}"]
        filters.append("drawtext=" + ":".join(opts))
    return filters


def corner_mask(edl: dict, work: Path) -> Path | None:
    """Black rounded-corner mask (output px) hiding the capture window behind the display's own corners."""
    radius = float(edl.get("corner_radius", 0))
    if radius <= 0:
        return None
    out_w, out_h = edl.get("size", SPEC["iphone_portrait"])
    mask = work / "corner-mask.png"
    alpha = f"255*clip(hypot(X-clip(X,{radius},W-1-{radius}),Y-clip(Y,{radius},H-1-{radius}))-{radius}+0.5,0,1)"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={out_w}x{out_h},format=rgba",
         "-vf", f"geq=r=0:g=0:b=0:a={quote(alpha)}", "-frames:v", "1", "-update", "1", str(mask)])
    return mask


def build_filtergraph(edl: dict, draft: bool, font: str, work: Path, mask: Path | None = None) -> tuple[str, float]:
    out_w, out_h = edl.get("size", SPEC["iphone_portrait"])
    fps = int(edl.get("fps", 30))
    fade = float(edl.get("transition_seconds", 0.4))
    crop = edl["crop"]
    style = edl.get("caption_style", {})
    placed, total = timeline(edl)
    chains = []
    for index, seg in enumerate(placed):
        steps = [
            "setpts=PTS-STARTPTS",
            f"fps={fps}",
            f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}",
            f"scale={out_w}:{out_h}:flags=lanczos",
            "setsar=1",
            "format=yuv420p",
            f"trim=duration={seg['length']}",
            "setpts=PTS-STARTPTS",
        ]
        if seg.get("dim"):
            # Darken the real footage behind a closing title; the app stays visible.
            steps.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{float(seg['dim'])}:t=fill")
        steps += caption_filters(seg.get("captions", []), seg["length"], font, work, seg["id"], style)
        steps.append("settb=AVTB")
        chains.append(f"[{index}:v]" + ",".join(steps) + f"[s{index}]")
    current = "s0"
    for index in range(1, len(placed)):
        label = f"x{index}"
        offset = placed[index]["out_start"]
        chains.append(f"[{current}][s{index}]xfade=transition=fade:duration={fade}:offset={offset}[{label}]")
        current = label
    if mask:
        chains.append(f"[{current}][{len(placed)}:v]overlay=0:0:shortest=1:format=auto,format=yuv420p[masked]")
        current = "masked"
    tail = []
    fade_out = float(edl.get("fade_out_seconds", 0.5))
    if fade_out > 0:
        tail.append(f"fade=t=out:st={total - fade_out}:d={fade_out}")
    if draft:
        text_file = work / "draft-label.txt"
        text_file.write_text(edl.get("draft_label", "DRAFT・公開不可"), encoding="utf-8")
        tail.append(
            "drawtext=" + ":".join([
                f"fontfile={quote(font)}",
                f"textfile={quote(str(text_file))}",
                "fontsize=30",
                "fontcolor=white",
                "box=1",
                "boxcolor=0xC62828@0.92",
                "boxborderw=12",
                "x=(w-text_w)/2",
                "y=h*0.012",
            ])
        )
    tail.append(f"trim=duration={total}")
    chains.append(f"[{current}]" + ",".join(tail) + "[vout]")
    chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={total}[aout]")
    return ";\n".join(chains) + "\n", total


def render(args: argparse.Namespace) -> None:
    edl_path, src, out_dir = Path(args.edl).resolve(), Path(args.input).resolve(), Path(args.output_dir).resolve()
    edl = load_edl(edl_path)
    if edl.get("audio", "silent") != "silent":
        raise SystemExit("only silent audio is supported (no captured/broadcast audio in previews)")
    draft = is_draft(edl)
    names = output_names(edl, draft)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work" / edl["name"]
    work.mkdir(parents=True, exist_ok=True)
    font = args.font
    if not Path(font).is_file():
        raise SystemExit(f"font not found: {font}")
    mask = corner_mask(edl, work)
    graph, total = build_filtergraph(edl, draft, font, work, mask)
    graph_file = work / "filtergraph.txt"
    graph_file.write_text(graph, encoding="utf-8")
    video = out_dir / names["video"]
    if video.exists() and not args.overwrite:
        raise SystemExit(f"refusing to overwrite {video}; pass --overwrite")
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y"]
    for seg in edl["segments"]:
        cmd += ["-ss", f"{seg['in']}", "-t", f"{round(seg['out'] - seg['in'] + 0.5, 3)}", "-i", str(src)]
    if mask:
        cmd += ["-loop", "1", "-framerate", str(edl.get("fps", 30)), "-i", str(mask)]
    bitrate = edl.get("video_bitrate", "11M")
    cmd += [
        "-/filter_complex", str(graph_file),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-profile:v", "high", "-level:v", "4.0",
        "-pix_fmt", "yuv420p", "-r", str(edl.get("fps", 30)), "-fps_mode", "cfr",
        "-b:v", bitrate, "-minrate", bitrate, "-maxrate", bitrate, "-bufsize", bitrate,
        "-x264-params", "nal-hrd=cbr",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        # AudioToolbox CBR keeps Apple's 256 kbps AAC even for the silent track;
        # FFmpeg's native encoder collapses silence to ~2 kbps.
        "-c:a", "aac_at", "-aac_at_mode", "cbr", "-b:a", "256k", "-ar", "48000", "-ac", "2",
        "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart",
        "-t", f"{total}", str(video),
    ]
    run(cmd)
    poster_t = float(edl.get("poster_seconds", 5.0))
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{poster_t}", "-i", str(video),
         "-frames:v", "1", "-update", "1", str(out_dir / names["poster"])])
    qa(args)


# ---------------------------------------------------------------- QA

def probe(path: Path) -> dict:
    return json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]).stdout)


def contact_sheet(video: Path, dest: Path, step: float, columns: int, font: str, offset: float = 0.0,
                  duration: float | None = None, crop: dict | None = None) -> None:
    filters = []
    if crop:
        filters.append(f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}")
    filters += [
        f"fps=1/{step}",
        "scale=160:-2",
        "drawtext=" + ":".join([
            f"fontfile={quote(font)}",
            f"text={quote('%{pts' + chr(92) + ':hms}')}" if offset == 0 else
            f"text={quote('%{eif' + chr(92) + ':t+' + str(offset) + chr(92) + ':d}')}",
            "fontsize=18", "fontcolor=yellow", "box=1", "boxcolor=black@0.8", "x=3", "y=3",
        ]),
    ]
    info = probe(video)
    length = duration if duration is not None else float(info["format"]["duration"])
    rows = max(1, int((length / step + columns - 1) // columns))
    filters.append(f"tile={columns}x{rows}")
    graph = dest.with_suffix(".filter.txt")
    graph.write_text("[0:v]" + ",".join(filters) + "[out]\n", encoding="utf-8")
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y"]
    if offset:
        cmd += ["-ss", str(offset)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-i", str(video), "-/filter_complex", str(graph), "-map", "[out]", "-frames:v", "1", "-update", "1", str(dest)]
    run(cmd)
    graph.unlink()


def boundary_sheet(src: Path, edl: dict, dest: Path, font: str, work: Path) -> list[dict]:
    """Source frames just inside each cut point (in, in+0.1, out-0.1, out-1/fps) cropped like the output."""
    crop = edl["crop"]
    tiles, records = [], []
    for seg in edl["segments"]:
        frame = 1 / float(edl.get("fps", 30))
        for label, t in (("in", seg["in"]), ("in+0.1", seg["in"] + 0.1),
                         ("out-0.1", seg["out"] - 0.1), ("out-1f", seg["out"] - frame)):
            tile = work / f"boundary-{seg['id']}-{label}.png"
            text = work / f"boundary-{seg['id']}-{label}.txt"
            text.write_text(f"{seg['id']} {label} {t:.3f}s", encoding="utf-8")
            vf = ",".join([
                f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}",
                "scale=240:-2",
                "drawtext=" + ":".join([f"fontfile={quote(font)}", f"textfile={quote(str(text))}", "fontsize=15",
                                         "fontcolor=yellow", "box=1", "boxcolor=black@0.8", "x=3", "y=3"]),
            ])
            run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(src),
                 "-vf", vf, "-frames:v", "1", "-update", "1", str(tile)])
            tiles.append(tile)
            records.append({"segment": seg["id"], "point": label, "source_seconds": round(t, 3), "sha256": sha256(tile)})
    inputs = []
    for tile in tiles:
        inputs += ["-i", str(tile)]
    rows = len(edl["segments"])
    height = probe(tiles[0])["streams"][0]["height"]
    layout = "|".join(f"{c * 240}_{r * height}" for r in range(rows) for c in range(4))
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *inputs, "-filter_complex",
         f"xstack=inputs={len(tiles)}:layout={layout}", "-frames:v", "1", "-update", "1", str(dest)])
    for tile in tiles:
        tile.unlink()
    return records


def transition_sheet(video: Path, placed: list[dict], fade: float, dest: Path, work: Path) -> None:
    """Output frames before, inside and after each dissolve."""
    tiles = []
    for seg in placed[1:]:
        for t in (seg["out_start"] - 0.1, seg["out_start"] + fade / 2, seg["out_start"] + fade + 0.1):
            tile = work / f"transition-{len(tiles):03d}.png"
            run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                 "-vf", "scale=200:-2", "-frames:v", "1", "-update", "1", str(tile)])
            tiles.append(tile)
    if not tiles:
        return
    inputs = []
    for tile in tiles:
        inputs += ["-i", str(tile)]
    height = probe(tiles[0])["streams"][0]["height"]
    layout = "|".join(f"{(i % 3) * 200}_{(i // 3) * height}" for i in range(len(tiles)))
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *inputs, "-filter_complex",
         f"xstack=inputs={len(tiles)}:layout={layout}", "-frames:v", "1", "-update", "1", str(dest)])
    for tile in tiles:
        tile.unlink()


def parse_ratio(value: str) -> float:
    num, _, den = value.partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


def qa(args: argparse.Namespace) -> None:
    edl_path, src, out_dir = Path(args.edl).resolve(), Path(args.input).resolve(), Path(args.output_dir).resolve()
    edl = load_edl(edl_path)
    draft = is_draft(edl)
    names = output_names(edl, draft)
    video, poster = out_dir / names["video"], out_dir / names["poster"]
    qa_dir = out_dir / "qa" / edl["name"]
    qa_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work" / edl["name"]
    work.mkdir(parents=True, exist_ok=True)
    font = args.font
    placed, total = timeline(edl)
    fade = float(edl.get("transition_seconds", 0.4))

    info = probe(video)
    (qa_dir / "ffprobe.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    astreams = [s for s in info["streams"] if s["codec_type"] == "audio"]

    decode = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-i", str(video), "-map", "0",
                             "-f", "null", "-"], text=True, capture_output=True)
    (qa_dir / "full-decode.log").write_text(decode.stderr or "(no decoder messages)\n", encoding="utf-8")
    counted = json.loads(run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                              "stream=index,codec_type,nb_read_frames", "-of", "json", str(video)]).stdout)
    frames = {s["codec_type"]: int(s.get("nb_read_frames", 0)) for s in counted["streams"]}

    framemd5 = qa_dir / "timeline-framemd5.txt"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(video), "-map", "0:v", "-f", "framemd5", str(framemd5)])
    hashes = [line.rsplit(",", 1)[1].strip() for line in framemd5.read_text().splitlines() if not line.startswith("#")]
    per_second = {}
    fps = float(edl.get("fps", 30))
    for index, digest in enumerate(hashes):
        per_second.setdefault(int(index / fps), hashlib.sha256()).update(digest.encode())
    timeline_hashes = {str(k): v.hexdigest() for k, v in sorted(per_second.items())}
    (qa_dir / "timeline-per-second-sha256.json").write_text(json.dumps(timeline_hashes, indent=2), encoding="utf-8")

    def detect(filter_text: str, stream: str) -> list[str]:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-map", stream, "-af" if stream == "0:a" else "-vf",
                                 filter_text, "-f", "null", "-"], text=True, capture_output=True)
        return [line for line in result.stderr.splitlines() if re.search(r"black_start|freeze_start|freeze_end|mean_volume|max_volume", line)]

    black = detect("blackdetect=d=0.1:pic_th=0.98", "0:v")
    freeze = detect("freezedetect=n=0.001:d=2", "0:v")
    volume = detect("volumedetect", "0:a")

    contact_sheet(video, qa_dir / "contactsheet-0.5s.jpg", 0.5, 10, font)
    boundaries = boundary_sheet(src, edl, qa_dir / "source-cut-boundaries.jpg", font, work)
    transition_sheet(video, placed, fade, qa_dir / "output-transitions.jpg", work)

    v = vstreams[0] if vstreams else {}
    a = astreams[0] if astreams else {}
    duration = float(info["format"]["duration"])
    size_bytes = int(info["format"]["size"])
    exp_w, exp_h = edl.get("size", SPEC["iphone_portrait"])
    checks = {
        "single_video_stream": len(vstreams) == 1,
        "single_stereo_audio_stream": len(astreams) == 1 and a.get("channels") == 2,
        "resolution_886x1920": (v.get("width"), v.get("height")) == (exp_w, exp_h),
        "codec_h264_high_level_le_4.0": v.get("codec_name") == "h264" and v.get("profile") == "High" and int(v.get("level", 99)) <= SPEC["h264_max_level"],
        "progressive_yuv420p": v.get("pix_fmt") == "yuv420p" and v.get("field_order", "progressive") == "progressive",
        "fps_le_30": 0 < parse_ratio(v.get("avg_frame_rate", "0/1")) <= SPEC["max_fps"] + 1e-6,
        "duration_15_to_30s": SPEC["min_seconds"] <= duration <= SPEC["max_seconds"],
        "size_le_500MB": size_bytes <= SPEC["max_bytes"],
        "audio_aac_256k_44.1or48k": a.get("codec_name") == "aac" and int(a.get("sample_rate", 0)) in SPEC["audio_sample_rates"]
                                     and abs(int(a.get("bit_rate", 0)) - SPEC["audio_bitrate"]) <= 16000,
        "video_bitrate_10_to_12Mbps": 10_000_000 <= int(v.get("bit_rate", 0)) <= 12_500_000,
        "all_streams_default_enabled": all(s.get("disposition", {}).get("default") == 1 for s in info["streams"]),
        "full_decode_clean": decode.returncode == 0 and not decode.stderr.strip(),
        "decoded_video_frames_positive": frames.get("video", 0) > 0,
        "no_black_segments": not any("black_start" in line for line in black),
        "poster_886x1920": poster.exists() and (probe(poster)["streams"][0]["width"], probe(poster)["streams"][0]["height"]) == (exp_w, exp_h),
        "no_container_metadata_paths": "/Users/" not in json.dumps(info["format"].get("tags", {})),
        "silent_audio_by_design": any("max_volume: -91" in line or "max_volume: -inf" in line for line in volume),
    }
    status = "DRAFT_NOT_FOR_UPLOAD" if draft else ("PASS_PENDING_HUMAN_REVIEW" if all(checks.values()) else "FAIL")
    if draft and not all(checks.values()):
        status = "DRAFT_NOT_FOR_UPLOAD_WITH_FAILED_CHECKS"
    try:
        commit = run(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"]).stdout.strip()
    except subprocess.CalledProcessError:
        commit = None
    report = {
        "status": status,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "draft": draft,
        "edl_name": edl["name"],
        "target": edl["target"],
        "footage_provenance": edl["footage"],
        "excluded_intervals": edl.get("excluded_intervals", []),
        "apple_spec": SPEC | {"iphone_portrait": list(SPEC["iphone_portrait"]), "audio_sample_rates": list(SPEC["audio_sample_rates"])},
        "outputs": {
            "video": {"file": names["video"], "bytes": size_bytes, "sha256": sha256(video),
                      "duration_seconds": duration, "decoded_frames": frames},
            "poster": {"file": names["poster"], "sha256": sha256(poster) if poster.exists() else None,
                       "seconds": float(edl.get("poster_seconds", 5.0))},
        },
        "inputs": {
            "source": {"file": src.name, "bytes": src.stat().st_size, "sha256": sha256(src)},
            "edl": {"file": edl_path.name, "sha256": sha256(edl_path)},
            "script": {"file": Path(__file__).name, "sha256": sha256(Path(__file__).resolve()), "repo_commit": commit},
            "font": {"file": Path(font).name, "sha256": sha256(Path(font))},
        },
        "tools": {"ffmpeg": tool_identity("ffmpeg"), "ffprobe": tool_identity("ffprobe"),
                  "python": {"executable": sys.executable, "version": sys.version.split()[0]}},
        "timeline": [{k: s[k] for k in ("id", "in", "out", "length", "out_start", "out_end")} |
                     {"captions": [c["text"] for c in s.get("captions", [])]} for s in placed],
        "total_seconds": total,
        "checks": checks,
        "detectors": {"blackdetect": black, "freezedetect_informational": freeze, "volumedetect": volume},
        "source_cut_boundaries": boundaries,
        "qa_files": {p.name: sha256(p) for p in sorted(qa_dir.iterdir()) if p.is_file()},
        "notes": edl.get("notes", []),
        "remaining_blockers": edl.get("remaining_blockers", []),
    }
    (out_dir / names["report_json"]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / names["report_md"]).write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": status, "video": str(video), "checks_failed": [k for k, ok in checks.items() if not ok]},
                     ensure_ascii=False))


def markdown_report(r: dict) -> str:
    video = r["outputs"]["video"]
    lines = [
        f"# App Preview QA — {r['edl_name']}",
        "",
        f"- status: **{r['status']}**",
        f"- generated_at: {r['generated_at']}",
        f"- target: {r['target']}",
        f"- footage provenance: {r['footage_provenance']}",
        f"- video: {video['file']} / {video['bytes']} bytes / sha256 {video['sha256']}",
        f"- duration {video['duration_seconds']:.3f}s, decoded frames {video['decoded_frames']}",
        f"- poster: {r['outputs']['poster']['file']} at {r['outputs']['poster']['seconds']}s / sha256 {r['outputs']['poster']['sha256']}",
        f"- source: {r['inputs']['source']['file']} / sha256 {r['inputs']['source']['sha256']}",
        f"- script sha256 {r['inputs']['script']['sha256']} (repo HEAD {r['inputs']['script']['repo_commit']})",
        f"- ffmpeg: {r['tools']['ffmpeg']['resolved']} ({r['tools']['ffmpeg']['version']})",
        f"- Apple spec: {r['apple_spec']['url']}",
        "",
        "## Timeline",
        "",
        "| id | source in–out (s) | output (s) | captions |",
        "|---|---|---|---|",
    ]
    for seg in r["timeline"]:
        lines.append(f"| {seg['id']} | {seg['in']}–{seg['out']} | {seg['out_start']}–{seg['out_end']} | {' / '.join(seg['captions'])} |")
    lines += ["", "## Excluded source intervals", ""]
    lines += [f"- {item}" for item in r["excluded_intervals"]] or ["- none"]
    lines += ["", "## Checks", ""]
    lines += [f"- [{'x' if ok else ' '}] {name}" for name, ok in r["checks"].items()]
    lines += ["", "## Detectors", ""]
    for name, found in r["detectors"].items():
        lines.append(f"- {name}: {'; '.join(found) if found else 'none'}")
    lines += ["", "## Notes", ""] + [f"- {n}" for n in r["notes"]]
    lines += ["", "## Remaining blockers", ""] + ([f"- {b}" for b in r["remaining_blockers"]] or ["- none recorded"])
    lines += ["", "## QA files", ""] + [f"- {name}: {digest}" for name, digest in r["qa_files"].items()]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- sheet

def sheet(args: argparse.Namespace) -> None:
    crop = None
    if args.crop:
        x, y, w, h = (int(v) for v in args.crop.split(":"))
        crop = {"x": x, "y": y, "w": w, "h": h}
    contact_sheet(Path(args.input).resolve(), Path(args.out).resolve(), args.step, args.columns, args.font,
                  offset=args.start, duration=args.duration, crop=crop)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "qa"):
        p = sub.add_parser(name)
        p.add_argument("--edl", required=True)
        p.add_argument("--input", required=True)
        p.add_argument("--output-dir", required=True)
        p.add_argument("--font", default=os.environ.get("APP_PREVIEW_FONT", DEFAULT_FONT))
        if name == "render":
            p.add_argument("--overwrite", action="store_true")
    p = sub.add_parser("sheet")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--duration", type=float)
    p.add_argument("--step", type=float, default=1.0)
    p.add_argument("--columns", type=int, default=12)
    p.add_argument("--crop")
    p.add_argument("--font", default=os.environ.get("APP_PREVIEW_FONT", DEFAULT_FONT))
    args = parser.parse_args()
    {"render": render, "qa": qa, "sheet": sheet}[args.command](args)


if __name__ == "__main__":
    main()
