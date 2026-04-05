import logging
import re
import subprocess
from pathlib import Path

from .api import Program

logger = logging.getLogger(__name__)


def make_output_path(output_dir: Path, program: Program) -> Path:
    """録音ファイルのパスを生成する。"""
    safe_title = re.sub(r'[\\/*?:"<>|\s]+', "_", program.title)[:50].rstrip("_")
    ts = program.start_time.strftime("%Y%m%d_%H%M")
    return output_dir / f"{ts}_{program.service}_{safe_title}.m4a"


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
