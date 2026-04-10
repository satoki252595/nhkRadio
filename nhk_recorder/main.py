import argparse
import json
import logging
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .api import Program, fetch_programs
from .config import Config, load_config
from .matcher import filter_by_series, filter_programs
from .notion import upload_recording
from .recorder import make_output_path, record
from .scheduler import schedule_recordings
from .streams import get_stream_urls
from . import radiko as radiko_mod

JST = timezone(timedelta(hours=9))

# 録音マージン: 番組の前後を含めて録音する
# - PRE_ROLL: ffmpegのHLS接続オーバーヘッドと冒頭の取りこぼし対策
# - POST_ROLL: 番組のオーバーラン対策 (定刻より少し延びる場合がある)
PRE_ROLL_SEC = 10
POST_ROLL_SEC = 20

# NHK / Radiko の "放送日" (broadcast day) は JST 5:00 から翌日 4:55 まで。
# 例: JST 4/9 03:00 の番組は 4/8 broadcast day に属し、programs-2026-04-08.json にある。
BROADCAST_DAY_HOUR = 5


def _broadcast_date(dt: datetime) -> str:
    """壁時計の datetime から broadcast day (YYYY-MM-DD) を返す。

    JST 5:00 未満の場合は前日の broadcast day、5:00 以降は当日。
    """
    return (dt - timedelta(hours=BROADCAST_DAY_HOUR)).strftime("%Y-%m-%d")


def _load_subscriptions(source: str) -> tuple[list[str], list[str]]:
    """購読シリーズIDリストとキーワードをJSONから読み込む。

    source はローカルファイルパス または http(s) URL を受け付ける。
    想定形式:
      {"series_ids": [...], "keywords": [...], "updated_at": "..."}
      または ["ABC123", ...] (旧形式、series_idsのみ)

    Returns:
        (series_ids, keywords)
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


def _record_one(
    program: Program,
    config: Config,
    keywords: list[str],
    area: str,
) -> None:
    """1番組を録音してNotionにアップロードする (ワーカースレッド用)。

    ストリームURL/Radiko認証は **録音直前** に取得することで、長時間待機後も
    確実に新鮮な接続情報を使う (50分以上待機すると古いトークンや古いキャッシュは
    無効化されることがあるため)。
    """
    logger = logging.getLogger(__name__)
    is_radiko = program.service.startswith("radiko:")

    # 録音ウィンドウ: [start - PRE_ROLL, end + POST_ROLL]
    # ffmpegのHLS接続には数秒かかるため、番組開始の少し前から録音を開始する。
    target_start = program.start_time - timedelta(seconds=PRE_ROLL_SEC)
    target_end = program.end_time + timedelta(seconds=POST_ROLL_SEC)

    now = datetime.now(JST)
    if now >= target_end:
        logger.info("既に終了済み: [%s] %s", program.service, program.title)
        return

    # ターゲット開始時刻まで待機 (既に過ぎていれば即時開始)
    wait_sec = (target_start - now).total_seconds()
    if wait_sec > 0:
        logger.info(
            "録音開始まで%d秒待機 (pre-roll %ds込み): [%s] %s",
            int(wait_sec), PRE_ROLL_SEC, program.service, program.title,
        )
        time.sleep(wait_sec)

    # 録音時間 = 現時点から target_end までの残り時間
    now = datetime.now(JST)
    duration = int((target_end - now).total_seconds())
    if duration <= 0:
        logger.info("録音時間が0以下: [%s] %s", program.service, program.title)
        return
    output_path = make_output_path(config.output_dir, program)

    # ストリーム情報を録音直前に取得 (待機中に古くなっている可能性があるため)
    if is_radiko:
        station_id = program.service.split(":", 1)[1]
        radiko_auth = radiko_mod.authenticate()
        if not radiko_auth:
            logger.error("Radiko再認証失敗、録音中止: %s", program.title)
            return
        logger.info("録音開始: [%s] %s (%d分)", program.service, program.title, duration // 60)
        success = radiko_mod.record_program(
            radiko_auth, station_id, duration, output_path, config.ffmpeg_path
        )
    else:
        # NHK ストリームURLは毎回取得 (master.m3u8 は通常は安定だが念のため)
        stream_urls = get_stream_urls(area)
        stream_url = stream_urls.get(program.service)
        if not stream_url:
            logger.warning("ストリームURLが不明: %s", program.service)
            return
        logger.info("録音開始: [%s] %s (%d分)", program.service, program.title, duration // 60)
        success = record(stream_url, duration, output_path, config.ffmpeg_path)

    if success and config.notion_token and config.notion_database_id:
        search_text = f"{program.title} {program.subtitle} {program.content}"
        matched_kw = [kw for kw in keywords if kw in search_text]
        try:
            upload_recording(config, program, output_path, matched_kw)
        except Exception as e:
            logger.error("Notionアップロード失敗: %s - %s", program.title, e)


def _record_immediately(
    programs: list[Program],
    config: Config,
    area: str,
    matched_keywords: list[str] | None = None,
) -> None:
    """番組を並列で即時録音する (GitHub Actions向け、Timer不使用)。

    同時刻に複数番組がある場合は並列録音する。録音+アップロードは
    各スレッドが独立して行うので、1つの失敗が他に波及しない。

    各スレッドはストリームURL/Radiko認証を録音直前に取得し直すため、
    長時間待機後でも新鮮な接続情報を使う。

    NHKとRadiko番組を同じリストで処理可能。
    service プレフィックス "radiko:" で判別。
    """
    logger = logging.getLogger(__name__)
    keywords = matched_keywords or config.keywords

    if not programs:
        return

    logger.info("並列録音: %d番組", len(programs))

    threads: list[threading.Thread] = []
    for program in programs:
        t = threading.Thread(
            target=_record_one,
            args=(program, config, keywords, area),
            name=f"rec-{program.service}-{program.id[:8]}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    # 全スレッド完了を待つ
    for t in threads:
        t.join()

    logger.info("全録音完了")


def main():
    parser = argparse.ArgumentParser(description="NHKラジオ録音ツール")
    parser.add_argument("--config", help="設定ファイルのパス")
    parser.add_argument("--date", help="対象日 (YYYY-MM-DD形式、デフォルト: 今日)")
    parser.add_argument("--dry-run", action="store_true", help="録音せず対象番組を表示")
    parser.add_argument(
        "--within", type=int, metavar="MINUTES",
        help="現在からN分以内に開始する番組のみ対象にして即時録音 (GitHub Actions向け)",
    )
    parser.add_argument(
        "--subscriptions", metavar="PATH_OR_URL",
        help="購読シリーズIDリストのJSON (ファイルパス または http(s) URL)",
    )
    parser.add_argument(
        "--include-radiko", action="store_true",
        help="Radiko (民放) も対象にする (日本IPが必要)",
    )
    parser.add_argument(
        "--skip-nhk", action="store_true",
        help="NHK番組をスキップ (Radiko録音ジョブ専用)",
    )
    parser.add_argument(
        "--expected-area", metavar="PREFIX",
        help="Radiko認証エリアの期待値プレフィックス (例: JP27,JP28=関西)。"
             "一致しない場合はRadiko録音を無効化する",
    )
    args = parser.parse_args()

    # 設定読み込み
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    # ログ設定
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    # 対象日 (broadcast day = JST 5:00-4:55 翌日)
    # --date 明示指定がある場合はそれを優先。
    # それ以外で --within 指定時は target_hour ベースで broadcast day を決める
    # (この時点では target_hour 未確定なので一旦 now ベース、後で再計算する)。
    target_date = args.date or _broadcast_date(datetime.now(JST))

    # 購読モード判定
    series_ids: list[str] = []
    matched_keywords: list[str] = []
    if args.subscriptions:
        series_ids, sub_keywords = _load_subscriptions(args.subscriptions)
        # subscriptions.json のキーワードをそのまま使う (空配列なら空のまま)
        # 以前は空時に config.keywords にフォールバックしていたが、Web UI でユーザーが
        # 意図的に空にしたキーワードがバックエンド側で勝手に補完されて意図しない番組が
        # 録音される問題があったため、subscriptions.json を絶対の正として扱う。
        matched_keywords = sub_keywords
        logger.info("購読モード: %d シリーズ + %d キーワード", len(series_ids), len(matched_keywords))
        logger.info("対象日: %s / エリア: %s", target_date, config.area)
    else:
        matched_keywords = config.keywords
        logger.info("キーワードモード: %s", matched_keywords)
        logger.info("対象日: %s / エリア: %s / キーワード: %s", target_date, config.area, config.keywords)

    # Radiko認証 (オプション)
    radiko_auth = None
    if args.include_radiko:
        logger.info("Radiko認証を実行中...")
        radiko_auth = radiko_mod.authenticate()
        if radiko_auth:
            logger.info("Radiko認証成功: %s (%s)", radiko_auth.area_id, radiko_auth.area_name)
            # エリアミスマッチ検知
            if args.expected_area:
                allowed = {a.strip() for a in args.expected_area.split(",") if a.strip()}
                if not any(radiko_auth.area_id.startswith(a) for a in allowed):
                    logger.error(
                        "VPNエリアミスマッチ: 期待=%s / 実際=%s → Radikoをスキップ",
                        args.expected_area, radiko_auth.area_id,
                    )
                    radiko_auth = None
        else:
            logger.warning("Radiko認証失敗 (日本IPでない可能性)。NHKのみ対象")

    # --within: 録音対象時間帯 (target_hour) を先に確定する。
    # GitHub Actions cron は 13-46 分遅延するため、cron を 1 時間前に発火させ、
    # スクリプト側で「次のHH:00境界の1時間幅」を狙う。
    # target_hour に基づいて broadcast day を計算するので、ここで先に決める。
    target_hour: datetime | None = None
    window_end: datetime | None = None
    if args.within is not None:
        now = datetime.now(JST)
        # cron `0 * * * *` は毎時 HH:00 発火を意図しているが、GitHub Actions では
        # 13-46 分の遅延が常態化している。各 cron 起動は「次の HH:00 から始まる
        # 1 時間幅」を録音対象として担当する設計。
        # 例: cron HH:00 → 起動 HH:13-46 → 待機 → target HH+1:00 - HH+2:00 を録音。
        # 起動が HH:55 以降ならどちらの target を選ぶかが曖昧になり次の run と重複
        # するが、Notion 側の重複チェックに任せる。
        target_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        window_end = target_hour + timedelta(hours=1)
        # target_hour に基づいて broadcast day を計算 (深夜0-5時を正しく扱う)
        if not args.date:
            target_date = _broadcast_date(target_hour)

    logger.info("対象日 (broadcast day): %s", target_date)

    # 番組表取得
    logger.info("番組表を取得中...")
    programs = fetch_programs(config, target_date)

    # Radiko番組も追加
    if radiko_auth:
        rp = radiko_mod.fetch_programs(radiko_auth.area_id, target_date)
        from .data_export import _radiko_to_program
        for p in rp:
            programs.append(_radiko_to_program(p))

    if not programs:
        logger.info("番組が取得できませんでした")
        return

    logger.info("合計 %d 件の番組を取得 (NHK + Radiko)", len(programs))

    # フィルタリング (シリーズ購読 + キーワードを OR で結合)
    # 注意: dedupe (NHK simulcast 排除) は filter の "後" にやる。先に dedupe すると
    # 「JOAK-FM 側 (rdk_) のシリーズだけ購読」のユーザーで、NHK 本家 r3 が残されたあと
    # filter_by_series がマッチせず、結局録音されないバグになる。
    if args.subscriptions:
        by_series = filter_by_series(programs, series_ids) if series_ids else []
        by_keyword = filter_programs(programs, matched_keywords) if matched_keywords else []
        # ID重複排除してマージ
        seen: set[str] = set()
        matched: list[Program] = []
        for p in by_series + by_keyword:
            if p.id not in seen:
                seen.add(p.id)
                matched.append(p)
        matched.sort(key=lambda p: p.start_time)
    else:
        matched = filter_programs(programs, config.keywords)

    if not matched:
        logger.info("マッチする番組がありません")
        return

    # NHK/Radiko サイマル重複排除 (NHK本家を優先)
    # filter の後に行うことで、JOAK-FM 側だけ購読していてもマッチしてから本家に統合される。
    from .data_export import dedupe_programs
    before_dedup = len(matched)
    matched = dedupe_programs(matched)
    if len(matched) < before_dedup:
        logger.info("サイマル重複排除: %d → %d 件", before_dedup, len(matched))

    # --skip-nhk: NHK番組を除外 (Radiko専用ジョブ向け)
    # r1/r3 (NHK本家) に加え、radiko上のNHK同時配信局 (JOAK/JOBK等) も除外。
    # 関西ジョブがNHK本家で録音するため、関東ジョブではNHK系を全てスキップ。
    if args.skip_nhk:
        from .data_export import NHK_SIMULCAST_STATIONS
        before = len(matched)
        def _is_nhk(p: Program) -> bool:
            if p.service.startswith(("r1", "r3")):
                return True
            if p.service.startswith("radiko:"):
                station = p.service.split(":", 1)[1]
                return station in NHK_SIMULCAST_STATIONS
            return False
        matched = [p for p in matched if not _is_nhk(p)]
        logger.info("--skip-nhk: NHK番組を%d件スキップ (同時配信含む)", before - len(matched))

    # --within: target_hour 時間帯の番組のみに絞り込み
    if args.within is not None and target_hour is not None:
        now = datetime.now(JST)
        matched = [
            p for p in matched
            if target_hour <= p.start_time < window_end
        ]
        wait_min = max(0, int((target_hour - now).total_seconds() / 60))
        logger.info(
            "対象時間帯: [%s, %s) (起動から約%d分待機)",
            target_hour.strftime("%m/%d %H:%M"), window_end.strftime("%m/%d %H:%M"), wait_min,
        )
        if not matched:
            logger.info("当該時間帯に対象番組なし")
            return

    # マッチ結果表示
    logger.info("--- マッチした番組 (%d件) ---", len(matched))
    for p in matched:
        start = p.start_time.strftime("%H:%M")
        end = p.end_time.strftime("%H:%M")
        logger.info("  [%s] %s-%s %s (%d分)", p.service, start, end, p.title, p.duration // 60)

    if args.dry_run:
        logger.info("ドライラン完了")
        return

    # Notion連携状態表示
    if config.notion_token and config.notion_database_id:
        logger.info("Notion連携: 有効 (録音後に自動アップロード)")
    else:
        logger.info("Notion連携: 無効 (ローカル保存のみ)")

    # 録音実行
    if args.within is not None:
        # GitHub Actions向け: 即時録音モード（Timer不使用）
        # ストリームURLは各録音スレッドが直前に取得し直す。
        _record_immediately(matched, config, config.area, matched_keywords)
    else:
        # ローカル向け: Timer待機モード
        # こちらは事前取得が必要 (Timer 発火時に毎回再取得するのは本旨と外れる)。
        stream_urls = get_stream_urls(config.area)
        logger.info("ストリームURL: %s", {k: v[:60] + "..." for k, v in stream_urls.items()})
        schedule_recordings(matched, stream_urls, config, matched_keywords=matched_keywords)


if __name__ == "__main__":
    main()
