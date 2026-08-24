"""期限付き子プロセス実行と process group の後始末。"""

from __future__ import annotations

import os
import signal
import subprocess
import time

_CHILD_ENV_KEYS = (
    "PATH", "LANG", "LC_ALL", "TZ", "TZDIR",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "HOME", "TMPDIR",
)


def allowlisted_env() -> dict[str, str]:
    """子プロセスへ渡してよい非secret環境変数だけを返す。"""
    return {key: os.environ[key] for key in _CHILD_ENV_KEYS if key in os.environ}


def terminate_process_group(
    proc: subprocess.Popen,
    *,
    grace_sec: float = 5,
) -> None:
    """proc が所有する process group を TERM、残存時は KILL で停止する。"""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=grace_sec)
    except subprocess.TimeoutExpired:
        pass

    # 親が先に終了しても孫プロセスが残る場合があるため、group 全体を確認する。
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    try:
        proc.wait(timeout=grace_sec)
    except subprocess.TimeoutExpired:
        pass


def run_captured(
    cmd: list[str],
    *,
    timeout_sec: float,
    deadline: float | None = None,
    text: bool = False,
) -> subprocess.CompletedProcess:
    """stdout/stderr を捕捉し、ローカル上限と絶対期限の早い方まで実行する。"""
    effective_timeout = timeout_sec
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(cmd, 0)
        effective_timeout = min(effective_timeout, remaining)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        start_new_session=True,
        env=allowlisted_env(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=effective_timeout)
    except BaseException:
        terminate_process_group(proc)
        proc.communicate()
        raise

    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
