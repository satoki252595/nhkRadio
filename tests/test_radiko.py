import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from nhk_recorder import radiko


def test_download_timefree_forwards_deadline_and_cleans_temp_on_timeout(tmp_path):
    start = datetime(2026, 8, 1, 12, 0, tzinfo=timezone(timedelta(hours=9)))
    output = tmp_path / "program.m4a"
    auth = radiko.RadikoAuth("token", "JP13", "Tokyo")

    with (
        patch.object(
            radiko, "_fetch_timefree_segments",
            return_value=(["https://example.test/segment.aac"], None),
        ),
        patch.object(radiko, "_download_segment", return_value=b"audio"),
        patch.object(
            radiko, "run_captured",
            side_effect=subprocess.TimeoutExpired(["ffmpeg"], 5),
        ) as run,
    ):
        assert not radiko.download_timefree(
            auth, "TBS", start, start + timedelta(seconds=15), output,
            parallel=1, deadline=123.0,
        )

    assert run.call_args.kwargs["deadline"] == 123.0
    assert not output.with_suffix(".aac.tmp").exists()
