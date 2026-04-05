from datetime import timezone, timedelta

from nhk_recorder.api import Program

JST = timezone(timedelta(hours=9))


# v3形式のサンプルレスポンス
SAMPLE_V3_RESPONSE = {
    "r1": {
        "publication": [
            {
                "id": "r1-270-2026040400001",
                "name": "ラジオ深夜便",
                "description": "今夜は落語名作選をお送りします",
                "startDate": "2026-04-04T23:00:00+09:00",
                "endDate": "2026-04-05T05:00:00+09:00",
                "identifierGroup": {
                    "radioEpisodeName": "落語特集",
                },
            },
            {
                "id": "r1-270-2026040400002",
                "name": "NHKニュース",
                "description": "全国のニュースをお伝えします",
                "startDate": "2026-04-04T07:00:00+09:00",
                "endDate": "2026-04-04T07:20:00+09:00",
                "identifierGroup": {
                    "radioEpisodeName": "",
                },
            },
        ]
    }
}


def test_program_duration():
    from datetime import datetime
    p = Program(
        id="test",
        service="r1",
        title="テスト",
        subtitle="",
        content="",
        start_time=datetime(2026, 4, 4, 21, 0, tzinfo=JST),
        end_time=datetime(2026, 4, 4, 21, 50, tzinfo=JST),
    )
    assert p.duration == 3000  # 50分 = 3000秒


def test_parse_v3_response():
    """v3 APIレスポンスのパースをシミュレート"""
    from datetime import datetime
    publications = SAMPLE_V3_RESPONSE["r1"]["publication"]

    programs = []
    for item in publications:
        p = Program(
            id=item["id"],
            service="r1",
            title=item["name"],
            subtitle=item.get("identifierGroup", {}).get("radioEpisodeName", ""),
            content=item.get("description", ""),
            start_time=datetime.fromisoformat(item["startDate"]),
            end_time=datetime.fromisoformat(item["endDate"]),
        )
        programs.append(p)

    assert len(programs) == 2
    assert programs[0].title == "ラジオ深夜便"
    assert programs[0].subtitle == "落語特集"
    assert programs[0].duration == 21600  # 6時間
    assert programs[1].title == "NHKニュース"
    assert programs[1].duration == 1200  # 20分
