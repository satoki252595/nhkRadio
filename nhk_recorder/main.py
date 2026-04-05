import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .api import Program, fetch_programs
from .config import Config, load_config
from .matcher import filter_by_series, filter_programs
from .notion import upload_recording
from .recorder import make_output_path, record
from .scheduler import schedule_recordings
from .streams import get_stream_urls

JST = timezone(timedelta(hours=9))


def _load_subscriptions(path: str) -> list[str]:
    """購読シリーズIDリストをJSONから読み込む。

    想定形式: {"series_ids": ["ABC123", "XYZ456"]} または ["ABC123", "XYZ456"]
    """
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("series_ids", [])


def _record_immediately(
    programs: list[Program],
    stream_urls: dict[str, str],
    config: Config,
    matched_keywords: list[str] | None = None,
) -> None:
    """番組を順番に即時録音する（GitHub Actions向け、Timer不使用）。"""
    logger = logging.getLogger(__name__)
    now = datetime.now(JST)
    keywords = matched_keywords or config.keywords

    for program in programs:
        stream_url = stream_urls.get(program.service)
        if not stream_url:
            logger.warning("ストリームURLが不明: %s", program.service)
            continue

        # 残り録音時間を計算
        elapsed = (now - program.start_time).total_seconds()
        if elapsed > program.duration:
            logger.info("既に終了済み: [%s] %s", program.service, program.title)
            continue

        duration = program.duration - max(int(elapsed), 0)
        output_path = make_output_path(config.output_dir, program)

        logger.info("録音開始: [%s] %s (%d分)", program.service, program.title, duration // 60)
        success = record(stream_url, duration, output_path, config.ffmpeg_path)

        if success and config.notion_token and config.notion_database_id:
            search_text = f"{program.title} {program.subtitle} {program.content}"
            matched_kw = [kw for kw in keywords if kw in search_text]
            try:
                upload_recording(config, program, output_path, matched_kw)
            except Exception as e:
                logger.error("Notionアップロード失敗: %s - %s", program.title, e)

        # 時刻を更新（次の番組の判定用）
        now = datetime.now(JST)


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
        "--subscriptions", metavar="PATH",
        help="購読シリーズIDリストのJSONパス (キーワード方式の代わりに購読ベースで録音)",
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
        series_ids = _load_subscriptions(args.subscriptions)
        logger.info("購読モード: %d シリーズ", len(series_ids))
        logger.info("対象日: %s / エリア: %s", target_date, config.area)
    else:
        matched_keywords = config.keywords
        logger.info("キーワードモード: %s", matched_keywords)
        logger.info("対象日: %s / エリア: %s / キーワード: %s", target_date, config.area, config.keywords)

    # 番組表取得
    logger.info("番組表を取得中...")
    programs = fetch_programs(config, target_date)
    if not programs:
        logger.info("番組が取得できませんでした")
        return

    logger.info("合計 %d 件の番組を取得", len(programs))

    # フィルタリング
    if args.subscriptions:
        matched = filter_by_series(programs, series_ids)
    else:
        matched = filter_programs(programs, config.keywords)

    if not matched:
        logger.info("マッチする番組がありません")
        return

    # --within: 指定分以内に開始する番組のみに絞り込み
    if args.within is not None:
        now = datetime.now(JST)
        window_end = now + timedelta(minutes=args.within)
        matched = [
            p for p in matched
            if p.start_time <= window_end and p.end_time > now
        ]
        if not matched:
            logger.info("直近%d分以内に対象番組なし", args.within)
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
        _record_immediately(matched, stream_urls, config, matched_keywords)
    else:
        # ローカル向け: Timer待機モード
        schedule_recordings(matched, stream_urls, config, matched_keywords=matched_keywords)


if __name__ == "__main__":
    main()
