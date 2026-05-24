"""_run_radiru_pass の並列化に関するリグレッションテスト。

並列化 (2026-05-24) で行った変更が、元の逐次版と同じ status 判定・カウンタ
更新・remaining リスト生成を保つことを保証する。実 HTTP は呼ばず
_download_nhk_via_radiru を mock 化する。
"""

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from nhk_recorder.api import Program
from nhk_recorder.config import Config
from nhk_recorder.main import _run_radiru_pass

JST = timezone(timedelta(hours=9))


def _program(pid: str, end_offset_sec: int = -3600) -> Program:
    """テスト用 Program を 1 件作る。end_offset_sec < 0 で「放送済み」状態。"""
    now = datetime.now(JST)
    start = now + timedelta(seconds=end_offset_sec - 1800)
    end = now + timedelta(seconds=end_offset_sec)
    return Program(
        id=pid, service="r1", title=f"title-{pid}", subtitle="", content="",
        start_time=start, end_time=end,
        series_id=f"S{pid}", series_name="", episode_name="",
        genre=[], area="NHK",
    )


def _empty_config() -> Config:
    """notion 未設定の最小 Config。"""
    return Config(
        nhk_api_key="k", area="270", services=["r1"], keywords=[],
        notion_token=None, notion_database_id=None,
        ffmpeg_path="ffmpeg", output_dir="recordings", log_level="INFO",
    )


def _counters() -> tuple[dict, threading.Lock]:
    return {
        "success": 0, "failed": 0, "skipped": 0,
        "mismatch": 0, "radiru_missing": 0, "via_radiru": 0,
        "already_uploaded": 0,
    }, threading.Lock()


def test_run_radiru_pass_filters_unaired_programs():
    """end_time が未来の番組は DL せず skipped に積み、eligible からも除外する。"""
    aired = _program("aired", end_offset_sec=-3600)  # 1h 前に終わった
    future = _program("future", end_offset_sec=+3600)  # 1h 先に終わる

    cfg = _empty_config()
    counters, lock = _counters()

    # aired のみ DL される想定。mock で uploaded を返す。
    with patch(
        "nhk_recorder.main._download_nhk_via_radiru", return_value="uploaded",
    ) as m:
        remaining = _run_radiru_pass([aired, future], cfg, [], counters, lock)

    # future は _download_nhk_via_radiru に渡らない
    called_ids = [c.args[0].id for c in m.call_args_list]
    assert called_ids == ["aired"]
    # 未放送は skipped カウンタに +1
    assert counters["skipped"] == 1
    # uploaded は次パス対象から外れる
    assert remaining == []


def test_run_radiru_pass_status_mapping_matches_sequential():
    """status → (remaining, radiru_missing カウンタ, ログ) の判定が逐次版と一致する。"""
    progs = [
        _program("uploaded"),
        _program("dl_failed"),
        _program("missing"),
        _program("no_series_id"),
        _program("upload_failed"),
    ]
    status_map = {
        "uploaded": "uploaded",
        "dl_failed": "dl_failed",
        "missing": "missing",
        "no_series_id": "no_series_id",
        "upload_failed": "upload_failed",
    }

    def fake_dl(p, cfg, kw, ctrs, lock):
        return status_map[p.id]

    cfg = _empty_config()
    counters, lock = _counters()
    with patch("nhk_recorder.main._download_nhk_via_radiru", side_effect=fake_dl):
        remaining = _run_radiru_pass(progs, cfg, [], counters, lock)

    # dl_failed のみ次パス再試行に積まれる
    assert [p.id for p in remaining] == ["dl_failed"]
    # missing / no_series_id は radiru_missing カウンタへ
    assert counters["radiru_missing"] == 2
    # uploaded / upload_failed のカウンタ更新は _download_nhk_via_radiru 内
    # (本テストでは mock しているため 0 のまま)
    assert counters["success"] == 0


def test_run_radiru_pass_returns_empty_when_no_eligible():
    """全番組が未放送なら DL は走らず空 list が返る。"""
    progs = [_program(f"p{i}", end_offset_sec=+1800) for i in range(3)]
    cfg = _empty_config()
    counters, lock = _counters()

    with patch("nhk_recorder.main._download_nhk_via_radiru") as m:
        remaining = _run_radiru_pass(progs, cfg, [], counters, lock)

    assert m.call_count == 0
    assert remaining == []
    assert counters["skipped"] == 3


def test_run_radiru_pass_parallel_invokes_all_in_parallel():
    """並列度 3 で 3 件同時に走ることを確認 (Barrier で同期確認)。"""
    progs = [_program(f"p{i}") for i in range(3)]
    barrier = threading.Barrier(3, timeout=5)

    def fake_dl(p, cfg, kw, ctrs, lock):
        # 全 thread がここに到達して初めて先へ進める。直列なら Barrier が
        # 集まらず TimeoutError で test 失敗する。
        barrier.wait()
        return "uploaded"

    cfg = _empty_config()
    counters, lock = _counters()
    with patch("nhk_recorder.main._download_nhk_via_radiru", side_effect=fake_dl):
        remaining = _run_radiru_pass(progs, cfg, [], counters, lock)

    assert remaining == []


def test_run_radiru_pass_isolates_exceptions_as_dl_failed():
    """_download_nhk_via_radiru から漏れた例外は dl_failed 扱い (次パス再試行)。"""
    progs = [_program("ok"), _program("boom")]

    def fake_dl(p, cfg, kw, ctrs, lock):
        if p.id == "boom":
            raise RuntimeError("simulated thread failure")
        return "uploaded"

    cfg = _empty_config()
    counters, lock = _counters()
    with patch("nhk_recorder.main._download_nhk_via_radiru", side_effect=fake_dl):
        remaining = _run_radiru_pass(progs, cfg, [], counters, lock)

    # boom だけ次パスへ、ok は確定済み
    assert [p.id for p in remaining] == ["boom"]
