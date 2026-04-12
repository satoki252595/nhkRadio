"""OpenVPN 接続の Python 側管理モジュール。

GitHub Actions の kota65535/github-openvpn-connect-action は一度接続すると
ジョブ終了まで切断できないため、複数の VPN エリアを順次カバーしたいこの
v2 アーキテクチャには不向き。本モジュールは sudo openvpn を直接起動 /
停止して、1 ジョブ内で複数回の再接続を可能にする。

前提: GitHub Actions runner ではデフォルトユーザー `runner` に NOPASSWD
sudo が設定されているため `sudo openvpn ...` が認証なしで実行できる。
"""

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PID_FILE = Path("/tmp/openvpn.pid")
LOG_FILE = Path("/tmp/openvpn.log")


def connect(config_path: Path, wait_sec: int = 30) -> bool:
    """openvpn を daemon 起動し、"Initialization Sequence Completed" を待つ。

    Returns:
        True: 接続成功
        False: タイムアウトまたはエラー
    """
    # まず既存 openvpn を確実に止める
    disconnect()

    # ログをリセット (前回の接続痕跡を混同しないように)
    try:
        LOG_FILE.unlink(missing_ok=True)
    except OSError:
        pass

    cmd = [
        "sudo", "openvpn",
        "--config", str(config_path),
        "--daemon",
        "--writepid", str(PID_FILE),
        "--log", str(LOG_FILE),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=15)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = getattr(e, "stderr", b"") or b""
        logger.error("openvpn 起動失敗: %s", stderr.decode(errors="replace")[-300:])
        return False

    # "Initialization Sequence Completed" を待つ
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        try:
            if LOG_FILE.exists():
                content = LOG_FILE.read_text(errors="replace")
                if "Initialization Sequence Completed" in content:
                    # 接続直後は DNS / route が反映する猶予を取る
                    time.sleep(2)
                    logger.info("VPN 接続成功")
                    return True
                if "AUTH_FAILED" in content:
                    logger.error("openvpn 認証失敗")
                    disconnect()
                    return False
                if "Cannot resolve host address" in content:
                    logger.error("openvpn ホスト名解決失敗")
                    disconnect()
                    return False
        except OSError:
            pass
        time.sleep(1)

    # デバッグ用: openvpn ログの末尾を出力
    try:
        if LOG_FILE.exists():
            tail = LOG_FILE.read_text(errors="replace").splitlines()[-15:]
            logger.warning("VPN 接続タイムアウト (%ds), openvpn ログ末尾:", wait_sec)
            for line in tail:
                logger.warning("  openvpn> %s", line.rstrip())
    except OSError:
        logger.warning("VPN 接続タイムアウト (%ds), ログ読取失敗", wait_sec)
    disconnect()
    return False


def disconnect() -> None:
    """openvpn daemon を停止する。

    1) writepid のプロセスに SIGTERM
    2) 念のため pkill で残存プロセスを掃除
    """
    try:
        if PID_FILE.exists():
            pid = PID_FILE.read_text().strip()
            if pid.isdigit():
                subprocess.run(
                    ["sudo", "kill", "-TERM", pid],
                    check=False, capture_output=True, timeout=5,
                )
    except (OSError, subprocess.TimeoutExpired):
        pass

    # 残存 openvpn プロセスを全停止 (念のため)
    subprocess.run(
        ["sudo", "pkill", "-TERM", "-x", "openvpn"],
        check=False, capture_output=True, timeout=5,
    )
    # プロセス終了と tun インターフェース削除を待つ
    time.sleep(3)

    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


class VpnSession:
    """with 文で使える VPN 接続コンテキストマネージャ。"""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.connected = False

    def __enter__(self) -> "VpnSession":
        self.connected = connect(self.config_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.connected:
            disconnect()
            self.connected = False
