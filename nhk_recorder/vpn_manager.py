"""OpenVPN 接続の Python 側管理モジュール。

--daemon を使わず Popen でフォアグラウンドプロセスとして管理する。
これにより:
- ログの取得が確実 (--log の file permission 問題を回避)
- プロセス管理が明確 (proc.terminate() で停止)
- エラー出力が即座に確認できる
"""

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_FILE = Path("/tmp/openvpn.log")

# 現在接続中の openvpn プロセス (disconnect で使う)
_current_proc: subprocess.Popen | None = None


def connect(config_path: Path, wait_sec: int = 45) -> bool:
    """openvpn を起動し、"Initialization Sequence Completed" を待つ。

    --daemon を使わず Popen でフォアグラウンド管理する。
    disconnect() で確実に停止できる。

    Returns:
        True: 接続成功
        False: タイムアウトまたはエラー
    """
    global _current_proc
    disconnect()

    try:
        LOG_FILE.unlink(missing_ok=True)
    except OSError:
        pass

    # --daemon なし、--log でファイルに出力、stdin を /dev/null にして
    # interactive prompt を防ぐ。Popen でバックグラウンド管理。
    cmd = [
        "sudo", "openvpn",
        "--config", str(config_path),
        "--log", str(LOG_FILE),
    ]

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

    # "Initialization Sequence Completed" をログファイルで待つ
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        # プロセスが既に死んでいたら早期終了
        if _current_proc.poll() is not None:
            stderr = (_current_proc.stderr.read() or b"").decode(errors="replace")
            log_content = ""
            try:
                log_content = LOG_FILE.read_text(errors="replace") if LOG_FILE.exists() else ""
            except OSError:
                pass
            logger.error(
                "openvpn が即終了 (code=%d)\n  stderr: %s\n  log tail: %s",
                _current_proc.returncode,
                stderr[-300:],
                "\n  ".join(log_content.splitlines()[-10:]),
            )
            _current_proc = None
            return False

        try:
            if LOG_FILE.exists():
                content = LOG_FILE.read_text(errors="replace")
                if "Initialization Sequence Completed" in content:
                    time.sleep(2)
                    logger.info("VPN 接続成功")
                    return True
                if "AUTH_FAILED" in content or "Cannot resolve" in content:
                    logger.error("openvpn エラー: %s", content.splitlines()[-1])
                    disconnect()
                    return False
        except OSError:
            pass
        time.sleep(1)

    # タイムアウト: デバッグ用にログ出力
    log_content = ""
    try:
        if LOG_FILE.exists():
            log_content = LOG_FILE.read_text(errors="replace")
    except OSError:
        pass
    if log_content:
        tail = log_content.splitlines()[-15:]
        logger.warning("VPN 接続タイムアウト (%ds), openvpn ログ末尾:", wait_sec)
        for line in tail:
            logger.warning("  openvpn> %s", line.rstrip())
    else:
        logger.warning("VPN 接続タイムアウト (%ds), ログファイル未生成", wait_sec)

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
    subprocess.run(
        ["sudo", "pkill", "-TERM", "-x", "openvpn"],
        check=False, capture_output=True, timeout=5,
    )
    time.sleep(2)
