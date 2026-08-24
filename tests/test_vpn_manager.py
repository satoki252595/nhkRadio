import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from nhk_recorder import vpn_manager


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self._target = target

    def start(self):
        self._target()

    def join(self, timeout=None):
        return None


@pytest.mark.parametrize(
    ("euid", "prefix"),
    [(0, []), (1000, ["sudo", "--"])],
)
def test_connect_limits_environment_and_disconnects_owned_group_only(euid, prefix):
    proc = Mock()
    proc.stdout = [b"Initialization Sequence Completed\n"]
    proc.poll.return_value = None
    vpn_manager._current_proc = None

    child_env = {
        "PATH": "/usr/bin:/usr/sbin",
        "LANG": "C.UTF-8",
        "NHK_API_KEY": "nhk-secret",
        "NOTION_TOKEN": "notion-secret",
        "GITHUB_TOKEN": "github-secret",
    }
    with (
        patch.dict(os.environ, child_env, clear=True),
        patch("nhk_recorder.vpn_manager.os.geteuid", return_value=euid),
        patch("nhk_recorder.vpn_manager.shutil.which", return_value="/nix/store/openvpn"),
        patch("nhk_recorder.vpn_manager.subprocess.Popen", return_value=proc) as popen,
        patch("nhk_recorder.vpn_manager.threading.Thread", _ImmediateThread),
        patch("nhk_recorder.vpn_manager.time.sleep"),
        patch("nhk_recorder.vpn_manager.terminate_process_group") as terminate,
    ):
        assert vpn_manager.connect(
            Path("vpn.ovpn"), deadline=time.monotonic() + 10,
        )
        vpn_manager.disconnect()

    assert popen.call_args.args[0] == prefix + [
        "/nix/store/openvpn", "--config", "vpn.ovpn", "--script-security", "1",
    ]
    assert popen.call_args.kwargs["env"] == {
        "PATH": "/usr/bin:/usr/sbin",
        "LANG": "C.UTF-8",
    }
    assert popen.call_args.kwargs["start_new_session"] is True
    terminate.assert_called_once_with(proc)
    assert vpn_manager._current_proc is None
