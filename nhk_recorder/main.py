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
    stream_urls: dict[str, str],
    config: Config,
    keywords: list[str],
    radiko_auth,
) -> None:
    """1番組を録音してNotionにアップロードする (ワーカースレッド用)。"""
    logger = logging.getLogger(__name__)
    is_radiko = program.service.startswith("radiko:")

    # ストリーム情報を決定
    if is_radiko:
        if not radiko_auth:
            logger.warning("Radiko番組だが未認証: %s", program.title)
            return
        station_id = program.service.split(":", 1)[1]
    else:
        stream_url = stream_urls.get(program.service)
        if not stream_url:
            logger.warning("ストリームURLが不明: %s", program.service)
            return

    # 番組開始まで待機 (まだ始まっていない場合)
    now = datetime.now(JST)
    wait_sec = (program.start_time - now).total_seconds()
    if wait_sec > 0:
        logger.info("番組開始まで%d秒待機: [%s] %s", int(wait_sec), program.service, program.title)
        time.sleep(wait_sec)

    # 残り録音時間を計算
    now = datetime.now(JST)
    elapsed = (now - program.start_time).total_seconds()
    if elapsed > program.duration:
        logger.info("既に終了済み: [%s] %s", program.service, program.title)
        return

    duration = program.duration - max(int(elapsed), 0)
    output_path = make_output_path(config.output_dir, program)

    logger.info("録音開始: [%s] %s (%d分)", program.service, program.title, duration // 60)
    if is_radiko:
        success = radiko_mod.record_program(
            radiko_auth, station_id, duration, output_path, config.ffmpeg_path
        )
    else:
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
    stream_urls: dict[str, str],
    config: Config,
    matched_keywords: list[str] | None = None,
    radiko_auth=None,
) -> None:
    """番組を並列で即時録音する (GitHub Actions向け、Timer不使用)。

    同時刻に複数番組がある場合は並列録音する。録音+アップロードは
    各スレッドが独立して行うので、1つの失敗が他に波及しない。

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
            args=(program, stream_urls, config, keywords, radiko_auth),
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

    # 対象日
    target_date = args.date or datetime.now(JST).strftime("%Y-%m-%d")

    # 購読モード判定
    series_ids: list[str] = []
    matched_keywords: list[str] = []
    if args.subscriptions:
        series_ids, sub_keywords = _load_subscriptions(args.subscriptions)
        # subscriptions.json 由来のキーワードを優先、無ければ config のキーワード
        matched_keywords = sub_keywords if sub_keywords else config.keywords
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

    # --skip-nhk: NHK(r1/r3)番組を除外 (Radiko専用ジョブ向け)
    if args.skip_nhk:
        before = len(matched)
        matched = [p for p in matched if not p.service.startswith(("r1", "r3"))]
        logger.info("--skip-nhk: NHK番組を%d件スキップ", before - len(matched))

    # --within: 指定分以内に開始する番組のみに絞り込み
    # start_time ベースでフィルタし、前のcron実行で録音済みの番組を除外する
    # (end_time > now だと放送中の番組が次のcronでも再マッチしてしまう)
    if args.within is not None:
        now = datetime.now(JST)
        window_start = now - timedelta(minutes=5)   # 起動遅延を考慮した猶予
        window_end = now + timedelta(minutes=args.within)
        matched = [
            p for p in matched
            if window_start <= p.start_time <= window_end
        ]
        if not matched:
            logger.info("直近%d分以内に対象番組なし", args.within)
            return

    # 重複排除: 同時刻・同タイトルの番組を統合 (NHK本家 vs radiko同時配信等)
    from .data_export import dedupe_programs
    before_dedupe = len(matched)
    matched = dedupe_programs(matched)
    if before_dedupe != len(matched):
        logger.info("録音対象の重複排除: %d件 → %d件", before_dedupe, len(matched))

    # マッチ結果表示
    logger.info("--- マッチした番組 (%d件) ---", len(matched))
    for p in matched:
        start = p.start_time.strftime("%H:%M")
        end = p.end_time.strftime("%H:%M")
        logger.info("  [%s] %s-%s %s (%d分)", p.service, start, end, p.title, p.duration // 60)

    if args.dry_run:
        logger.info("ドライラン完了")
        return

    # ストリームURL取得
    stream_urls = get_stream_urls(config.area)
    logger.info("ストリームURL: %s", {k: v[:60] + "..." for k, v in stream_urls.items()})

    # Notion連携状態表示
    if config.notion_token and config.notion_database_id:
        logger.info("Notion連携: 有効 (録音後に自動アップロード)")
    else:
        logger.info("Notion連携: 無効 (ローカル保存のみ)")

    # 録音実行
    if args.within is not None:
        # GitHub Actions向け: 即時録音モード（Timer不使用）
        _record_immediately(matched, stream_urls, config, matched_keywords, radiko_auth)
    else:
        # ローカル向け: Timer待機モード
        schedule_recordings(matched, stream_urls, config, matched_keywords=matched_keywords)


if __name__ == "__main__":
    main()
