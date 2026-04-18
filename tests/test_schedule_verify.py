"""schedule_verify の単体テスト。

4/14 の「放送していない番組を録音していました」インシデントの回帰テスト。
キャッシュされた番組タイトルと当日差し替えられた Radiko 実スケジュールを
クロスチェックし、類似度が低い場合は録音をスキップすることを確認する。
"""
from datetime import datetime, timedelta, timezone

import pytest

from nhk_recorder.api import Program
from nhk_recorder.radiko import RadikoProgram
from nhk_recorder.schedule_verify import (
    SIMILARITY_THRESHOLD,
    _normalize_title,
    _similarity,
    verify_program,
)

JST = timezone(timedelta(hours=9))


def _program(title: str, service: str = "r3", start=None, end=None) -> Program:
    start = start or datetime(2026, 4, 14, 16, 0, tzinfo=JST)
    end = end or datetime(2026, 4, 14, 17, 55, tzinfo=JST)
    return Program(
        id="test-p",
        service=service,
        title=title,
        subtitle="",
        content="",
        start_time=start,
        end_time=end,
        series_id="TEST",
        series_name="テスト",
    )


def _rprog(station_id: str, title: str, start=None, end=None) -> RadikoProgram:
    start = start or datetime(2026, 4, 14, 16, 0, tzinfo=JST)
    end = end or datetime(2026, 4, 14, 17, 55, tzinfo=JST)
    return RadikoProgram(
        id=f"{station_id}-test",
        station_id=station_id,
        station_name="NHK FM（大阪）",
        title=title,
        subtitle="",
        content="",
        performer="",
        start_time=start,
        end_time=end,
        area_id="JP27",
    )


def _index(*radiko_progs):
    return {
        (p.station_id, p.start_time.isoformat()): p for p in radiko_progs
    }


def test_normalize_strips_station_prefix():
    assert _normalize_title("[NHK FM（東京）] 名演奏ライブラリー") == "名演奏ライブラリー"


def test_normalize_strips_episode_number():
    assert _normalize_title("古楽の楽しみ 木と古楽（２）") == "古楽の楽しみ 木と古楽"
    assert _normalize_title("ラジオビジネス英語 Ｌｅｓｓｏｎ（１０）") == "ラジオビジネス英語"


def test_similarity_exact_match():
    assert _similarity("落語の時間", "落語の時間") == 1.0


def test_similarity_different_programs():
    # 完全に別番組のタイトル
    sim = _similarity("名演奏ライブラリー コルトー", "緊急特別番組 大規模災害報道")
    assert sim < SIMILARITY_THRESHOLD


def test_similarity_same_series_different_episode():
    # 連載番組の回違い (data_export 側で episode number が既に剥がれている前提)
    sim = _similarity(
        "ラジオビジネス英語",
        "ラジオビジネス英語",
    )
    assert sim >= SIMILARITY_THRESHOLD


def test_verify_ok_exact_title():
    prog = _program("名演奏ライブラリー 詩情豊かな名ピアニスト アルフレッド・コルトー")
    index = _index(_rprog("JOBK-FM", "[NHK FM（大阪）] 名演奏ライブラリー 詩情豊かな名ピアニスト アルフレッド・コルトー"))
    result = verify_program(prog, "JOBK-FM", index)
    assert result.ok, f"should match: {result.reason}"


def test_verify_mismatch_when_replaced():
    """4/14 インシデント相当: 予定 = コルトー、実際 = 別番組 → スキップすべき。"""
    prog = _program("名演奏ライブラリー 詩情豊かな名ピアニスト アルフレッド・コルトー")
    index = _index(_rprog("JOBK-FM", "[NHK FM（大阪）] 緊急特別番組 政府記者会見中継"))
    result = verify_program(prog, "JOBK-FM", index)
    assert not result.ok
    assert "タイトル不一致" in result.reason
    assert "政府記者会見" in result.actual_title


def test_verify_mismatch_when_slot_missing():
    """スケジュールから枠が消えた (番組短縮/欠番) → スキップ。"""
    prog = _program("名演奏ライブラリー")
    # 索引には別局の番組しかない
    index = _index(_rprog("ABC", "[ABCラジオ] 桂りょうばの落語トラベル"))
    result = verify_program(prog, "JOBK-FM", index)
    assert not result.ok
    assert "Radiko スケジュール無し" in result.reason


def test_verify_ok_with_3_second_offset():
    """NHK の :03 秒オフセット vs Radiko の :00 秒丸めを許容する。"""
    prog = _program(
        "古楽の楽しみ",
        start=datetime(2026, 4, 14, 5, 0, 3, tzinfo=JST),
        end=datetime(2026, 4, 14, 5, 55, tzinfo=JST),
    )
    index = _index(_rprog(
        "JOBK-FM",
        "[NHK FM（大阪）] 古楽の楽しみ 木と古楽（２）",
        start=datetime(2026, 4, 14, 5, 0, 0, tzinfo=JST),
        end=datetime(2026, 4, 14, 5, 55, 0, tzinfo=JST),
    ))
    result = verify_program(prog, "JOBK-FM", index)
    assert result.ok, f"should tolerate :03 offset: {result.reason}"


def test_verify_ok_series_episode_number_differs():
    """ラジオビジネス英語 Lesson(9) キャッシュ vs Lesson(10) 実放送: 正規化後は同一。"""
    prog = _program("ラジオビジネス英語　Ｌｅｓｓｏｎ（９）")
    index = _index(_rprog(
        "JOBK-FM", "[NHK FM（大阪）] ラジオビジネス英語　Ｌｅｓｓｏｎ（１０）",
    ))
    result = verify_program(prog, "JOBK-FM", index)
    assert result.ok, f"episode number diff should be tolerated: {result.reason}"
