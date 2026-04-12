"""OpenVPN 接続の Python 側管理モジュール。

openvpn を Popen でフォアグラウンド実行し、stderr を threading で
リアルタイム監視して "Initialization Sequence Completed" を検出する。
--log オプションは使わない (GitHub Actions runner で /tmp への書き込みが
不安定だった実績あり)。
"""

import logging
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 現在接続中の openvpn プロセス
_current_proc: subprocess.Popen | None = None


def connect(config_path: Path, wait_sec: int = 45) -> bool:
    """openvpn を起動し、"Initialization Sequence Completed" を待つ。

    stderr をリアルタイムで threading 監視する。

    Returns:
        True: 接続成功
        False: タイムアウトまたはエラー
    """
    global _current_proc
    disconnect()

    cmd = ["sudo", "openvpn", "--config", str(config_path)]

    try:
        _current_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("openvpn 起動失敗: %s", e)
        return False

    # stderr を非同期で読むスレッド
    output_lines: list[str] = []
    connected_event = threading.Event()
    error_event = threading.Event()

    def _reader():
        assert _current_proc is not None and _current_proc.stderr is not None
        try:
            for raw_line in _current_proc.stderr:
                line = raw_line.decode(errors="replace").rstrip()
                output_lines.append(line)
                if "Initialization Sequence Completed" in line:
                    connected_event.set()
                elif "AUTH_FAILED" in line or "Cannot resolve" in line:
                    error_event.set()
        except (ValueError, OSError):
            pass

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    # 待機: connected / error / timeout
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if connected_event.is_set():
            time.sleep(2)  # route 安定化
            logger.info("VPN 接続成功")
            return True
        if error_event.is_set():
            logger.error("openvpn エラー: %s", output_lines[-1] if output_lines else "unknown")
            disconnect()
            return False
        if _current_proc.poll() is not None:
            reader_thread.join(timeout=3)
            logger.error(
                "openvpn が即終了 (code=%d), 出力:\n  %s",
                _current_proc.returncode,
                "\n  ".join(output_lines[-15:]),
            )
            _current_proc = None
            return False
        time.sleep(0.5)

    # タイムアウト
    logger.warning("VPN 接続タイムアウト (%ds), openvpn 出力:", wait_sec)
    for line in output_lines[-15:]:
        logger.warning("  openvpn> %s", line)
    disconnect()
    return False


def disconnect() -> None:
    """openvpn プロセスを停止する。"""
    global _current_proc

    if _current_proc is not None:
        try:
            _current_proc.terminate()
            try:
                _current_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _current_proc.kill()
                _current_proc.wait(timeout=5)
        except OSError:
            pass
        _current_proc = None

    # 念のため残存 openvpn を全停止
    try:
        subprocess.run(
            ["sudo", "pkill", "-TERM", "-x", "openvpn"],
            check=False, capture_output=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        pass
    time.sleep(2)
