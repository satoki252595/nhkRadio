"""番組データをJSON形式でエクスポートする (フロントエンド向け)。

毎日4時に実行して、以下のファイルを生成する:
- data/programs-YYYY-MM-DD.json : その日の全番組
- data/series.json : ユニークなシリーズ一覧 (蓄積型)
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .api import fetch_programs
from .config import load_config

JST = timezone(timedelta(hours=9))


def program_to_dict(p) -> dict:
    return {
        "id": p.id,
        "service": p.service,
        "title": p.title,
        "subtitle": p.subtitle,
        "content": p.content,
        "start_time": p.start_time.isoformat(),
        "end_time": p.end_time.isoformat(),
        "duration_sec": p.duration,
        "series_id": p.series_id,
        "series_name": p.series_name,
        "episode_name": p.episode_name,
        "genre": p.genre,
    }


def load_series_index(path: Path) -> dict[str, dict]:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return {s["series_id"]: s for s in json.load(f).get("series", [])}
    return {}


def save_series_index(path: Path, index: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    series_list = sorted(index.values(), key=lambda s: (s["service"], s["series_name"]))
    data = {
        "updated_at": datetime.now(JST).isoformat(),
        "series": series_list,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="NHK番組データをJSON出力")
    parser.add_argument("--date", help="対象日 (YYYY-MM-DD、デフォルト: 今日)")
    parser.add_argument("--output-dir", default="./data", help="出力ディレクトリ")
    parser.add_argument("--days", type=int, default=1, help="何日分取得するか (今日から)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger(__name__)

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    series_file = output_dir / "series.json"
    series_index = load_series_index(series_file)
    logger.info("既存シリーズ数: %d", len(series_index))

    # 対象日の計算
    base_date = (
        datetime.fromisoformat(args.date).replace(tzinfo=JST)
        if args.date
        else datetime.now(JST)
    )

    all_programs: list = []
    for i in range(args.days):
        target = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        logger.info("番組表取得: %s", target)
        programs = fetch_programs(config, target)

        # 番組リストをJSON保存
        programs_file = output_dir / f"programs-{target}.json"
        with open(programs_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": target,
                    "area": config.area,
                    "updated_at": datetime.now(JST).isoformat(),
                    "programs": [program_to_dict(p) for p in programs],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info("書き出し: %s (%d件)", programs_file, len(programs))

        # シリーズ情報を蓄積
        for p in programs:
            if not p.series_id:
                continue
            if p.series_id not in series_index:
                series_index[p.series_id] = {
                    "series_id": p.series_id,
                    "series_name": p.series_name,
                    "service": p.service,
                    "genre": p.genre,
                    "sample_title": p.title,
                    "sample_description": p.content[:200],
                    "first_seen": target,
                    "last_seen": target,
                }
            else:
                series_index[p.series_id]["last_seen"] = target

        all_programs.extend(programs)

    save_series_index(series_file, series_index)
    logger.info("シリーズ一覧更新: %s (合計 %d 件)", series_file, len(series_index))

    # 最新番組表のエイリアスを作成 (latest.json)
    if args.days >= 1:
        today_str = base_date.strftime("%Y-%m-%d")
        today_file = output_dir / f"programs-{today_str}.json"
        latest_file = output_dir / "programs-latest.json"
        if today_file.exists():
            with open(today_file, encoding="utf-8") as f:
                latest_data = json.load(f)
            with open(latest_file, "w", encoding="utf-8") as f:
                json.dump(latest_data, f, ensure_ascii=False, indent=2)
            logger.info("最新エイリアス: %s", latest_file)


if __name__ == "__main__":
    main()
