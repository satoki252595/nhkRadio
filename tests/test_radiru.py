"""nhk_recorder.radiru の単体テスト。

API レスポンスはネットワーク依存なので httpx の MonkeyPatch でモックする。
2026-04-14 インシデント (Radiko 配信停止) の回帰テストとして、
「放送開始時刻から正しいエピソードを解決できるか」を検証する。
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from nhk_recorder import radiru

JST = timezone(timedelta(hours=9))


class _FakeResp:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _fake_series(episodes):
    return {
        "id": 247,
        "title": "ラジオビジネス英語",
        "episodes": episodes,
    }


def _episode(program_title, start_iso, end_iso, stream_url="http://example/s.m3u8"):
    return {
        "program_title": program_title,
        "onair_date": "",
        "stream_url": stream_url,
        "aa_contents_id": f"[radio]vod;{program_title};r3,130;x;{start_iso}_{end_iso}",
        "program_sub_title": "",
    }


def test_parse_aa_time_range_ok():
    t = radiru._parse_aa_time_range(
        "[radio]vod;title;r3,130;x;2026-04-14T23:20:00+09:00_2026-04-14T23:35:00+09:00"
    )
    assert t is not None
    start, end = t
    assert start == datetime(2026, 4, 14, 23, 20, tzinfo=JST)
    assert end == datetime(2026, 4, 14, 23, 35, tzinfo=JST)


def test_parse_aa_time_range_malformed():
    assert radiru._parse_aa_time_range("") is None
    assert radiru._parse_aa_time_range("not;enough;fields") is None
    assert radiru._parse_aa_time_range("a;b;c;d;not-a-time") is None


def test_fetch_series_episodes_happy_path():
    payload = _fake_series([
        _episode("Lesson (9)", "2026-04-13T23:20:00+09:00", "2026-04-13T23:35:00+09:00"),
        _episode("Lesson (10)", "2026-04-14T23:20:00+09:00", "2026-04-14T23:35:00+09:00",
                 "https://vod-stream.nhk.jp/a.m3u8"),
    ])
    with patch.object(httpx, "get", return_value=_FakeResp(payload)):
        eps = radiru.fetch_series_episodes("368315KKP8")
    assert len(eps) == 2
    assert eps[1].program_title == "Lesson (10)"
    assert eps[1].stream_url == "https://vod-stream.nhk.jp/a.m3u8"


def test_fetch_series_episodes_skips_invalid():
    payload = _fake_series([
        {"program_title": "no aa/stream"},
        _episode("Lesson (10)", "2026-04-14T23:20:00+09:00", "2026-04-14T23:35:00+09:00"),
    ])
    with patch.object(httpx, "get", return_value=_FakeResp(payload)):
        eps = radiru.fetch_series_episodes("368315KKP8")
    assert len(eps) == 1


def test_fetch_series_episodes_network_error():
    def boom(*a, **kw):
        raise httpx.RequestError("boom")
    with patch.object(httpx, "get", side_effect=boom):
        eps = radiru.fetch_series_episodes("X")
    assert eps == []


def test_find_episode_exact_match():
    payload = _fake_series([
        _episode("Lesson (10)", "2026-04-14T23:20:00+09:00", "2026-04-14T23:35:00+09:00"),
    ])
    with patch.object(httpx, "get", return_value=_FakeResp(payload)):
        ep = radiru.find_episode(
            "368315KKP8", datetime(2026, 4, 14, 23, 20, tzinfo=JST),
        )
    assert ep is not None
    assert ep.program_title == "Lesson (10)"


def test_find_episode_tolerates_3_second_offset():
    """NHK の :03 秒オフセット vs radiru の :00 秒を許容。"""
    payload = _fake_series([
        _episode("Kogaku", "2026-04-14T05:00:00+09:00", "2026-04-14T05:55:00+09:00"),
    ])
    with patch.object(httpx, "get", return_value=_FakeResp(payload)):
        ep = radiru.find_episode(
            "COGAKU", datetime(2026, 4, 14, 5, 0, 3, tzinfo=JST),
        )
    assert ep is not None
    assert ep.program_title == "Kogaku"


def test_find_episode_no_match_returns_none():
    payload = _fake_series([
        _episode("Old", "2026-04-01T10:00:00+09:00", "2026-04-01T11:00:00+09:00"),
    ])
    # new_arrivals も空を返すようにして corner 探索もフォールバックさせない
    def fake_get(url, params=None, timeout=None):
        if "new_arrivals" in url:
            return _FakeResp({"corners": []})
        return _FakeResp(payload)
    with patch.object(httpx, "get", side_effect=fake_get):
        ep = radiru.find_episode(
            "X", datetime(2026, 4, 14, 23, 20, tzinfo=JST),
        )
    assert ep is None


def test_find_episode_title_fallback_for_rerun():
    """時刻が一致しない再放送枠 (名演奏ライブラリー Tue 16:00 ← Sun 09:00 原放送) で
    タイトル一致フォールバックが発火し、原放送のストリームを返すこと。"""
    payload = _fake_series([
        _episode(
            "名演奏ライブラリー 詩情豊かな名ピアニスト アルフレッド・コルトー",
            "2026-04-12T09:00:03+09:00", "2026-04-12T10:55:00+09:00",
            "https://vod/sunday.m3u8",
        ),
    ])

    def fake_get(url, params=None, timeout=None):
        if "new_arrivals" in url:
            return _FakeResp({"corners": []})
        return _FakeResp(payload)

    with patch.object(httpx, "get", side_effect=fake_get):
        ep = radiru.find_episode(
            "J99L3XYGQ8",
            # 4/14 Tuesday 16:00 の再放送枠
            datetime(2026, 4, 14, 16, 0, 3, tzinfo=JST),
            expected_title="名演奏ライブラリー　詩情豊かな名ピアニスト　アルフレッド・コルトー",
        )
    assert ep is not None
    assert ep.stream_url == "https://vod/sunday.m3u8"


def test_find_episode_title_fallback_does_not_mismatch_episodes():
    """タイトル fallback でも Lesson(10) と Lesson(9) は別物と判定されること (誤マッチ防止)。"""
    payload = _fake_series([
        _episode(
            "ラジオビジネス英語 Lesson (9)",
            "2026-04-13T23:20:00+09:00", "2026-04-13T23:35:00+09:00",
            "https://vod/lesson9.m3u8",
        ),
    ])

    def fake_get(url, params=None, timeout=None):
        if "new_arrivals" in url:
            return _FakeResp({"corners": []})
        return _FakeResp(payload)

    with patch.object(httpx, "get", side_effect=fake_get):
        ep = radiru.find_episode(
            "368315KKP8",
            # 4/14 23:20 Lesson (10) を期待 (radiru にはまだ無い想定)
            datetime(2026, 4, 14, 23, 20, tzinfo=JST),
            expected_title="ラジオビジネス英語 Ｌｅｓｓｏｎ（１０）",
        )
    assert ep is None  # Lesson(9) に誤マッチしてはいけない


def test_find_episode_title_fallback_normalizes_fullwidth_and_spaces():
    """全角英数・全角スペース・局名プレフィックスを吸収してタイトル一致すること。"""
    payload = _fake_series([
        _episode(
            "ラジオビジネス英語 Lesson (10)",
            "2026-04-14T23:20:00+09:00", "2026-04-14T23:35:00+09:00",
            "https://vod/lesson10.m3u8",
        ),
    ])

    def fake_get(url, params=None, timeout=None):
        if "new_arrivals" in url:
            return _FakeResp({"corners": []})
        return _FakeResp(payload)

    with patch.object(httpx, "get", side_effect=fake_get):
        ep = radiru.find_episode(
            "368315KKP8",
            # 時刻を意図的に 1 時間ズラして title fallback を発動させる
            datetime(2026, 4, 15, 0, 20, tzinfo=JST),
            expected_title="ラジオビジネス英語　Ｌｅｓｓｏｎ（１０）",  # 全角
        )
    assert ep is not None
    assert ep.stream_url == "https://vod/lesson10.m3u8"


def test_find_episode_tries_alternate_corners_when_01_empty():
    """corner_site_id='01' で見つからない場合、new_arrivals 経由で他 corner を試行する。"""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params or {}))
        if "new_arrivals" in url:
            return _FakeResp({"corners": [
                {"series_site_id": "X", "corner_site_id": "26"},
            ]})
        # series API
        cid = (params or {}).get("corner_site_id", "01")
        if cid == "01":
            return _FakeResp(_fake_series([]))
        if cid == "26":
            return _FakeResp(_fake_series([
                _episode("Found", "2026-04-14T23:20:00+09:00",
                         "2026-04-14T23:35:00+09:00"),
            ]))
        return _FakeResp(_fake_series([]))

    with patch.object(httpx, "get", side_effect=fake_get):
        ep = radiru.find_episode(
            "X", datetime(2026, 4, 14, 23, 20, tzinfo=JST),
        )
    assert ep is not None
    assert ep.program_title == "Found"
    # 01 → new_arrivals → 26 の順でアクセスされたこと
    corner_ids = [c[1].get("corner_site_id") for c in calls if "corner_site_id" in c[1]]
    assert corner_ids == ["01", "26"]


def test_find_episode_brute_force_corner_when_new_arrivals_silent():
    """new_arrivals に該当シリーズが無くても "02..30" のブルートフォースで救済される。"""
    def fake_get(url, params=None, timeout=None):
        if "new_arrivals" in url:
            # 該当シリーズについて何も返さない (語学番組などで頻発)
            return _FakeResp({"corners": []})
        cid = (params or {}).get("corner_site_id", "01")
        if cid == "07":
            return _FakeResp(_fake_series([
                _episode("Lang Lesson", "2026-04-14T11:20:00+09:00",
                         "2026-04-14T11:35:00+09:00"),
            ]))
        return _FakeResp(_fake_series([]))

    with patch.object(httpx, "get", side_effect=fake_get):
        ep = radiru.find_episode(
            "X", datetime(2026, 4, 14, 11, 20, tzinfo=JST),
        )
    assert ep is not None
    assert ep.program_title == "Lang Lesson"


def test_find_episode_lenient_title_match_drops_series_prefix():
    """radiru の program_title にシリーズ名プレフィックスが付かないケースを救済する。

    実例: NHK 番組表 = "ラジオビジネス英語 Lesson(10)" / radiru = "Lesson (10)"
    末尾完全一致なので Lesson(1) と Lesson(10) の誤マッチは起きない。
    """
    payload = _fake_series([
        _episode(
            "Lesson (10)",  # ← シリーズ名プレフィックスなし
            "2026-04-14T11:20:00+09:00", "2026-04-14T11:35:00+09:00",
            "https://vod/lesson10.m3u8",
        ),
    ])

    def fake_get(url, params=None, timeout=None):
        if "new_arrivals" in url:
            return _FakeResp({"corners": []})
        return _FakeResp(payload)

    with patch.object(httpx, "get", side_effect=fake_get):
        ep = radiru.find_episode(
            "368315KKP8",
            # 23:20 の再放送枠を狙う (radiru は 11:20 の本放送のみ収録)
            datetime(2026, 4, 14, 23, 20, tzinfo=JST),
            expected_title="ラジオビジネス英語　Ｌｅｓｓｏｎ（１０）",
        )
    assert ep is not None
    assert ep.stream_url == "https://vod/lesson10.m3u8"


def test_find_episode_lenient_title_does_not_mismatch_close_episodes():
    """末尾一致は完全な空白区切りで行うので Lesson(1) と Lesson(10) は誤マッチしない。"""
    payload = _fake_series([
        _episode(
            "Lesson (1)",
            "2026-04-01T11:20:00+09:00", "2026-04-01T11:35:00+09:00",
            "https://vod/lesson1.m3u8",
        ),
    ])

    def fake_get(url, params=None, timeout=None):
        if "new_arrivals" in url:
            return _FakeResp({"corners": []})
        return _FakeResp(payload)

    with patch.object(httpx, "get", side_effect=fake_get):
        ep = radiru.find_episode(
            "368315KKP8",
            datetime(2026, 4, 14, 23, 20, tzinfo=JST),
            expected_title="ラジオビジネス英語 Lesson (10)",
        )
    assert ep is None


def test_fetch_series_episodes_handles_invalid_json():
    """JSON 以外 (HTML エラーページ等) が返ってきても例外を投げず空リスト。"""

    class _BadResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("Expecting value")

    with patch.object(httpx, "get", return_value=_BadResp()):
        eps = radiru.fetch_series_episodes("X")
    assert eps == []
