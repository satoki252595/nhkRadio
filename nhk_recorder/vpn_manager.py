"""OpenVPN 接続の Python 側管理モジュール。

openvpn を Popen でフォアグラウンド実行し、stderr を threading で
リアルタイム監視して "Initialization Sequence Completed" を検出する。
--log オプションは使わない (GitHub Actions runner で /tmp への書き込みが
不安定だった実績あり)。
"""

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .subprocess_utils import allowlisted_env, terminate_process_group

logger = logging.getLogger(__name__)

# 現在接続中の openvpn プロセス
_current_proc: subprocess.Popen | None = None


def connect(
    config_path: Path,
    wait_sec: int = 45,
    *,
    deadline: float | None = None,
) -> bool:
    """openvpn を起動し、"Initialization Sequence Completed" を待つ。

    stderr をリアルタイムで threading 監視する。

    Returns:
        True: 接続成功
        False: タイムアウトまたはエラー
    """
    global _current_proc
    disconnect()

    if deadline is not None and time.monotonic() >= deadline:
        logger.warning("VPN 接続前に全体期限へ到達")
        return False

    openvpn_bin = shutil.which("openvpn") or "openvpn"
    cmd = ([] if os.geteuid() == 0 else ["sudo", "--"]) + [
        openvpn_bin, "--config", str(config_path), "--script-security", "1",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,   # openvpn は stdout にログ出力する
            stderr=subprocess.STDOUT,  # stderr も stdout に統合
            env=allowlisted_env(),
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("openvpn 起動失敗: %s", e)
        return False
    _current_proc = proc

    # stdout を非同期で読むスレッド
    output_lines: list[str] = []
    connected_event = threading.Event()
    error_event = threading.Event()

    def _reader():
        assert proc.stdout is not None
        try:
            for raw_line in proc.stdout:
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
    wait_deadline = time.monotonic() + wait_sec
    if deadline is not None:
        wait_deadline = min(wait_deadline, deadline)
    while time.monotonic() < wait_deadline:
        if connected_event.is_set():
            settle_sec = 2.0
            if deadline is not None:
                settle_sec = min(settle_sec, max(0.0, deadline - time.monotonic()))
            time.sleep(settle_sec)  # route 安定化
            if deadline is not None and time.monotonic() >= deadline:
                logger.warning("VPN route 安定化中に全体期限へ到達")
                disconnect()
                return False
            logger.info("VPN 接続成功")
            return True
        if error_event.is_set():
            logger.error("openvpn エラー: %s", output_lines[-1] if output_lines else "unknown")
            disconnect()
            return False
        if proc.poll() is not None:
            reader_thread.join(timeout=3)
            logger.error(
                "openvpn が即終了 (code=%d), 出力:\n  %s",
                proc.returncode,
                "\n  ".join(output_lines[-15:]),
            )
            if _current_proc is proc:
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
    """このモジュールが起動した openvpn process group だけを停止する。"""
    global _current_proc

    proc = _current_proc
    _current_proc = None
    if proc is not None:
        try:
            terminate_process_group(proc)
        except OSError:
            pass
