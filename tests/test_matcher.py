from datetime import datetime, timedelta, timezone

from nhk_recorder.api import Program
from nhk_recorder.matcher import filter_programs

JST = timezone(timedelta(hours=9))


def _make_program(title="テスト番組", subtitle="", content="", service="r1", id="test001"):
    return Program(
        id=id,
        service=service,
        title=title,
        subtitle=subtitle,
        content=content,
        start_time=datetime(2026, 4, 4, 21, 0, tzinfo=JST),
        end_time=datetime(2026, 4, 4, 21, 50, tzinfo=JST),
    )


def test_match_title():
    programs = [_make_program(title="日本の話芸 落語特選")]
    result = filter_programs(programs, ["落語"])
    assert len(result) == 1


def test_match_subtitle():
    programs = [_make_program(title="番組A", subtitle="落語の世界")]
    result = filter_programs(programs, ["落語"])
    assert len(result) == 1


def test_match_content():
    programs = [_make_program(title="番組A", content="今回は落語をお届けします")]
    result = filter_programs(programs, ["落語"])
    assert len(result) == 1


def test_no_match():
    programs = [_make_program(title="ニュース")]
    result = filter_programs(programs, ["落語"])
    assert len(result) == 0


def test_multiple_keywords():
    programs = [
        _make_program(title="英語で話そう", id="p1"),
        _make_program(title="落語の時間", id="p2"),
        _make_program(title="音楽の泉", id="p3"),
    ]
    result = filter_programs(programs, ["落語", "英語"])
    assert len(result) == 2


def test_dedup():
    p = _make_program(title="落語の時間", id="dup1")
    result = filter_programs([p, p], ["落語"])
    assert len(result) == 1


def test_empty_keywords():
    programs = [_make_program(title="落語の時間")]
    result = filter_programs(programs, [])
    assert len(result) == 0


def test_sorted_by_start_time():
    p1 = Program(
        id="late", service="r1", title="落語A", subtitle="", content="",
        start_time=datetime(2026, 4, 4, 22, 0, tzinfo=JST),
        end_time=datetime(2026, 4, 4, 22, 50, tzinfo=JST),
    )
    p2 = Program(
        id="early", service="r1", title="落語B", subtitle="", content="",
        start_time=datetime(2026, 4, 4, 10, 0, tzinfo=JST),
        end_time=datetime(2026, 4, 4, 10, 50, tzinfo=JST),
    )
    result = filter_programs([p1, p2], ["落語"])
    assert result[0].id == "early"
    assert result[1].id == "late"
