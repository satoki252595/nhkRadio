"""NHK ラジオ録音ツール (タイムフリー ダウンロード型)。

GitHub Actions の日次ジョブとして動作する。前日放送された購読番組を
Radiko タイムフリー API (放送後 7 日以内取得可能) から一括ダウンロードし、
Notion データベースにアップロードする。

v1 (ライブ録音) の致命的な問題:
- GitHub Actions cron の発火漏れと 13-46 分遅延
- VPN Gate の出口エリアがランダム (kanto 期待→JP40 福岡接続 等)
- 並列ジョブの Notion アップロード TOCTOU race
- live HLS 録音の timing 依存 (PRE_ROLL/POST_ROLL/broadcast day 境界)
- ffmpeg timeout vs multipart upload retry の競合

v2 (このファイル) は上記全てを「live 録音をやめる」ことで解決する。
放送後にダウンロードするので、いつ cron が起動しようと同じ結果が得られる。
"""

import argparse
import json
import logging
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import radiko as radiko_mod
from .api import Program, fetch_programs
from .config import Config, load_config
from .matcher import filter_by_series, filter_programs
from .notion import upload_recording
from .recorder import make_output_path


def _load_programs_from_json(json_path: Path) -> list[Program]:
    """data/programs-YYYY-MM-DD.json を読んで Program リストに変換する。

    NHK API v3 は過去日付の番組表を 400 で拒否するため、data-update
    ワークフローが毎日生成してリポジトリに commit している既存 JSON を
    直接読むのが確実。NHK / Radiko を区別せず両方含まれている。
    """
    if not json_path.exists():
        return []
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    programs: list[Program] = []
    for p in data.get("programs", []):
        try:
            programs.append(Program(
                id=p.get("id", ""),
                service=p.get("service", ""),
                title=p.get("title", ""),
                subtitle=p.get("subtitle", ""),
                content=p.get("content", ""),
                start_time=datetime.fromisoformat(p["start_time"]),
                end_time=datetime.fromisoformat(p["end_time"]),
                series_id=p.get("series_id", ""),
                series_name=p.get("series_name", ""),
                episode_name=p.get("episode_name", ""),
                genre=p.get("genre", []) or [],
                area=p.get("area", "") or "",
            ))
        except (KeyError, ValueError):
            continue
    return programs

JST = timezone(timedelta(hours=9))

# NHK / Radiko の放送日は JST 5:00 - 翌 4:55
BROADCAST_DAY_HOUR = 5


def _broadcast_date(dt: datetime) -> str:
    """壁時計 datetime から放送日 (YYYY-MM-DD) を計算する。"""
    return (dt - timedelta(hours=BROADCAST_DAY_HOUR)).strftime("%Y-%m-%d")


def _load_subscriptions(source: str) -> tuple[list[str], list[str]]:
    """購読シリーズ ID とキーワードを JSON から読み込む。

    subscriptions.json の keywords は空配列でもそのまま尊重する
    (config のデフォルトにフォールバックしない)。
    """
    if source.startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(source, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    else:
        p = Path(source)
        if not p.exists():
            return [], []
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    if isinstance(data, list):
        return data, []
    return data.get("series_ids", []), data.get("keywords", [])


def _find_nhk_stations(stations: dict[str, str]) -> tuple[str | None, str | None]:
    """接続中の Radiko area で聴取可能な NHK AM/FM 局の station_id を返す。

    NHK r1 (AM 第1) → Tokyo=JOAK, Osaka=JOBK, Nagoya=JOCK 等
    NHK r3 (FM)     → Tokyo=JOAK-FM, Osaka=JOBK-FM, 等

    VPN Gate の出口エリアに依存して使える局が変わるので、動的に発見する。
    """
    am, fm = None, None
    for sid in sorted(stations):
        name = stations[sid]
        if "NHK" not in name:
            continue
        # FM 優先判定
        if "FM" in name or sid.endswith("-FM"):
            if fm is None:
                fm = sid
        else:
            if am is None:
                am = sid
    return am, fm


def _service_to_station(
    service: str, nhk_am: str | None, nhk_fm: str | None
) -> str | None:
    """Program.service を Radiko の station_id にマップする。

    - "r1" → NHK AM 局 (JOAK/JOBK/...)
    - "r3" → NHK FM 局 (JOAK-FM/JOBK-FM/...)
    - "radiko:ABC" → "ABC"
    """
    if service == "r1":
        return nhk_am
    if service == "r3":
        return nhk_fm
    if service.startswith("radiko:"):
        return service.split(":", 1)[1]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NHK ラジオ タイムフリー ダウンロード (v2)",
    )
    parser.add_argument("--config", help="設定ファイルのパス")
    parser.add_argument(
        "--subscriptions", metavar="PATH_OR_URL", required=True,
        help="購読シリーズ JSON (ファイルパス または http(s) URL)",
    )
    parser.add_argument(
        "--target-date", metavar="YYYY-MM-DD",
        help="対象放送日 (デフォルト: 実行時点の 1 日前の broadcast day)",
    )
    parser.add_argument(
        "--days", type=int, default=1,
        help="何日分を対象にするか (デフォルト: 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="録音せず対象番組一覧のみ表示",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    # 購読読み込み
    series_ids, keywords = _load_subscriptions(args.subscriptions)
    logger.info("購読: %d シリーズ + %d キーワード", len(series_ids), len(keywords))

    # 対象日の決定 (デフォルト: 昨日の broadcast day を起点に --days 分遡る)
    now = datetime.now(JST)
    if args.target_date:
        base_date = datetime.strptime(args.target_date, "%Y-%m-%d").replace(tzinfo=JST)
    else:
        # 「現在の broadcast day の前日」を起点にする。
        # (現在 broadcast day はまだ完了していないので timefree に載っていない可能性)
        today_bd = datetime.strptime(_broadcast_date(now), "%Y-%m-%d").replace(tzinfo=JST)
        base_date = today_bd - timedelta(days=1)
    target_dates = [
        (base_date - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(args.days)
    ]
    logger.info("対象 broadcast day: %s", target_dates)

    # Radiko 認証 (VPN 接続後に JP IP を得ている前提)
    logger.info("Radiko 認証中...")
    radiko_auth = radiko_mod.authenticate()
    if not radiko_auth:
        logger.error("Radiko 認証失敗。日本 IP に接続できていない可能性があります。")
        sys.exit(2)
    logger.info("Radiko 認証成功: area=%s (%s)", radiko_auth.area_id, radiko_auth.area_name)

    # 当該エリアで聴取可能な NHK 局を発見
    area_stations = radiko_mod.fetch_stations(radiko_auth.area_id)
    nhk_am, nhk_fm = _find_nhk_stations(area_stations)
    logger.info("このエリアの NHK 局: AM=%s, FM=%s", nhk_am, nhk_fm)

    # 番組表の取得 + フィルタリング (対象日すべて)
    # NHK API v3 は過去日付を 400 で拒否するため、data-update ワークフローが
    # 毎日 JST 04:30 に生成して commit する data/programs-YYYY-MM-DD.json を
    # 読む (NHK + Radiko 両方含まれている)。未来日付や JSON が未生成の場合は
    # NHK API + Radiko API にフォールバック。
    data_dir = Path(__file__).resolve().parent.parent / "data"
    matched: list[Program] = []
    seen_ids: set[str] = set()
    for target_date in target_dates:
        logger.info("番組表取得: %s", target_date)
        json_path = data_dir / f"programs-{target_date}.json"
        programs = _load_programs_from_json(json_path)
        if programs:
            logger.info("  → JSON から %d 件ロード", len(programs))
        else:
            logger.info("  → JSON が無いため API にフォールバック")
            programs = fetch_programs(config, target_date)
            # Radiko 番組も API から追加
            rp = radiko_mod.fetch_programs(radiko_auth.area_id, target_date)
            from .data_export import _radiko_to_program
            for p in rp:
                programs.append(_radiko_to_program(p))

        # シリーズ / キーワード マッチング
        by_series = filter_by_series(programs, series_ids) if series_ids else []
        by_keyword = filter_programs(programs, keywords) if keywords else []
        for p in by_series + by_keyword:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                matched.append(p)

    # NHK サイマル重複排除 (NHK 本家 r1/r3 を優先して radiko:JOAK 等を削除)
    from .data_export import dedupe_programs
    before_dedup = len(matched)
    matched = dedupe_programs(matched)
    if len(matched) < before_dedup:
        logger.info("サイマル重複排除: %d → %d 件", before_dedup, len(matched))

    matched.sort(key=lambda p: p.start_time)

    logger.info("=== 対象番組 (%d 件) ===", len(matched))
    for p in matched:
        logger.info(
            "  [%s] %s %s-%s %s (%d分)",
            p.service,
            p.start_time.strftime("%Y-%m-%d"),
            p.start_time.strftime("%H:%M"),
            p.end_time.strftime("%H:%M"),
            p.title[:50],
            p.duration // 60,
        )

    if args.dry_run:
        logger.info("ドライラン完了")
        return

    if not matched:
        logger.info("対象番組なし、終了")
        return

    # 並列ダウンロード + アップロード
    # Radiko timefree は 1x realtime でしか取れない (chunklist window が時間と
    # ともに進むため) ので、複数番組を threading で同時並列実行して総時間を
    # max(番組長) + バッファに収める。
    counters = {"success": 0, "failed": 0, "skipped": 0}
    counters_lock = threading.Lock()

    def _process_one(p: Program) -> None:
        # 未放送はスキップ (timefree にまだ無い)
        if p.end_time > now:
            logger.info(
                "未放送スキップ: [%s] %s %s-%s %s",
                p.service,
                p.start_time.strftime("%Y-%m-%d"),
                p.start_time.strftime("%H:%M"),
                p.end_time.strftime("%H:%M"),
                p.title[:50],
            )
            with counters_lock:
                counters["skipped"] += 1
            return

        station_id = _service_to_station(p.service, nhk_am, nhk_fm)
        if not station_id:
            logger.warning(
                "ステーション ID 解決不可: service=%s area=%s → %s",
                p.service, radiko_auth.area_id, p.title[:50],
            )
            with counters_lock:
                counters["failed"] += 1
            return

        # このエリアで当該局が聴取可能か確認 (NHK 以外)
        if p.service.startswith("radiko:") and station_id not in area_stations:
            logger.warning(
                "当該エリア (%s) で聴取不可: station=%s → %s",
                radiko_auth.area_id, station_id, p.title[:50],
            )
            with counters_lock:
                counters["failed"] += 1
            return

        output_path = make_output_path(config.output_dir, p)
        logger.info("→ ダウンロード: [%s→%s] %s", p.service, station_id, p.title[:50])

        ok = radiko_mod.download_timefree(
            radiko_auth, station_id,
            p.start_time, p.end_time,
            output_path, config.ffmpeg_path,
        )
        if not ok:
            logger.error("ダウンロード失敗: %s", p.title[:50])
            with counters_lock:
                counters["failed"] += 1
            return

        if config.notion_token and config.notion_database_id:
            search_text = f"{p.title} {p.subtitle} {p.content}"
            matched_kw = [kw for kw in keywords if kw in search_text]
            try:
                uploaded = upload_recording(config, p, output_path, matched_kw)
            except Exception as e:
                logger.error("Notion アップロード失敗: %s - %s", p.title[:50], e)
                uploaded = False
            with counters_lock:
                if uploaded:
                    counters["success"] += 1
                else:
                    counters["failed"] += 1
        else:
            with counters_lock:
                counters["success"] += 1

        # 完了後にファイル削除 (ディスク節約)
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass

    logger.info("並列ダウンロード開始: %d 番組", len(matched))
    threads: list[threading.Thread] = []
    for p in matched:
        t = threading.Thread(target=_process_one, args=(p,), daemon=True,
                             name=f"dl-{p.id[:8]}")
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    logger.info(
        "=== 完了: 成功 %d / 失敗 %d / スキップ %d ===",
        counters["success"], counters["failed"], counters["skipped"],
    )
    # 失敗があってもジョブ自体は成功扱いにする (部分成功を許容)
    # ただし全滅なら非ゼロで終了
    if counters["failed"] > 0 and counters["success"] == 0 and counters["skipped"] == 0:
        sys.exit(3)


if __name__ == "__main__":
    main()
