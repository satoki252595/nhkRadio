import os
import signal
import subprocess
from unittest.mock import Mock, call, patch

import pytest

from nhk_recorder.subprocess_utils import run_captured


def test_run_captured_caps_timeout_and_kills_process_group():
    proc = Mock()
    proc.pid = 1234
    proc.returncode = -signal.SIGKILL
    proc.communicate.side_effect = [
        subprocess.TimeoutExpired(["tool"], 2),
        (b"", b""),
    ]

    with (
        patch.dict(
            os.environ,
            {
                "PATH": "/bin",
                "HOME": "/tmp/home",
                "NOTION_TOKEN": "notion-secret",
                "GITHUB_TOKEN": "github-secret",
            },
            clear=True,
        ),
        patch("nhk_recorder.subprocess_utils.time.monotonic", return_value=100),
        patch("nhk_recorder.subprocess_utils.subprocess.Popen", return_value=proc) as popen,
        patch("nhk_recorder.subprocess_utils.os.killpg") as killpg,
        pytest.raises(subprocess.TimeoutExpired),
    ):
        run_captured(["tool"], timeout_sec=600, deadline=102)

    assert popen.call_args.kwargs["start_new_session"] is True
    assert popen.call_args.kwargs["env"] == {
        "PATH": "/bin",
        "HOME": "/tmp/home",
    }
    assert proc.communicate.call_args_list == [call(timeout=2), call()]
    assert killpg.call_args_list == [
        call(1234, signal.SIGTERM),
        call(1234, signal.SIGKILL),
    ]


def test_run_captured_does_not_spawn_after_deadline():
    with (
        patch("nhk_recorder.subprocess_utils.time.monotonic", return_value=100),
        patch("nhk_recorder.subprocess_utils.subprocess.Popen") as popen,
        pytest.raises(subprocess.TimeoutExpired),
    ):
        run_captured(["tool"], timeout_sec=600, deadline=100)

    popen.assert_not_called()
