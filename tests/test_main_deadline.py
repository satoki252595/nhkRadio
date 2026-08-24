import logging
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from nhk_recorder.api import Program
from nhk_recorder.config import Config
from nhk_recorder.main import (
    _download_and_upload,
    _download_nhk_via_radiru,
    _handle_sigterm,
    _report_and_exit,
    main,
)

JST = timezone(timedelta(hours=9))


def _program(service="r1"):
    return Program(
        id="p1", service=service, title="title", subtitle="", content="",
        start_time=datetime(2026, 8, 1, 10, 0, tzinfo=JST),
        end_time=datetime(2026, 8, 1, 10, 30, tzinfo=JST),
        series_id="series-1",
    )


def _config(tmp_path):
    return Config(
        nhk_api_key="key", area="270", services=["r1"], keywords=[],
        notion_token=None, notion_database_id=None,
        ffmpeg_path="ffmpeg", output_dir=tmp_path, log_level="INFO",
    )


def test_report_exits_124_when_runtime_deadline_is_exhausted():
    counters = {
        "success": 1,
        "failed": 0,
        "skipped": 0,
        "mismatch": 0,
    }

    with pytest.raises(SystemExit) as exc:
        _report_and_exit(
            counters, 1, logging.getLogger(__name__),
            deadline_exhausted=True,
        )

    assert exc.value.code == 124


def test_sigterm_becomes_system_exit_143():
    with pytest.raises(SystemExit) as exc:
        _handle_sigterm(signal.SIGTERM, None)

    assert exc.value.code == 143


def test_main_disconnects_when_connect_is_interrupted(tmp_path):
    server = Mock(hostname="vpn.example", ip="192.0.2.1", score=1)
    cfg = _config(tmp_path)
    with (
        patch.object(sys, "argv", ["nhk-rec", "--subscriptions", "subscriptions.json"]),
        patch("nhk_recorder.main.signal.signal"),
        patch("nhk_recorder.main.load_config", return_value=cfg),
        patch("nhk_recorder.main._load_subscriptions", return_value=(["series-1"], [])),
        patch("nhk_recorder.main._load_programs_from_json", return_value=[_program()]),
        patch("nhk_recorder.main.fetch_jp_servers", return_value=[server]),
        patch("nhk_recorder.main.vpn_manager.connect", side_effect=SystemExit(143)),
        patch("nhk_recorder.main.vpn_manager.disconnect") as disconnect,
    ):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 143
    disconnect.assert_called_once_with()


def test_nhk_deadline_after_download_skips_upload_and_removes_file(tmp_path):
    output = tmp_path / "nhk.m4a"
    output.write_bytes(b"audio")
    episode = Mock(stream_url="https://example.test/stream", program_title="episode")
    counters = {"success": 0, "failed": 0, "via_radiru": 0}

    with (
        patch("nhk_recorder.main.radiru_mod.find_episode", return_value=episode),
        patch("nhk_recorder.main.radiru_mod.download_ondemand", return_value=True),
        patch("nhk_recorder.main.make_output_path", return_value=output),
        patch("nhk_recorder.main.time.monotonic", return_value=10),
        patch("nhk_recorder.main._upload_to_notion") as upload,
    ):
        result = _download_nhk_via_radiru(
            _program(), _config(tmp_path), [], counters, threading.Lock(),
            deadline=10,
        )

    assert result == "dl_failed"
    upload.assert_not_called()
    assert not output.exists()


def test_radiko_deadline_after_download_skips_upload_and_removes_file(tmp_path):
    output = tmp_path / "radiko.m4a"
    output.write_bytes(b"audio")
    counters = {"success": 0, "failed": 0}

    with (
        patch("nhk_recorder.main.radiko_mod.download_timefree", return_value=True),
        patch("nhk_recorder.main.make_output_path", return_value=output),
        patch("nhk_recorder.main.time.monotonic", return_value=10),
        patch("nhk_recorder.main._upload_to_notion") as upload,
    ):
        _download_and_upload(
            _program("radiko:TBS"), "TBS", Mock(), _config(tmp_path), [],
            counters, threading.Lock(), deadline=10,
        )

    assert counters["failed"] == 1
    upload.assert_not_called()
    assert not output.exists()
