"""NHK らじる★らじる 聴き逃し (on-demand) クライアント。

Radiko タイムフリー は権利保護のため NHK の多くの番組を「配信停止」扱いとし、
アクセスすると「大変申し訳ありませんが、現在お聞きいただいているこの番組は
配信を停止しております」という 15 秒アナウンスのループ音源が返ってくる
(2026-04-14 のインシデント: ラジオビジネス英語 Lesson(10), 名演奏ライブラリー,
ニュースで学ぶ現代英語 の 3 件が全て配信停止アナウンスに置換されていた)。

NHK 本家番組は Radiko ではなく、NHK が直接提供する「聴き逃し配信」
(radiru on-demand) からダウンロードする。

特徴:
- API (radio-api/series, new_arrivals) は日本国外 IP でも取得可能
- ストリーム配信 (vod-stream.nhk.jp) は **日本国内 IP 限定** で、国外から
  m3u8 を叩くと HTTP 403 Forbidden が返る。GitHub Actions などのクラウド
  ランナーから取得する場合は VPN で日本 IP に乗せ替える必要がある。
- 配信停止の心配なし (NHK 直営なので権利処理済み)
- 配信期間は放送後 1 週間が多い (番組により変動)
- m3u8 を ffmpeg で remux するだけ (Radiko のような認証・アセンブリ不要)

API エンドポイント (2024-06 リニューアル後、非公式ながら公式 Web が利用):
- new_arrivals: 新着エピソード一覧
  https://www.nhk.or.jp/radio-api/app/v1/web/ondemand/corners/new_arrivals
- series: 指定シリーズの配信中エピソード一覧 + stream_url
  https://www.nhk.or.jp/radio-api/app/v1/web/ondemand/series
      ?site_id={series_site_id}&corner_site_id={corner_site_id}

series_site_id は NHK API v3 の `radioSeriesId` と同値 (例: 368315KKP8 =
ラジオビジネス英語) なので、既存の購読シリーズ ID をそのまま流用できる。
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .subprocess_utils import run_captured

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

NEW_ARRIVALS_URL = (
    "https://www.nhk.or.jp/radio-api/app/v1/web/ondemand/corners/new_arrivals"
)
SERIES_URL = "https://www.nhk.or.jp/radio-api/app/v1/web/ondemand/series"

# vod-stream.nhk.jp の HLS playlist は API が返す stream_url そのものではなく、
# 末尾の ".m4a" を取り除いて "/index.m3u8" を足したパスにある。
# yt-dlp 公式 NHK extractor (yt_dlp/extractor/nhk.py) と同じ変換を行う:
#     audio_path = remove_end(stream_url, ".m4a")
#     playlist  = f"{audio_path}/index.m3u8"
# API が ".m4a" 付きを返すバージョンと付かないバージョンの両方が観測されているので
# rstrip("/") + remove_end(".m4a") の両方を行ってから "/index.m3u8" を付ける。
# (2026-05 観測: API が ".m4a" 抜きの URL を返すようになり、その URL を素のまま
#  叩くと vod-stream.nhk.jp が 403 を返して radiru DL が全件失敗していた)


def _to_m3u8_url(stream_url: str) -> str:
    """API の stream_url を実際にダウンロード可能な HLS playlist URL に変換する。"""
    if stream_url.endswith(".m3u8"):
        return stream_url
    base = stream_url
    if base.endswith(".m4a"):
        base = base[:-4]
    return base.rstrip("/") + "/index.m3u8"


# vod-stream.nhk.jp CDN への保険として、ブラウザ風 User-Agent と
# NHK ラジオサイトの Referer を付与する (yt-dlp 公式 extractor は
# 設定していないが、CDN が将来 UA チェックを足したときの防御として
# 残しておく)。
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_REFERER = "https://www.nhk.or.jp/radio/"


@dataclass
class RadiruEpisode:
    series_site_id: str
    corner_site_id: str
    program_title: str
    start_time: datetime
    end_time: datetime
    stream_url: str


def _parse_aa_time_range(aa_contents_id: str) -> tuple[datetime, datetime] | None:
    """aa_contents_id の末尾フィールドから (start, end) を取り出す。

    aa_contents_id フォーマット例:
        "[radio]vod;ラジオビジネス英語 Lesson (10);r3,130;2026041467875;
         2026-04-14T23:20:00+09:00_2026-04-14T23:35:00+09:00"
    """
    parts = aa_contents_id.split(";")
    if len(parts) < 5:
        return None
    time_part = parts[-1]
    if "_" not in time_part:
        return None
    a, b = time_part.split("_", 1)
    try:
        return datetime.fromisoformat(a), datetime.fromisoformat(b)
    except ValueError:
        return None


def fetch_series_episodes(
    series_site_id: str,
    corner_site_id: str = "01",
    timeout: float = 30.0,
) -> list[RadiruEpisode]:
    """指定シリーズの聴き逃しエピソード一覧を取得する。

    JSON 以外の応答 (HTML エラー等) が返った場合は空リストを返す
    (例外を握りつぶして処理を続行する。NHK 側の一時的な不調でも
    他シリーズの取得は止めない方針)。
    """
    try:
        r = httpx.get(
            SERIES_URL,
            params={
                "site_id": series_site_id,
                "corner_site_id": corner_site_id,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
        logger.warning(
            "radiru series fetch 失敗 (%s/%s): %s",
            series_site_id, corner_site_id, e,
        )
        return []

    episodes: list[RadiruEpisode] = []
    raw_episodes = data.get("episodes", []) or []
    skipped_no_time = 0
    skipped_no_url = 0
    for ep in raw_episodes:
        times = _parse_aa_time_range(ep.get("aa_contents_id", ""))
        if not times:
            skipped_no_time += 1
            continue
        stream_url = ep.get("stream_url", "")
        if not stream_url:
            skipped_no_url += 1
            continue
        episodes.append(
            RadiruEpisode(
                series_site_id=series_site_id,
                corner_site_id=corner_site_id,
                program_title=ep.get("program_title", ""),
                start_time=times[0],
                end_time=times[1],
                stream_url=stream_url,
            )
        )
    if raw_episodes and not episodes:
        logger.warning(
            "radiru series 応答にエピソードはあるが全件スキップ "
            "(%s/%s): raw=%d no_time=%d no_url=%d",
            series_site_id, corner_site_id,
            len(raw_episodes), skipped_no_time, skipped_no_url,
        )
    return episodes


def _discover_corners(series_site_id: str, timeout: float = 30.0) -> list[str]:
    """new_arrivals を走査して指定シリーズで使われている corner_site_id を列挙する。

    殆どの単発番組は corner_site_id=="01" で取得できるが、長時間番組
    (Ｎらじ等) は複数 corner (ニュース・特集・コーナー別) で配信されるため
    "01" のみでは取りこぼす。
    """
    try:
        r = httpx.get(NEW_ARRIVALS_URL, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.debug("radiru new_arrivals fetch 失敗: %s", e)
        return []

    corners: list[str] = []
    seen: set[str] = set()
    for c in data.get("corners", []):
        if c.get("series_site_id") != series_site_id:
            continue
        cid = str(c.get("corner_site_id", ""))
        if cid and cid not in seen:
            seen.add(cid)
            corners.append(cid)
    return corners


def find_episode(
    series_site_id: str,
    start_time: datetime,
    tolerance_sec: int = 120,
    preferred_corner: str = "01",
    expected_title: str = "",
    brute_force_corner_max: int = 30,
) -> RadiruEpisode | None:
    """指定シリーズ・開始時刻のエピソードを探す。

    対応戦略 (順に試行):
    1. corner_site_id="01" で時刻一致検索 (大半の番組はここでヒット)
    2. new_arrivals 走査で発見した他 corner で時刻一致検索
       (N らじ等の複数 corner 番組向け)
    3. corner_site_id="01" がエピソード 0 件のとき、"02".."30" を順次
       ブルートフォース試行 (語学・音楽番組で "01" 以外のコーナーに
       割り当てられているケースを救済)
    4. 全 corner で集めたエピソードに対し、expected_title による
       タイトルマッチで救済:
         a. 正規化タイトル完全一致 (例: 再放送枠の枠時刻違い吸収)
         b. NHK 側のシリーズ名プレフィックスを除いた末尾一致
            (radiru が "Lesson (10)" だけ返すケースを救済)
       "Lesson (9)" と "Lesson (10)" のような異なるエピソードは
       正規化後も別タイトルなので誤マッチしない。

    Returns:
        マッチしたエピソード、または None (配信期間切れ/未公開/識別不能)
    """
    target = start_time.astimezone(JST)

    tried_corners: list[str] = [preferred_corner]
    all_episodes: list[RadiruEpisode] = list(
        fetch_series_episodes(series_site_id, preferred_corner)
    )

    best = _best_match(all_episodes, target, tolerance_sec)
    if best is not None:
        return best

    for cid in _discover_corners(series_site_id):
        if cid in tried_corners:
            continue
        tried_corners.append(cid)
        extra = fetch_series_episodes(series_site_id, cid)
        all_episodes.extend(extra)
        best = _best_match(extra, target, tolerance_sec)
        if best is not None:
            return best

    # corner "01" 不発 + new_arrivals 不発の場合のブルートフォース。
    # 語学番組や週末番組は new_arrivals にエントリされない (ピックアップ
    # されない) ことがあり、その場合は "02".."30" を直接叩いて拾う。
    if not all_episodes:
        for i in range(2, brute_force_corner_max + 1):
            cid = f"{i:02d}"
            if cid in tried_corners:
                continue
            tried_corners.append(cid)
            extra = fetch_series_episodes(series_site_id, cid)
            if not extra:
                continue
            logger.info(
                "radiru ブルートフォースで発見: series=%s corner=%s episodes=%d",
                series_site_id, cid, len(extra),
            )
            all_episodes.extend(extra)
            best = _best_match(extra, target, tolerance_sec)
            if best is not None:
                return best
            break

    if expected_title:
        title_hit = _match_by_title(all_episodes, expected_title)
        if title_hit is not None:
            logger.info(
                "radiru タイトル一致で解決 (再放送扱い): series=%s 枠=%s "
                "実エピソード=%s (%s)",
                series_site_id, target.isoformat(),
                title_hit.program_title, title_hit.start_time.isoformat(),
            )
            return title_hit

        title_hit = _match_by_title_lenient(all_episodes, expected_title)
        if title_hit is not None:
            logger.info(
                "radiru タイトル末尾一致で解決 (シリーズ名プレフィックス差異): "
                "series=%s 枠=%s NHKタイトル=%r radiruタイトル=%r (%s)",
                series_site_id, target.isoformat(),
                expected_title[:60], title_hit.program_title,
                title_hit.start_time.isoformat(),
            )
            return title_hit

    if all_episodes:
        sample = [
            (ep.program_title[:60], ep.start_time.isoformat())
            for ep in all_episodes[:5]
        ]
        logger.warning(
            "radiru エピソード未発見 (候補あり): series=%s target=%s "
            "title=%r tried_corners=%s episodes=%d sample=%s",
            series_site_id, target.isoformat(),
            expected_title[:60], tried_corners, len(all_episodes), sample,
        )
    else:
        logger.warning(
            "radiru エピソード未発見 (候補なし): series=%s target=%s "
            "title=%r tried_corners=%s",
            series_site_id, target.isoformat(),
            expected_title[:60], tried_corners,
        )
    return None


def _normalize_title_strict(title: str) -> str:
    """radiru タイトル比較用の正規化 (エピソード番号は保持する)。

    schedule_verify._normalize_title は回数マーカー "(9)/(10)/Lesson(9)" を
    剥がすため、本件 (再放送の同一コンテンツ判定) には使えない。
    - NHK キャッシュ "ラジオビジネス英語 Ｌｅｓｓｏｎ（１０）"
    - radiru  "ラジオビジネス英語 Lesson (10)"
    を同一と見なし、
    - radiru Lesson (9)
    とは**別物**と見なす必要があるため、ここでは:
        1. 全角英数 → 半角
        2. 局名プレフィックス [NHK FM…] を除去
        3. 連続空白を単一半角空白に圧縮
    **までしか行わず**、回数表記はそのまま比較対象に残す。
    """
    import re
    if not title:
        return ""
    # 先頭の [局名] を除去
    t = re.sub(r"^\[[^\]]+\]\s*", "", title)
    # 全角英数・括弧を半角に
    out: list[str] = []
    for ch in t:
        code = ord(ch)
        if 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A or 0xFF10 <= code <= 0xFF19:
            out.append(chr(code - 0xFEE0))
        elif ch == "（":
            out.append("(")
        elif ch == "）":
            out.append(")")
        else:
            out.append(ch)
    t = "".join(out)
    # 連続空白 (全角含む) を単一半角空白に
    t = re.sub(r"[\s　]+", " ", t).strip()
    # 括弧まわりのスペースを除去 ("Lesson (10)" と "Lesson(10)" を同一視)
    t = re.sub(r"\s*([()])\s*", r"\1", t)
    return t


def _match_by_title(
    episodes: list[RadiruEpisode], expected_title: str,
) -> RadiruEpisode | None:
    """同一シリーズ内で正規化タイトル完全一致のエピソードを返す。"""
    norm_target = _normalize_title_strict(expected_title)
    if not norm_target:
        return None
    for ep in episodes:
        if _normalize_title_strict(ep.program_title) == norm_target:
            return ep
    return None


def _match_by_title_lenient(
    episodes: list[RadiruEpisode], expected_title: str,
) -> RadiruEpisode | None:
    """シリーズ名プレフィックスの差異を吸収するタイトル末尾一致。

    NHK 番組表 v3 と radiru の program_title でシリーズ名の付き方が
    異なるケースを救済する:
        NHK    = "ラジオビジネス英語 Lesson(10)"
        radiru = "Lesson(10)"  ← 番組表側のシリーズ名が付かない

    安全条件として「半角スペース区切りの完全な末尾一致」を要求する。
    これにより "Lesson(1)" と "Lesson(10)" のような部分文字列の
    誤マッチは発生しない (空白で区切られた完全な単語境界での比較)。

    Returns:
        該当エピソード、または None。
    """
    norm_target = _normalize_title_strict(expected_title)
    if not norm_target:
        return None

    for ep in episodes:
        ep_norm = _normalize_title_strict(ep.program_title)
        if not ep_norm:
            continue
        if ep_norm == norm_target:
            return ep
        # NHK タイトルが radiru タイトルを末尾に含む (一般的なケース)
        if norm_target.endswith(" " + ep_norm):
            return ep
        # 逆向き: radiru タイトルが NHK タイトルを末尾に含む (稀)
        if ep_norm.endswith(" " + norm_target):
            return ep
    return None


def _best_match(
    episodes: list[RadiruEpisode],
    target: datetime,
    tolerance_sec: int,
) -> RadiruEpisode | None:
    best: RadiruEpisode | None = None
    best_diff = tolerance_sec + 1
    for ep in episodes:
        diff = abs((ep.start_time - target).total_seconds())
        if diff == 0:
            return ep
        if diff <= tolerance_sec and diff < best_diff:
            best = ep
            best_diff = diff
    return best


def download_ondemand(
    stream_url: str,
    output_path: Path,
    ffmpeg_path: str = "ffmpeg",
    timeout_sec: int = 600,
    *,
    deadline: float | None = None,
) -> bool:
    """聴き逃し m3u8 を yt-dlp で M4A に保存する。

    Note on timeout_sec=600 (10 min):
        旧値 1800s (30 min) は HLS stall 時に 1 件あたり 30 分待つことになり、
        6 件で 3 時間消費して GitHub Actions runner が preemption されやすかった
        (2026-05-23 incident: 1h11m で job cancel)。実測の正常 DL 速度は 5〜10x
        realtime (2 時間番組を 15〜25 分) なので、10 分超過は明らかに stall。
        fail-fast して次の VPN サーバー (= 別 area) で retry した方が速い。

    **なぜ yt-dlp か**: ffmpeg の HLS demuxer 経由だと、一部番組 (115 分クラス
    の音楽番組、例: 2026-04-12 名演奏ライブラリー コルトー) で
    `Multiple RDBs per frame with CRC is not implemented` が発生し、**24 秒で
    途中停止**する。これは ffmpeg 8.1 の AAC デコーダがこの RDB 変種を扱えない
    ため。一方 yt-dlp は native HLS downloader で各セグメントを個別 HTTP
    フェッチして ADTS 連結するだけなので ffmpeg の AAC デコーダを介さず、
    全番組で安定動作する (実測: 115 分番組を 41 MB / 113 分で取得成功)。

    フォールバック: yt-dlp が未インストールなら ffmpeg に落とす (短い番組は
    これで通ることが多いため)。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    playlist_url = _to_m3u8_url(stream_url)
    logger.info(
        "radiru DL: %s (api=%s) → %s",
        playlist_url, stream_url, output_path.name,
    )

    ytdlp_bin = shutil.which("yt-dlp")
    if ytdlp_bin:
        ytdlp_result = _try_ytdlp(
            ytdlp_bin, playlist_url, output_path, timeout_sec,
            deadline=deadline,
        )
        if ytdlp_result:
            logger.info(
                "radiru DL 完了 (yt-dlp): %s (%.1f MB)",
                output_path.name, output_path.stat().st_size / 1024 / 1024,
            )
            return True
        if ytdlp_result is None:
            # yt-dlp が timeout_sec (600s) 経ってもセグメントを取得できなかった
            # 場合、ffmpeg フォールバックは同一 URL・同一 VPN 経路を再度叩く
            # だけなので、帯域不足/CDN 側の絞り込みが原因なら同じ理由で
            # 再度タイムアウトする。2026-06〜07 の障害ログで実測: yt-dlp
            # タイムアウト後の ffmpeg フォールバックは 100% (観測した全件) が
            # 同様にタイムアウトするか「出力サイズ過小」で失敗しており、
            # 1 件あたり 600s → 1200s に倍化するだけで成功に繋がったことが
            # ない。fail-fast して次の VPN パス (=別サーバー/別経路) に
            # 賭けた方が時間対効果が高いので、ここでは ffmpeg を試さない。
            logger.warning(
                "yt-dlp がタイムアウト、同一経路の ffmpeg 再試行は"
                "スキップして次の VPN パスに委ねる",
            )
            return False
        logger.warning("yt-dlp 失敗、ffmpeg フォールバック試行")

    # Fallback: ffmpeg direct HLS. 上述の Multiple RDBs 問題で長尺番組は
    # 失敗するが、短い番組 (通常の語学・ニュース 15 分枠) は通ることが多い。
    copy_cmd = [
        ffmpeg_path, "-y",
        "-user_agent", _BROWSER_UA,
        "-headers", f"Referer: {_REFERER}\r\n",
        "-i", playlist_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        str(output_path),
    ]
    if _try_ffmpeg(copy_cmd, output_path, timeout_sec, deadline=deadline):
        logger.info(
            "radiru DL 完了 (ffmpeg copy): %s (%.1f MB)",
            output_path.name, output_path.stat().st_size / 1024 / 1024,
        )
        return True

    logger.error(
        "radiru DL 完全失敗 (yt-dlp/ffmpeg 両方): %s", output_path.name,
    )
    return False


def _try_ytdlp(
    ytdlp_bin: str, stream_url: str, output_path: Path, timeout_sec: int,
    *,
    deadline: float | None = None,
) -> bool | None:
    """yt-dlp で HLS を取得し M4A で保存する。

    yt-dlp はデフォルトで拡張子を自動付与するため、`-o <path_without_ext>`
    で拡張子を指定しない形式で渡し、実際の出力は `<path>.mp4` か `.m4a`
    で生成される。取得後に期待パスへ rename する。

    Returns:
        True: 成功
        False: 失敗 (タイムアウト以外。バイナリ不在・非 0 終了・出力異常等)
        None: timeout_sec 経過によるタイムアウト (呼び出し元はこれを見て
              ffmpeg フォールバックを打ち切るかどうか判断する)
    """
    # yt-dlp は拡張子をコンテナから決めるので、出力名を拡張子抜きにする
    tmp_base = output_path.with_suffix("")

    # 過去の失敗録音ファイルが残っていると、yt-dlp が生成した別拡張子の
    # 正常ファイルを見落として古いファイルを「produced」と誤認する。
    # 走る前に候補拡張子を全て削除する。
    for ext in (".m4a", ".mp4", ".aac", ".mp4.part", ".part"):
        stale = Path(f"{tmp_base}{ext}")
        stale.unlink(missing_ok=True)

    cmd = [
        ytdlp_bin,
        "--no-progress",
        "--hls-prefer-native",
        "--user-agent", _BROWSER_UA,
        "--referer", _REFERER,
        "-o", f"{tmp_base}.%(ext)s",
        stream_url,
    ]
    try:
        proc = run_captured(cmd, timeout_sec=timeout_sec, deadline=deadline)
    except subprocess.TimeoutExpired as e:
        logger.warning("yt-dlp タイムアウト: %s", e)
        return None
    except FileNotFoundError as e:
        logger.warning("yt-dlp 実行失敗: %s", e)
        return False
    if proc.returncode != 0:
        logger.warning(
            "yt-dlp 非 0 終了 (code=%d): %s",
            proc.returncode, proc.stderr.decode(errors="replace")[-300:],
        )
        return False

    # yt-dlp が生成した実ファイル (.mp4 / .m4a / .aac) を探す
    produced: Path | None = None
    for ext in (".m4a", ".mp4", ".aac"):
        cand = Path(f"{tmp_base}{ext}")
        if cand.exists() and cand.stat().st_size > 100_000:
            produced = cand
            break
    if not produced:
        logger.warning("yt-dlp 出力ファイル不見当 (base=%s)", tmp_base)
        return False

    if produced != output_path:
        try:
            produced.rename(output_path)
        except OSError as e:
            logger.warning("yt-dlp 出力 rename 失敗: %s", e)
            return False

    duration = _probe_duration(output_path, deadline=deadline)
    if duration is not None and duration < 60.0:
        logger.warning(
            "yt-dlp 出力の実尺が短すぎる (%.1f 秒)", duration,
        )
        return False
    return True


def _try_ffmpeg(
    cmd: list[str],
    output_path: Path,
    timeout_sec: int,
    *,
    deadline: float | None = None,
) -> bool:
    """ffmpeg を実行し、出力が「妥当」なら True を返す (フォールバック用)。"""
    try:
        proc = run_captured(cmd, timeout_sec=timeout_sec, deadline=deadline)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.error("ffmpeg 実行失敗: %s", e)
        return False
    if proc.returncode != 0:
        logger.warning(
            "ffmpeg 非 0 終了 (code=%d): %s",
            proc.returncode, proc.stderr.decode(errors="replace")[-300:],
        )
        return False
    if not (output_path.exists() and output_path.stat().st_size > 100_000):
        logger.warning("ffmpeg 出力サイズ過小")
        return False
    duration = _probe_duration(output_path, deadline=deadline)
    if duration is not None and duration < 60.0:
        logger.warning("ffmpeg 出力の実尺が短すぎる (%.1f 秒)", duration)
        return False
    return True


def _probe_duration(path: Path, *, deadline: float | None = None) -> float | None:
    """ffprobe で duration を秒数で取得する。失敗したら None。"""
    try:
        proc = run_captured(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            timeout_sec=30, deadline=deadline, text=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None
