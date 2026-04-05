import logging
import re
import subprocess
from pathlib import Path

from .api import Program

logger = logging.getLogger(__name__)


def make_output_path(output_dir: Path, program: Program) -> Path:
    """録音ファイルのパスを生成する。

    ファイル名例: 20260410_0900_r1_NHK_真打ち競演.m4a
                 20260410_1400_radiko-TBS_JP13_CITY_CHILL_CLUB.m4a

    area を含むことで、並列ジョブ (kanto/kansai) でファイル名が衝突しない。
    """
    safe_title = re.sub(r'[\\/*?:"<>|\s]+', "_", program.title)[:50].rstrip("_")
    # service に "radiko:ABC" のような : が含まれうるのでサニタイズ
    safe_service = re.sub(r'[\\/*?:"<>|\s]+', "-", program.service)
    # area (JP13/JP27/NHK) もサニタイズ
    area = getattr(program, "area", "") or "unknown"
    safe_area = re.sub(r'[\\/*?:"<>|\s]+', "-", area)
    ts = program.start_time.strftime("%Y%m%d_%H%M")
    return output_dir / f"{ts}_{safe_service}_{safe_area}_{safe_title}.m4a"


def record(stream_url: str, duration: int, output_path: Path, ffmpeg_path: str = "ffmpeg") -> bool:
    """ffmpegでストリームを録音する。

    Args:
        stream_url: HLSストリームURL
        duration: 録音時間（秒）
        output_path: 出力ファイルパス
        ffmpeg_path: ffmpegのパス

    Returns:
        成功ならTrue
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_path, "-y",
        "-i", stream_url,
        "-t", str(duration),
        "-c", "copy",
        str(output_path),
    ]

    logger.info("録音開始: %s (%d秒) -> %s", stream_url, duration, output_path.name)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=duration + 120,
        )
        if result.returncode == 0:
            logger.info("録音完了: %s", output_path.name)
            return True
        else:
            logger.error("ffmpegエラー (code=%d): %s", result.returncode, result.stderr.decode(errors="replace")[-500:])
            return False
    except subprocess.TimeoutExpired:
        logger.error("録音タイムアウト: %s", output_path.name)
        return False
    except FileNotFoundError:
        logger.error("ffmpegが見つかりません: %s", ffmpeg_path)
        return False
