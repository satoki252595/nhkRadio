"""NHK ラジオ録音ツール (タイムフリー + マルチ VPN パス版)。

GitHub Actions 日次ジョブで動作。前日放送された購読番組を Radiko
タイムフリー API から取得し、Notion に投入する。

v2 アーキテクチャの要点:
- リアルタイム録音ではなく timefree (放送後 7 日間取得可能)
- 1 ジョブ内で VPN を複数回張り直し、多様な Radiko エリアをカバー
- ffmpeg は 1x realtime が上限なので並列 threading で同時 DL

VPN 戦略:
1. JSON から programs 読込 → subscription filter → pending リスト
2. VPN Gate サーバーを順次試行
   a. 接続 → Radiko auth → 実 area 取得
   b. NHK (area 非依存) + このエリアで聴取可能な Radiko 局を並列 DL
   c. DL 成功した番組を pending から除外
   d. 切断
3. pending が空 or 最大 VPN 試行回数に到達で終了
"""

import argparse
import json
import logging
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import radiko as radiko_mod
from . import vpn_manager
from .api import Program, fetch_programs
from .config import Config, load_config
from .matcher import filter_by_series, filter_programs
from .notion import upload_recording
from .recorder import make_output_path
from .vpngate import fetch_jp_servers

JST = timezone(timedelta(hours=9))

# NHK / Radiko の放送日は JST 5:00 - 翌 4:55
BROADCAST_DAY_HOUR = 5

# VPN 接続の最大試行回数 (足りない area を探し続ける上限)
MAX_VPN_ATTEMPTS = 10


def _broadcast_date(dt: datetime) -> str:
    """壁時計 datetime から放送日 (YYYY-MM-DD) を計算する。"""
    return (dt - timedelta(hours=BROADCAST_DAY_HOUR)).strftime("%Y-%m-%d")


def _load_subscriptions(source: str) -> tuple[list[str], list[str]]:
    """購読シリーズ ID とキーワードを JSON から読み込む。"""
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


def _find_nhk_stations(stations: dict[str, str]) -> tuple[str | None, str | None]:
    """Radiko の当該エリアで聴取可能な NHK AM/FM 局の station_id を返す。"""
    am, fm = None, None
    for sid in sorted(stations):
        name = stations[sid]
        if "NHK" not in name:
            continue
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
    """Program.service を Radiko の station_id にマップする。"""
    if service == "r1":
        return nhk_am
    if service == "r3":
        return nhk_fm
    if service.startswith("radiko:"):
        return service.split(":", 1)[1]
    return None


def _download_and_upload(
    program: Program,
    station_id: str,
    auth: "radiko_mod.RadikoAuth",
    config: Config,
    keywords: list[str],
    counters: dict,
    counters_lock: threading.Lock,
) -> None:
    """1 番組を DL して Notion にアップする (スレッド worker)。"""
    output_path = make_output_path(config.output_dir, program)
    logger = logging.getLogger(__name__)
    logger.info("→ DL: [%s→%s] %s", program.service, station_id, program.title[:50])

    ok = radiko_mod.download_timefree(
        auth, station_id,
        program.start_time, program.end_time,
        output_path, config.ffmpeg_path,
    )
    if not ok:
        logger.error("DL 失敗: %s", program.title[:50])
        with counters_lock:
            counters["failed"] += 1
        return

    if config.notion_token and config.notion_database_id:
        search_text = f"{program.title} {program.subtitle} {program.content}"
        matched_kw = [kw for kw in keywords if kw in search_text]
        try:
            uploaded = upload_recording(config, program, output_path, matched_kw)
        except Exception as e:
            logger.error("Notion アップロード失敗: %s - %s", program.title[:50], e)
            uploaded = False
        with counters_lock:
            if uploaded:
                counters["success"] += 1
            else:
                counters["failed"] += 1
    else:
        with counters_lock:
            counters["success"] += 1

    # 完了後にファイル削除
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass


def _run_one_pass(
    pending: list[Program],
    auth: "radiko_mod.RadikoAuth",
    config: Config,
    keywords: list[str],
    counters: dict,
    counters_lock: threading.Lock,
) -> list[Program]:
    """現在の VPN セッションで取得可能な番組を並列 DL し、残りを返す。

    Args:
        pending: まだ DL できていない番組

    Returns:
        この pass で DL できなかった (次 VPN で再試行する) 番組のリスト
    """
    logger = logging.getLogger(__name__)

    # 当該エリアの聴取可能局を取得
    area_stations = radiko_mod.fetch_stations(auth.area_id)
    nhk_am, nhk_fm = _find_nhk_stations(area_stations)
    logger.info(
        "area=%s で聴取可能: NHK AM=%s FM=%s + Radiko %d 局",
        auth.area_id, nhk_am, nhk_fm, len(area_stations),
    )

    # このパスで DL 可能 / 不可能 を判定
    to_download: list[tuple[Program, str]] = []
    remaining: list[Program] = []
    now = datetime.now(JST)

    for p in pending:
        # 未放送はそもそも timefree にないので skip (次パスで試しても無意味)
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
            continue

        station_id = _service_to_station(p.service, nhk_am, nhk_fm)
        if not station_id:
            # NHK 本家なのにこのエリアで NHK 局が見つからない等。次パスに期待。
            remaining.append(p)
            continue

        # radiko:XXX の場合は当該局が聴取可能エリアに含まれるか確認
        if p.service.startswith("radiko:") and station_id not in area_stations:
            remaining.append(p)
            continue

        to_download.append((p, station_id))

    if not to_download:
        logger.info("このエリアで DL 可能な番組なし (pending %d)", len(remaining))
        return remaining

    logger.info(
        "このエリアで並列 DL: %d 番組 (残り %d は次パス)",
        len(to_download), len(remaining),
    )

    # 並列ダウンロード
    threads: list[threading.Thread] = []
    for program, station_id in to_download:
        t = threading.Thread(
            target=_download_and_upload,
            args=(program, station_id, auth, config, keywords, counters, counters_lock),
            daemon=True,
            name=f"dl-{program.id[:8]}",
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    return remaining


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
        "--max-vpn-attempts", type=int, default=MAX_VPN_ATTEMPTS,
        help="最大 VPN 試行回数 (デフォルト: 10)",
    )
    parser.add_argument(
        "--vpn-config", default="vpn.ovpn",
        help="openvpn 設定ファイルの書き出し先 (デフォルト: vpn.ovpn)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="DL せず対象番組一覧のみ表示",
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

    # 対象日の決定
    now = datetime.now(JST)
    if args.target_date:
        base_date = datetime.strptime(args.target_date, "%Y-%m-%d").replace(tzinfo=JST)
    else:
        today_bd = datetime.strptime(_broadcast_date(now), "%Y-%m-%d").replace(tzinfo=JST)
        base_date = today_bd - timedelta(days=1)
    target_dates = [
        (base_date - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(args.days)
    ]
    logger.info("対象 broadcast day: %s", target_dates)

    # 番組表の取得 & フィルタ (VPN 不要)
    # data-update ワークフローが生成する data/programs-YYYY-MM-DD.json を読む
    data_dir = Path(__file__).resolve().parent.parent / "data"
    matched: list[Program] = []
    seen_ids: set[str] = set()

    for target_date in target_dates:
        json_path = data_dir / f"programs-{target_date}.json"
        programs = _load_programs_from_json(json_path)
        if programs:
            logger.info("programs-%s.json から %d 件ロード", target_date, len(programs))
        else:
            logger.warning("programs-%s.json が存在しない、この日はスキップ", target_date)
            continue

        by_series = filter_by_series(programs, series_ids) if series_ids else []
        by_keyword = filter_programs(programs, keywords) if keywords else []
        for p in by_series + by_keyword:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                matched.append(p)

    # NHK サイマル重複排除 (NHK 本家 r1/r3 を優先)
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

    # マルチ VPN パス: 異なる area に順次接続して取得可能な分を DL
    logger.info("VPN Gate サーバーリスト取得中...")
    vpn_servers = fetch_jp_servers(limit=50)
    if not vpn_servers:
        logger.error("VPN Gate サーバー取得失敗")
        sys.exit(2)
    logger.info("VPN Gate: %d 台のサーバーを取得", len(vpn_servers))

    counters = {"success": 0, "failed": 0, "skipped": 0}
    counters_lock = threading.Lock()

    pending: list[Program] = list(matched)
    attempted_areas: set[str] = set()
    vpn_config_path = Path(args.vpn_config)

    for attempt_idx, server in enumerate(vpn_servers, start=1):
        if not pending:
            logger.info("全番組 DL 完了、VPN ループ終了")
            break
        if attempt_idx > args.max_vpn_attempts:
            logger.warning(
                "VPN 最大試行回数 %d に到達、残り %d 番組未取得",
                args.max_vpn_attempts, len(pending),
            )
            break

        logger.info(
            "=== VPN 試行 %d/%d: %s (IP=%s score=%d) ===",
            attempt_idx, args.max_vpn_attempts,
            server.hostname, server.ip, server.score,
        )

        # Config を書き出し
        try:
            server.write_ovpn(vpn_config_path)
        except OSError as e:
            logger.error("ovpn 書き出し失敗: %s", e)
            continue

        # VPN 接続
        if not vpn_manager.connect(vpn_config_path):
            logger.warning("VPN 接続失敗、次へ")
            continue

        try:
            # Radiko auth で実 area 取得
            auth = radiko_mod.authenticate()
            if not auth:
                logger.warning("Radiko 認証失敗、次へ")
                continue
            logger.info("area=%s (%s) に接続", auth.area_id, auth.area_name)

            if auth.area_id in attempted_areas:
                logger.info("既に試したエリア、次へ (area=%s)", auth.area_id)
                continue
            attempted_areas.add(auth.area_id)

            # このエリアで取れる番組を全部 DL
            pending = _run_one_pass(
                pending, auth, config, keywords, counters, counters_lock,
            )
        finally:
            vpn_manager.disconnect()

    # 最終レポート
    if pending:
        logger.warning("取得できなかった番組 (%d 件):", len(pending))
        for p in pending:
            station = p.service
            if p.service.startswith("radiko:"):
                station = p.service.split(":", 1)[1]
            logger.warning(
                "  [%s] %s %s %s (覆われなかった area)",
                p.service, p.start_time.strftime("%Y-%m-%d %H:%M"),
                station, p.title[:50],
            )

    logger.info(
        "=== 完了: 成功 %d / 失敗 %d / 未放送スキップ %d / 未カバー %d ===",
        counters["success"], counters["failed"], counters["skipped"], len(pending),
    )

    # 全滅なら非ゼロで終了
    if (
        counters["success"] == 0
        and counters["failed"] > 0
        and counters["skipped"] == 0
    ):
        sys.exit(3)


if __name__ == "__main__":
    main()
