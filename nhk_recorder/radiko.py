"""Radiko (民放ラジオ) API クライアント。

日本IPからのアクセスが必要。GitHub Actions で使う場合は VPN Gate などで
日本IPにルーティングしてから呼び出すこと。詳細は docs/radiko-vpn-setup.md 参照。
"""

import base64
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# Radiko固定キー (クライアントハードコード値)
RADIKO_AUTH_KEY = "bcd151073c03b352e1ef2fd66c32209da9ca0afa"
AUTH1_URL = "https://radiko.jp/v2/api/auth1"
AUTH2_URL = "https://radiko.jp/v2/api/auth2"
STATION_LIST_URL = "https://radiko.jp/v3/station/list/{area_id}.xml"
PROGRAM_DATE_URL = "http://radiko.jp/v3/program/date/{date}/{area_id}.xml"
STREAM_URL_TEMPLATE = (
    "https://f-radiko.smartstream.ne.jp/{station_id}/_definst_/simul-stream.stream/playlist.m3u8"
)


@dataclass
class RadikoAuth:
    token: str
    area_id: str
    area_name: str


@dataclass
class RadikoProgram:
    id: str
    station_id: str
    station_name: str
    title: str
    subtitle: str
    content: str
    performer: str
    start_time: datetime
    end_time: datetime
    series_name: str = ""

    @property
    def duration(self) -> int:
        return int((self.end_time - self.start_time).total_seconds())


def authenticate() -> RadikoAuth | None:
    """Radiko認証 (auth1 → partialkey → auth2)。

    日本IPからのみ成功する。VPN経由の場合もJPエリアコードが返ればOK。

    Returns:
        認証成功時は RadikoAuth、失敗時は None
    """
    headers1 = {
        "User-Agent": "curl/7.52.1",
        "Accept": "*/*",
        "X-Radiko-App": "pc_html5",
        "X-Radiko-App-Version": "0.0.1",
        "X-Radiko-User": "dummy_user",
        "X-Radiko-Device": "pc",
    }

    try:
        with httpx.Client(timeout=30) as client:
            # Step 1: auth1
            resp1 = client.get(AUTH1_URL, headers=headers1)
            if resp1.status_code != 200:
                logger.error("Radiko auth1失敗: HTTP %s", resp1.status_code)
                return None

            token = resp1.headers.get("X-Radiko-AuthToken")
            key_length = resp1.headers.get("X-Radiko-KeyLength")
            key_offset = resp1.headers.get("X-Radiko-KeyOffset")
            if not (token and key_length and key_offset):
                logger.error("Radiko auth1: 必要ヘッダー欠損")
                return None

            offset = int(key_offset)
            length = int(key_length)
            partial = RADIKO_AUTH_KEY[offset : offset + length].encode("utf-8")
            partial_key = base64.b64encode(partial).decode("utf-8")

            # Step 2: auth2
            headers2 = {
                **headers1,
                "X-Radiko-AuthToken": token,
                "X-Radiko-Partialkey": partial_key,
            }
            resp2 = client.get(AUTH2_URL, headers=headers2)
            if resp2.status_code != 200:
                logger.error("Radiko auth2失敗: HTTP %s - %s", resp2.status_code, resp2.text[:200])
                return None

            # レスポンスbody: "JP27,大阪府,OSAKA JAPAN"
            parts = resp2.text.strip().split(",")
            if len(parts) < 2 or not parts[0].startswith("JP"):
                logger.error("Radiko auth2: 不正なエリアコード: %s", resp2.text[:100])
                return None

            area_id = parts[0]
            area_name = parts[1] if len(parts) > 1 else ""
            logger.info("Radiko認証成功: area=%s (%s)", area_id, area_name)
            return RadikoAuth(token=token, area_id=area_id, area_name=area_name)

    except httpx.RequestError as e:
        logger.error("Radiko認証エラー: %s", e)
        return None


def fetch_stations(area_id: str) -> dict[str, str]:
    """指定エリアの放送局一覧を取得。

    Returns:
        station_id -> station_name の辞書
    """
    try:
        resp = httpx.get(STATION_LIST_URL.format(area_id=area_id), timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        stations: dict[str, str] = {}
        for station in root.iter("station"):
            sid = station.findtext("id", "").strip()
            name = station.findtext("name", "").strip()
            if sid:
                stations[sid] = name
        logger.info("Radiko放送局取得: %d局 (area=%s)", len(stations), area_id)
        return stations
    except (httpx.RequestError, httpx.HTTPStatusError, ET.ParseError) as e:
        logger.error("Radiko放送局取得失敗: %s", e)
        return {}


def _parse_radiko_time(s: str) -> datetime:
    """YYYYMMDDhhmmss → datetime (JST)"""
    return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=JST)


def fetch_programs(area_id: str, date: str) -> list[RadikoProgram]:
    """指定日の指定エリアの全番組を取得。

    Args:
        area_id: "JP27" (大阪) 等
        date: "YYYY-MM-DD"
    """
    ymd = date.replace("-", "")
    try:
        resp = httpx.get(
            PROGRAM_DATE_URL.format(date=ymd, area_id=area_id),
            timeout=30,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except (httpx.RequestError, httpx.HTTPStatusError, ET.ParseError) as e:
        logger.error("Radiko番組表取得失敗 (%s, %s): %s", area_id, date, e)
        return []

    programs: list[RadikoProgram] = []
    for station in root.iter("station"):
        station_id = station.get("id", "")
        station_name = station.findtext("name", "").strip()
        progs_elem = station.find("progs")
        if progs_elem is None:
            continue
        for prog in progs_elem.iter("prog"):
            try:
                ft = prog.get("ft", "")  # 開始時刻 YYYYMMDDhhmmss
                to = prog.get("to", "")  # 終了時刻
                prog_id = prog.get("id", "")
                if not ft or not to:
                    continue
                title = (prog.findtext("title") or "").strip()
                info = (prog.findtext("info") or "").strip()
                pfm = (prog.findtext("pfm") or "").strip()
                programs.append(
                    RadikoProgram(
                        id=f"{station_id}-{prog_id}",
                        station_id=station_id,
                        station_name=station_name,
                        title=title,
                        subtitle="",
                        content=info,
                        performer=pfm,
                        start_time=_parse_radiko_time(ft),
                        end_time=_parse_radiko_time(to),
                        series_name=title,  # Radiko は series_id が無いので title をシリーズ名とする
                    )
                )
            except (KeyError, ValueError) as e:
                logger.warning("Radiko番組パース失敗: %s", e)

    logger.info("Radiko番組表取得: %d件 (area=%s, date=%s)", len(programs), area_id, date)
    return programs


def record_program(
    auth: RadikoAuth,
    station_id: str,
    duration_sec: int,
    output_path: Path,
    ffmpeg_path: str = "ffmpeg",
) -> bool:
    """Radikoライブストリームを録音する。

    Returns:
        成功ならTrue
    """
    import subprocess

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stream_url = STREAM_URL_TEMPLATE.format(station_id=station_id)

    cmd = [
        ffmpeg_path,
        "-y",
        "-headers",
        f"X-Radiko-AuthToken: {auth.token}",
        "-i",
        stream_url,
        "-t",
        str(duration_sec),
        "-c",
        "copy",
        str(output_path),
    ]

    logger.info("Radiko録音開始: %s (%d秒) -> %s", station_id, duration_sec, output_path.name)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=duration_sec + 120,
        )
        if result.returncode == 0:
            logger.info("Radiko録音完了: %s", output_path.name)
            return True
        logger.error(
            "ffmpegエラー (code=%d): %s",
            result.returncode,
            result.stderr.decode(errors="replace")[-500:],
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("Radiko録音タイムアウト: %s", output_path.name)
        return False
    except FileNotFoundError:
        logger.error("ffmpegが見つかりません: %s", ffmpeg_path)
        return False
