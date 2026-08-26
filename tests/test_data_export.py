import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from nhk_recorder import data_export
from nhk_recorder.api import Program
from nhk_recorder.radiko import RadikoAuth


def _set_args(monkeypatch, output_dir, *extra):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "data_export",
            "--date",
            "2026-08-27",
            "--days",
            "1",
            "--past-days",
            "0",
            "--output-dir",
            str(output_dir),
            *extra,
        ],
    )
    monkeypatch.setattr(
        data_export, "load_config", lambda: SimpleNamespace(area="130")
    )


def test_export_stops_when_requested_radiko_authentication_fails(
    tmp_path, monkeypatch
):
    output_dir = tmp_path / "data"
    _set_args(monkeypatch, output_dir, "--include-radiko")
    monkeypatch.setattr(data_export.radiko, "authenticate", lambda: None)

    with pytest.raises(SystemExit) as error:
        data_export.main()

    assert error.value.code == 1
    assert not (output_dir / "series.json").exists()


def test_export_stops_when_fresh_nhk_programs_are_empty(tmp_path, monkeypatch):
    output_dir = tmp_path / "data"
    _set_args(monkeypatch, output_dir)
    monkeypatch.setattr(data_export, "fetch_programs", lambda _config, _date: [])

    with pytest.raises(SystemExit) as error:
        data_export.main()

    assert error.value.code == 1
    assert not (output_dir / "series.json").exists()


def test_export_stops_when_authenticated_radiko_schedule_is_empty(
    tmp_path, monkeypatch
):
    output_dir = tmp_path / "data"
    _set_args(monkeypatch, output_dir, "--include-radiko")
    start = datetime(2026, 8, 27, tzinfo=data_export.JST)
    program = Program(
        id="nhk-test",
        service="r1",
        title="test",
        subtitle="",
        content="",
        start_time=start,
        end_time=start + timedelta(hours=1),
    )
    monkeypatch.setattr(
        data_export.radiko,
        "authenticate",
        lambda: RadikoAuth(token="test", area_id="JP13", area_name="東京"),
    )
    monkeypatch.setattr(data_export, "fetch_programs", lambda _config, _date: [program])
    monkeypatch.setattr(data_export.radiko, "fetch_programs", lambda _area, _date: [])

    with pytest.raises(SystemExit) as error:
        data_export.main()

    assert error.value.code == 1
    assert not (output_dir / "series.json").exists()
