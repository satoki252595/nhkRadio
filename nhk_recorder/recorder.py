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
        成功ならTrue (出力ファイルが作成されていればTrue扱い)

    Note:
        subprocess.run の timeout は ffmpeg を強制 kill しファイル破棄につながるため
        使わない。代わりに Popen + communicate(timeout) で待ち、タイムアウト時は
        SIGTERM で graceful 終了させて、ファイルが残れば成功扱いにする。
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

    # ffmpeg は -t で自然終了するはずだが、HLSセグメント取得遅延等で +N秒程度
    # 余計にかかる場合がある。subprocess を強制 kill するとファイルが残らないため、
    # 余裕を持って (duration + 180s) 待ち、それでも終わらなければ SIGTERM で
    # graceful にクローズしてファイルを残す。
    grace_sec = duration + 180

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        logger.error("ffmpegが見つかりません: %s", ffmpeg_path)
        return False

    try:
        _, stderr = proc.communicate(timeout=grace_sec)
        if proc.returncode == 0:
            logger.info("録音完了: %s", output_path.name)
            return True
        # 非0終了でも、ファイルがあれば部分録音として残す
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.warning(
                "ffmpeg非0終了 (code=%d) だが出力あり、部分録音として保持: %s",
                proc.returncode, output_path.name,
            )
            return True
        logger.error("ffmpegエラー (code=%d): %s", proc.returncode, stderr.decode(errors="replace")[-500:])
        return False
    except subprocess.TimeoutExpired:
        # SIGTERM で graceful 終了 → moov atom を書き込ませる
        logger.warning("録音時間超過 (%ds超)、SIGTERMで graceful 終了します: %s", grace_sec, output_path.name)
        proc.terminate()
        try:
            proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            logger.error("SIGTERM後も終了せず、SIGKILLします: %s", output_path.name)
            proc.kill()
            proc.communicate()
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.info("タイムアウトしたが出力あり、保持: %s", output_path.name)
            return True
        logger.error("録音タイムアウト & 出力なし: %s", output_path.name)
        return False
