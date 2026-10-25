#!/usr/bin/env python3
"""Render and QA the Playback for Notion promo video (outside the App Store) from a storyboard.

Run inside `nix develop`. Unlike the App Preview (render_app_preview.py), this layout puts a
few short rounded clips of the real app on a plain background and lets the copy lead.
Paths are always explicit on the CLI; the storyboard (JSON) holds timing, layout and copy.

  render_promo_video.py render --board BOARD.json --input SRC --music AUDIO --icon ICON.png --output-dir DIR
  render_promo_video.py qa     --board BOARD.json --input SRC --music AUDIO --icon ICON.png --output-dir DIR

Storyboard keys: name, size, fps, duration, video_bitrate, background{color, glow_color, glow_y},
crop (phone area of the capture), card{w, h, radius}, music{volume, fade_in, fade_out},
clips[{id, in, out, start, x, y, rise}], icon{start, end, size, x, y},
texts[{text, start, end, y, size, font, color, box, boxcolor, boxborderw, rise, x}].
`x` defaults to centred; clip `x` defaults to centred.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_app_preview import (  # noqa: E402  (shared helpers; same flake tools)
    DEFAULT_FONT, contact_sheet, probe, quote, run, sha256, tool_identity,
)

FADE = 0.3


def load_board(path: Path) -> dict:
    board = json.loads(path.read_text(encoding="utf-8"))
    for key in ("name", "size", "duration", "crop", "card", "clips", "texts"):
        if key not in board:
            raise SystemExit(f"storyboard missing {key!r}")
    for clip in board["clips"]:
        if clip["out"] <= clip["in"]:
            raise SystemExit(f"clip {clip['id']}: out must be after in")
        if clip["start"] + clip["out"] - clip["in"] > board["duration"] + 1e-6:
            raise SystemExit(f"clip {clip['id']} runs past the end")
    return board


def window_alpha(start: float, end: float, fade: float = FADE) -> str:
    return (f"if(lt(t,{start}),0,if(lt(t,{start + fade}),(t-{start})/{fade},"
            f"if(gt(t,{end - fade}),max(0,({end}-t)/{fade}),1)))")


def rise_expr(base: str, start: float, rise: float) -> str:
    return f"{base}+{rise}*pow(1-clip((t-{start})/{FADE * 1.6},0,1),2)" if rise else base


def make_still(work: Path, name: str, size: tuple[int, int], fmt: str, expr: dict) -> Path:
    """One-frame PNG from geq expressions (background glow, rounded masks)."""
    out = work / name
    w, h = size
    args = ":".join(f"{k}={quote(v)}" for k, v in expr.items())
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h},format={fmt}",
         "-vf", f"geq={args}", "-frames:v", "1", "-update", "1", str(out)])
    return out


def hex_rgb(color: str) -> tuple[int, int, int]:
    value = color.removeprefix("0x").removeprefix("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rounded_alpha(radius: float) -> str:
    return f"255*clip({radius}+0.5-hypot(X-clip(X,{radius},W-1-{radius}),Y-clip(Y,{radius},H-1-{radius})),0,1)"


def build(board: dict, font: str, work: Path, src: Path, music: Path, icon: Path) -> tuple[list[str], str]:
    width, height = board["size"]
    fps = int(board.get("fps", 30))
    total = float(board["duration"])
    bg = board.get("background", {})
    r, g, b = hex_rgb(bg.get("color", "0x0D0D12"))
    gr, gg, gb = hex_rgb(bg.get("glow_color", "0x2A2870"))
    gy = float(bg.get("glow_y", 0.18)) * height
    # Soft radial glow toward the top: mix base and glow colour by distance.
    k = f"clip(1-hypot((X-W/2)/(W*0.9),(Y-{gy})/(H*0.55)),0,1)"
    background = make_still(work, "background.png", (width, height), "rgb24", {
        "r": f"{r}+({gr}-{r})*pow({k},1.6)", "g": f"{g}+({gg}-{g})*pow({k},1.6)", "b": f"{b}+({gb}-{b})*pow({k},1.6)"})
    card = board["card"]
    card_mask = make_still(work, "card-mask.png", (card["w"], card["h"]), "gray",
                           {"lum": rounded_alpha(card["radius"])})
    icon_cfg = board.get("icon")
    icon_mask = None
    if icon_cfg:
        size = int(icon_cfg["size"])
        icon_mask = make_still(work, "icon-mask.png", (size, size), "gray", {"lum": rounded_alpha(size * 0.2237)})

    inputs = ["-loop", "1", "-framerate", str(fps), "-t", f"{total}", "-i", str(background)]
    chains, index = [], 1
    crop = board["crop"]
    overlays = []
    for clip in board["clips"]:
        length = round(clip["out"] - clip["in"], 3)
        inputs += ["-ss", f"{clip['in']}", "-t", f"{length + 0.5}", "-i", str(src)]
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{length}", "-i", str(card_mask)]
        start = float(clip["start"])
        chains.append(
            f"[{index}:v]setpts=PTS-STARTPTS,fps={fps},crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},"
            f"scale={card['w']}:{card['h']}:flags=lanczos,setsar=1,format=yuva420p,trim=duration={length},"
            f"setpts=PTS-STARTPTS[c{index}];"
            f"[{index + 1}:v]format=gray,trim=duration={length},setpts=PTS-STARTPTS[m{index}];"
            f"[c{index}][m{index}]alphamerge,fade=t=in:st=0:d={FADE}:alpha=1,"
            f"fade=t=out:st={length - FADE}:d={FADE}:alpha=1,setpts=PTS-STARTPTS+{start}/TB[k{index}]"
        )
        x = clip.get("x", (width - card["w"]) / 2)
        y = rise_expr(str(clip["y"]), start, float(clip.get("rise", 40)))
        overlays.append((f"k{index}", x, y, start, start + length))
        index += 2
    if icon_cfg:
        size = int(icon_cfg["size"])
        start, end = float(icon_cfg["start"]), float(icon_cfg["end"])
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{end - start}", "-i", str(icon)]
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{end - start}", "-i", str(icon_mask)]
        chains.append(
            f"[{index}:v]scale={size}:{size}:flags=lanczos,setsar=1,format=yuva420p[ic];"
            f"[{index + 1}:v]format=gray[im];"
            f"[ic][im]alphamerge,fade=t=in:st=0:d={FADE}:alpha=1,setpts=PTS-STARTPTS+{start}/TB[icon]"
        )
        x = icon_cfg.get("x", (width - size) / 2)
        overlays.append(("icon", x, rise_expr(str(icon_cfg["y"]), start, 30), start, end))
        index += 2
    current = "0:v"
    for n, (label, x, y, start, end) in enumerate(overlays):
        out = f"o{n}"
        chains.append(f"[{current}][{label}]overlay=x={x}:y={quote(y)}:eval=frame:eof_action=pass:"
                      f"enable={quote(f'between(t,{start},{end})')}[{out}]")
        current = out
    texts = []
    for n, item in enumerate(board["texts"]):
        text_file = work / f"text-{n:02d}.txt"
        text_file.write_text(item["text"], encoding="utf-8")
        start, end = float(item["start"]), float(item.get("end", total))
        line_font = str(Path(font).with_name(item["font"])) if item.get("font") else font
        opts = [f"fontfile={quote(line_font)}", f"textfile={quote(str(text_file))}",
                f"fontsize={int(item['size'])}", f"fontcolor={item.get('color', 'white')}"]
        if item.get("box"):
            opts += ["box=1", f"boxcolor={item.get('boxcolor', '0x5E5CE6')}",
                     f"boxborderw={item.get('boxborderw', '14|26')}"]
        x = item.get("x", "(w-text_w)/2")
        opts += [f"x={quote(str(x))}", f"y={quote(rise_expr(f'h*{float(item['y'])}', start, float(item.get('rise', 24))))}",
                 f"alpha={quote(window_alpha(start, end))}",
                 f"enable={quote(f'between(t,{start},{end})')}"]
        texts.append("drawtext=" + ":".join(opts))
    fade_out = float(board.get("fade_out_seconds", 0.6))
    tail = texts + [f"fade=t=out:st={total - fade_out}:d={fade_out}", "format=yuv420p", f"trim=duration={total}"]
    chains.append(f"[{current}]" + ",".join(tail) + "[vout]")
    m = board.get("music", {})
    inputs += ["-i", str(music)]
    chains.append(
        f"[{index}:a]atrim=duration={total},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
        f"volume={m.get('volume', 1.0)},afade=t=in:st=0:d={m.get('fade_in', 0.4)},"
        f"afade=t=out:st={total - float(m.get('fade_out', 1.6))}:d={m.get('fade_out', 1.6)},"
        f"apad=whole_dur={total}[aout]"
    )
    return inputs, ";\n".join(chains) + "\n"


def output_names(board: dict) -> dict:
    stem = board["name"]
    return {"video": f"{stem}.mp4", "poster": f"{stem}-poster.png",
            "report_json": f"{stem}-report.json", "report_md": f"{stem}-report.md"}


def render(args: argparse.Namespace) -> None:
    board_path = Path(args.board).resolve()
    board = load_board(board_path)
    out_dir = Path(args.output_dir).resolve()
    work = out_dir / "work" / board["name"]
    work.mkdir(parents=True, exist_ok=True)
    names = output_names(board)
    video = out_dir / names["video"]
    if video.exists() and not args.overwrite:
        raise SystemExit(f"refusing to overwrite {video}; pass --overwrite")
    inputs, graph = build(board, args.font, work, Path(args.input).resolve(), Path(args.music).resolve(),
                          Path(args.icon).resolve())
    graph_file = work / "filtergraph.txt"
    graph_file.write_text(graph, encoding="utf-8")
    bitrate = board.get("video_bitrate", "11M")
    fps = str(board.get("fps", 30))
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *inputs,
         "-/filter_complex", str(graph_file), "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "slow", "-profile:v", "high", "-level:v", "4.0",
         "-pix_fmt", "yuv420p", "-r", fps, "-fps_mode", "cfr",
         "-b:v", bitrate, "-minrate", bitrate, "-maxrate", bitrate, "-bufsize", bitrate, "-x264-params", "nal-hrd=cbr",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
         "-c:a", "aac_at", "-aac_at_mode", "cbr", "-b:a", "256k", "-ar", "48000", "-ac", "2",
         "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart",
         "-t", f"{board['duration']}", str(video)])
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{board.get('poster_seconds', 5.0)}", "-i", str(video),
         "-frames:v", "1", "-update", "1", str(out_dir / names["poster"])])
    qa(args)


def clip_boundaries(board: dict, src: Path, dest: Path, font: str, work: Path) -> list[dict]:
    """Source frames at each clip's in, in+0.1, out-0.1 and out-1f, cropped like the card."""
    crop = board["crop"]
    frame = 1 / float(board.get("fps", 30))
    tiles, records = [], []
    for clip in board["clips"]:
        for label, t in (("in", clip["in"]), ("in+0.1", clip["in"] + 0.1),
                         ("out-0.1", clip["out"] - 0.1), ("out-1f", clip["out"] - frame)):
            tile, text = work / f"b-{clip['id']}-{label}.png", work / f"b-{clip['id']}-{label}.txt"
            text.write_text(f"{clip['id']} {label} {t:.3f}s", encoding="utf-8")
            run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(src), "-vf",
                 f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},scale=240:-2,drawtext=fontfile={quote(font)}:"
                 f"textfile={quote(str(text))}:fontsize=15:fontcolor=yellow:box=1:boxcolor=black@0.8:x=3:y=3",
                 "-frames:v", "1", "-update", "1", str(tile)])
            tiles.append(tile)
            records.append({"clip": clip["id"], "point": label, "source_seconds": round(t, 3), "sha256": sha256(tile)})
    height = probe(tiles[0])["streams"][0]["height"]
    layout = "|".join(f"{c * 240}_{r * height}" for r in range(len(board["clips"])) for c in range(4))
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y"]
    for tile in tiles:
        cmd += ["-i", str(tile)]
    run(cmd + ["-filter_complex", f"xstack=inputs={len(tiles)}:layout={layout}", "-frames:v", "1", "-update", "1", str(dest)])
    for tile in tiles:
        tile.unlink()
    return records


def qa(args: argparse.Namespace) -> None:
    board_path, src = Path(args.board).resolve(), Path(args.input).resolve()
    music, icon = Path(args.music).resolve(), Path(args.icon).resolve()
    board = load_board(board_path)
    out_dir = Path(args.output_dir).resolve()
    names = output_names(board)
    video, poster = out_dir / names["video"], out_dir / names["poster"]
    qa_dir, work = out_dir / "qa" / board["name"], out_dir / "work" / board["name"]
    qa_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    (qa_dir / "ffprobe.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    decode = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-i", str(video), "-map", "0",
                             "-f", "null", "-"], text=True, capture_output=True)
    (qa_dir / "full-decode.log").write_text(decode.stderr or "(no decoder messages)\n", encoding="utf-8")
    counted = json.loads(run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                              "stream=codec_type,nb_read_frames", "-of", "json", str(video)]).stdout)
    frames = {s["codec_type"]: int(s.get("nb_read_frames", 0)) for s in counted["streams"]}
    framemd5 = qa_dir / "timeline-framemd5.txt"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(video), "-map", "0:v", "-f", "framemd5", str(framemd5)])

    def detect(filter_text: str, stream: str) -> list[str]:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-map", stream,
                                 "-af" if stream == "0:a" else "-vf", filter_text, "-f", "null", "-"],
                                text=True, capture_output=True)
        return [line.split("] ", 1)[-1] for line in result.stderr.splitlines()
                if re.search(r"black_start|mean_volume|max_volume|I:|Peak:", line) and "TARGET" not in line]

    # The background is near-black by design, so the strict detector only flags frames
    # that are essentially pure black (luma <= ~2% above floor) on 98% of the picture.
    black = detect("blackdetect=d=0.1:pic_th=0.98:pix_th=0.02", "0:v")
    volume = detect("volumedetect", "0:a")
    loudness = detect("ebur128=peak=true", "0:a")
    contact_sheet(video, qa_dir / "contactsheet-0.5s.jpg", 0.5, 10, args.font)
    boundaries = clip_boundaries(board, src, qa_dir / "source-clip-boundaries.jpg", args.font, work)
    max_volume = next((float(re.search(r"max_volume: (-?[\d.]+)", l).group(1)) for l in volume if "max_volume" in l), 0.0)
    w, h = board["size"]
    checks = {
        "resolution": (v.get("width"), v.get("height")) == (w, h),
        "h264_high_level_le_4.0": v.get("codec_name") == "h264" and v.get("profile") == "High" and int(v.get("level", 99)) <= 40,
        "progressive_yuv420p": v.get("pix_fmt") == "yuv420p" and v.get("field_order", "progressive") == "progressive",
        "fps_30": abs(eval(v.get("avg_frame_rate", "0/1")) - 30) < 1e-6,
        "duration_20_to_30s": 20.0 <= float(info["format"]["duration"]) <= 30.0,
        "audio_aac_256k_48k_stereo": a.get("codec_name") == "aac" and int(a.get("sample_rate", 0)) == 48000
                                     and a.get("channels") == 2 and abs(int(a.get("bit_rate", 0)) - 256000) <= 16000,
        "audio_not_clipping": max_volume <= -1.0,
        "full_decode_clean": decode.returncode == 0 and not decode.stderr.strip(),
        "no_pure_black_segments": not any("black_start" in line for line in black),
        "no_container_metadata_paths": "/Users/" not in json.dumps(info["format"].get("tags", {})),
    }
    status = "PASS_PENDING_HUMAN_REVIEW" if all(checks.values()) else "FAIL"
    try:
        commit = run(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"]).stdout.strip()
    except subprocess.CalledProcessError:
        commit = None
    clips_total = round(sum(c["out"] - c["in"] for c in board["clips"]), 3)
    report = {
        "status": status,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "name": board["name"],
        "target": board.get("target"),
        "footage_provenance": board.get("footage"),
        "outputs": {"video": {"file": names["video"], "bytes": int(info["format"]["size"]), "sha256": sha256(video),
                              "duration_seconds": float(info["format"]["duration"]), "decoded_frames": frames},
                    "poster": {"file": names["poster"], "sha256": sha256(poster), "seconds": board.get("poster_seconds", 5.0)}},
        "inputs": {name: {"file": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)}
                   for name, p in (("source", src), ("music", music), ("icon", icon), ("storyboard", board_path))}
                  | {"script": {"file": Path(__file__).name, "sha256": sha256(Path(__file__).resolve()), "repo_commit": commit},
                     "font_default": {"file": Path(args.font).name, "sha256": sha256(Path(args.font))}},
        "tools": {"ffmpeg": tool_identity("ffmpeg"), "ffprobe": tool_identity("ffprobe")},
        "real_footage_seconds": clips_total,
        "clips": [{k: c[k] for k in ("id", "in", "out", "start")} for c in board["clips"]],
        "texts": [{"text": t["text"], "start": t["start"], "end": t.get("end", board["duration"])} for t in board["texts"]],
        "checks": checks,
        "detectors": {"blackdetect_pix_th_0.02": black, "volumedetect": volume, "ebur128": loudness},
        "source_clip_boundaries": boundaries,
        "qa_files": {p.name: sha256(p) for p in sorted(qa_dir.iterdir()) if p.is_file()},
        "notes": board.get("notes", []),
    }
    (out_dir / names["report_json"]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [f"# Promo video QA — {board['name']}", "", f"- status: **{status}**",
             f"- video: {names['video']} / {report['outputs']['video']['bytes']} bytes / sha256 {report['outputs']['video']['sha256']}",
             f"- duration {report['outputs']['video']['duration_seconds']:.3f}s, decoded frames {frames}",
             f"- real app footage: {clips_total}s in {len(board['clips'])} clips", "", "## Clips", "",
             "| id | source in–out (s) | output start (s) |", "|---|---|---|"]
    lines += [f"| {c['id']} | {c['in']}–{c['out']} | {c['start']} |" for c in board["clips"]]
    lines += ["", "## Copy", "", "| start–end (s) | text |", "|---|---|"]
    lines += [f"| {t['start']}–{t['end']} | {t['text']} |" for t in report["texts"]]
    lines += ["", "## Checks", ""] + [f"- [{'x' if ok else ' '}] {k}" for k, ok in checks.items()]
    lines += ["", "## Detectors", ""] + [f"- {k}: {'; '.join(val) if val else 'none'}" for k, val in report["detectors"].items()]
    lines += ["", "## Notes", ""] + [f"- {n}" for n in report["notes"]]
    (out_dir / names["report_md"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "video": str(video), "checks_failed": [k for k, ok in checks.items() if not ok]},
                     ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "qa"):
        p = sub.add_parser(name)
        for flag in ("--board", "--input", "--music", "--icon", "--output-dir"):
            p.add_argument(flag, required=True)
        p.add_argument("--font", default=os.environ.get("APP_PREVIEW_FONT", DEFAULT_FONT))
        if name == "render":
            p.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    {"render": render, "qa": qa}[args.command](args)


if __name__ == "__main__":
    main()
