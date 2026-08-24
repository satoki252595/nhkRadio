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

from .subprocess_utils import run_captured

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# Radiko固定キー (クライアントハードコード値)
RADIKO_AUTH_KEY = "bcd151073c03b352e1ef2fd66c32209da9ca0afa"
AUTH1_URL = "https://radiko.jp/v2/api/auth1"
AUTH2_URL = "https://radiko.jp/v2/api/auth2"
STATION_LIST_URL = "https://radiko.jp/v3/station/list/{area_id}.xml"
PROGRAM_DATE_URL = "http://radiko.jp/v3/program/date/{date}/{area_id}.xml"

# Radiko タイムフリー (放送後 7 日以内の番組を任意の時間範囲で取得)
#
# 重要: 以前使っていた `f-radiko.smartstream.ne.jp/.../simul-stream.stream/playlist.m3u8`
# は **ライブ専用** で、`ft`/`to` クエリを付けても無視されてライブストリームを返す。
# 実際のタイムフリー CDN は `tf-f-rpaa-radiko.smartstream.ne.jp/tf/playlist.m3u8` で、
# 必須クエリパラメータは下記の通り (yt-dlp 2026.04 extractor を参考):
#   - station_id: 局 ID (JOAK-FM, ABC 等)
#   - start_at, ft:  開始時刻 (YYYYMMDDhhmmss)  ← start_at と ft 両方必要
#   - end_at,   to:  終了時刻 (YYYYMMDDhhmmss)  ← end_at と to 両方必要
#   - l=15, type=b, lsid=<32hex>: 固定値/ランダム
#
# ヘッダー: X-Radiko-AuthToken + X-Radiko-AreaId (両方必要)
TIMEFREE_BASE_URL = "https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/playlist.m3u8"
STATION_STREAM_URL = "https://radiko.jp/v3/station/stream/pc_html5/{station_id}.xml"


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
    area_id: str = ""  # JP13(東京)/JP27(大阪) 等

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
                        area_id=area_id,
                        start_time=_parse_radiko_time(ft),
                        end_time=_parse_radiko_time(to),
                        series_name=title,  # Radiko は series_id が無いので title をシリーズ名とする
                    )
                )
            except (KeyError, ValueError) as e:
                logger.warning("Radiko番組パース失敗: %s", e)

    logger.info("Radiko番組表取得: %d件 (area=%s, date=%s)", len(programs), area_id, date)
    return programs


def _fetch_timefree_segments(
    auth: RadikoAuth,
    station_id: str,
    start_at: str,
    end_at_full: str,
) -> tuple[list[str], bytes | None]:
    """start_at から 15 秒分の medialist を取得してセグメントバイナリを返す。

    Radiko の medialist は 1 回に 3 セグメント = 15 秒分しか返さない sliding
    window。start_at を 15 秒刻みで進めて呼ぶことで全期間をカバーする。

    Returns:
        (segment_url_list, concatenated_binary) または ([], None) on error
    """
    import random as _random
    from urllib.parse import urlencode

    h = {
        "X-Radiko-AuthToken": auth.token,
        "X-Radiko-AreaId": auth.area_id,
    }

    lsid = "".join(_random.choices("0123456789abcdef", k=32))
    query = urlencode({
        "station_id": station_id,
        "l": "15",
        "lsid": lsid,
        "type": "b",
        "start_at": start_at,
        "ft": start_at,
        "end_at": end_at_full,
        "to": end_at_full,
    })
    playlist_url = f"{TIMEFREE_BASE_URL}?{query}"

    try:
        r = httpx.get(playlist_url, headers=h, timeout=15)
        if r.status_code != 200:
            return [], None
        mlist_urls = [l for l in r.text.splitlines() if l.startswith("http")]
        if not mlist_urls:
            return [], None
        medialist_url = mlist_urls[0]
        r2 = httpx.get(medialist_url, headers=h, timeout=15)
        if r2.status_code != 200:
            return [], None
        segments = [l for l in r2.text.splitlines() if l.startswith("http") and ".aac" in l]
        return segments, None
    except httpx.RequestError:
        return [], None


def _download_segment(url: str, auth: RadikoAuth, retries: int = 3) -> bytes | None:
    """セグメントをダウンロードする (簡易リトライ付き)。"""
    h = {
        "X-Radiko-AuthToken": auth.token,
        "X-Radiko-AreaId": auth.area_id,
    }
    for _ in range(retries):
        try:
            r = httpx.get(url, headers=h, timeout=15)
            if r.status_code == 200:
                return r.content
        except httpx.RequestError:
            pass
        import time as _t
        _t.sleep(0.3)
    return None


def download_timefree(
    auth: RadikoAuth,
    station_id: str,
    start_time: datetime,
    end_time: datetime,
    output_path: Path,
    ffmpeg_path: str = "ffmpeg",
    parallel: int = 8,
    *,
    deadline: float | None = None,
) -> bool:
    """Radiko タイムフリー API で放送済み番組をダウンロードする。

    実装方式:
        Radiko の medialist は 1 リクエスト 3 セグメント = 15 秒分しか返さない
        sliding window であり、ffmpeg で HLS VOD 扱いさせると error 183 で
        parse 失敗する。対策として **start_at を 15 秒刻みで進めて medialist
        を複数回 fetch → 各 segment を並列 DL → 連結 → ffmpeg で remux** する。

        並列度 8 で約 8-15x realtime の実効速度が出る。

    Returns:
        成功なら True
    """
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    output_path.parent.mkdir(parents=True, exist_ok=True)
    start_dt = start_time.astimezone(JST)
    end_dt = end_time.astimezone(JST)
    duration_sec = int((end_dt - start_dt).total_seconds())
    end_at_full = end_dt.strftime("%Y%m%d%H%M%S")

    logger.info(
        "Radiko timefree DL: %s %s-%s (%d秒) -> %s",
        station_id,
        start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        end_dt.strftime("%H:%M:%S"),
        duration_sec,
        output_path.name,
    )

    # 15 秒刻みの start_at リストを生成
    STEP = 15
    steps: list[str] = []
    cur = start_dt
    while cur < end_dt:
        steps.append(cur.strftime("%Y%m%d%H%M%S"))
        cur += timedelta(seconds=STEP)
    logger.info("timefree window 数: %d (各 %d 秒)", len(steps), STEP)

    # 各 step の medialist を並列 fetch → セグメント URL リストを組み立てる
    def _fetch_one(start_at: str) -> tuple[int, list[str]]:
        segs, _ = _fetch_timefree_segments(auth, station_id, start_at, end_at_full)
        return (int(start_at), segs)

    step_segments: dict[int, list[str]] = {}
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        for key, segs in pool.map(_fetch_one, steps):
            step_segments[key] = segs

    # 時刻順にセグメント URL を連結 (重複除外)
    seen: set[str] = set()
    ordered_segs: list[str] = []
    for key in sorted(step_segments):
        for url in step_segments[key]:
            # URL の末尾 .aac ファイル名で重複判定
            name = url.split("/")[-1].split("?")[0]
            if name in seen:
                continue
            seen.add(name)
            ordered_segs.append(url)

    if not ordered_segs:
        logger.error("セグメント取得失敗: 対象範囲のセグメントが0件")
        return False
    logger.info("合計セグメント数: %d (重複除外後)", len(ordered_segs))

    # 各セグメントを並列 DL → バイナリ配列 (idx 順)
    seg_bytes: list[bytes | None] = [None] * len(ordered_segs)

    def _dl(idx: int) -> tuple[int, bytes | None]:
        return idx, _download_segment(ordered_segs[idx], auth)

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        for idx, data in pool.map(_dl, range(len(ordered_segs))):
            seg_bytes[idx] = data

    missing = sum(1 for b in seg_bytes if not b)
    if missing > 0:
        logger.warning("セグメント欠損: %d / %d", missing, len(ordered_segs))
    valid_bytes = [b for b in seg_bytes if b]
    if not valid_bytes:
        logger.error("全セグメント取得失敗")
        return False

    # バイナリ連結 → 一時 AAC ファイル
    tmp_aac = output_path.with_suffix(".aac.tmp")
    total = 0
    with open(tmp_aac, "wb") as f:
        for b in valid_bytes:
            f.write(b)
            total += len(b)
    logger.info("連結完了: %d bytes", total)

    # ffmpeg で AAC → M4A にリミックス (moov atom 付与)
    cmd = [
        ffmpeg_path, "-y",
        "-i", str(tmp_aac),
        "-c", "copy",
        str(output_path),
    ]
    try:
        proc = run_captured(cmd, timeout_sec=300, deadline=deadline)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.error("ffmpeg リミックス失敗: %s", e)
        tmp_aac.unlink(missing_ok=True)
        return False
    tmp_aac.unlink(missing_ok=True)

    if proc.returncode != 0:
        logger.error(
            "ffmpeg リミックス非0終了 (code=%d): %s",
            proc.returncode, proc.stderr.decode(errors="replace")[-400:],
        )
        return False

    if not (output_path.exists() and output_path.stat().st_size > 0):
        logger.error("出力ファイルが生成されない")
        return False

    logger.info(
        "timefree DL 完了: %s (%.1f MB)",
        output_path.name, output_path.stat().st_size / 1024 / 1024,
    )
    return True

