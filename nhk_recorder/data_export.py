"""番組データをJSON形式でエクスポートする (フロントエンド向け)。

毎日4時に実行して、以下のファイルを生成する:
- data/programs-YYYY-MM-DD.json : その日の全番組
- data/programs-latest.json     : 今日の番組のエイリアス
- data/series.json              : ユニークなシリーズ一覧 (蓄積型)

シリーズ情報は既存のseries.jsonに追記・更新され、過去に一度でも登場した
シリーズが蓄積されていく。デフォルトでは過去7日+未来7日=2週間分を取得
して、週次番組や平日番組を漏れなくカバーする。
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .api import fetch_programs
from .config import load_config
from . import radiko

JST = timezone(timedelta(hours=9))


def _radiko_to_program(rp):
    """RadikoProgram を NHK Program 互換オブジェクトに変換。

    service は radiko:{station_id} 形式 (例: radiko:ABC)。
    series_id は station_id + title のハッシュ (安定ID)。
    """
    import hashlib
    from .api import Program

    # 安定したシリーズID生成 (station + title)
    series_key = f"{rp.station_id}|{rp.title}"
    series_id = "rdk_" + hashlib.md5(series_key.encode("utf-8")).hexdigest()[:12]

    return Program(
        id=rp.id,
        service=f"radiko:{rp.station_id}",
        title=f"[{rp.station_name}] {rp.title}",
        subtitle=rp.performer,
        content=rp.content,
        start_time=rp.start_time,
        end_time=rp.end_time,
        series_id=series_id,
        series_name=rp.title,
        episode_name="",
        genre=[],
    )


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


def prune_old_programs(output_dir: Path, keep_days: int = 14) -> None:
    """古い programs-YYYY-MM-DD.json を削除 (容量節約)。"""
    today = datetime.now(JST).date()
    cutoff = today - timedelta(days=keep_days)
    for path in output_dir.glob("programs-*.json"):
        if path.name == "programs-latest.json":
            continue
        try:
            date_str = path.stem.replace("programs-", "")
            file_date = datetime.fromisoformat(date_str).date()
            if file_date < cutoff:
                path.unlink()
        except (ValueError, OSError):
            continue


def main():
    parser = argparse.ArgumentParser(description="NHK番組データをJSON出力")
    parser.add_argument("--date", help="開始日 (YYYY-MM-DD、デフォルト: 今日)")
    parser.add_argument("--output-dir", default="./data", help="出力ディレクトリ")
    parser.add_argument(
        "--days", type=int, default=7,
        help="何日分取得するか (デフォルト: 7 = 1週間先まで)",
    )
    parser.add_argument(
        "--past-days", type=int, default=7,
        help="過去何日分も取得してシリーズ情報を蓄積するか (デフォルト: 7)",
    )
    parser.add_argument(
        "--prune-days", type=int, default=14,
        help="何日より古い番組JSONを削除するか (デフォルト: 14)",
    )
    parser.add_argument(
        "--include-radiko", action="store_true",
        help="Radiko (民放) の番組も取得する (日本IPが必要)",
    )
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

    # Radiko認証 (オプション)
    radiko_auth = None
    if args.include_radiko:
        logger.info("Radiko認証を実行中...")
        radiko_auth = radiko.authenticate()
        if radiko_auth:
            logger.info("Radiko認証成功: %s (%s)", radiko_auth.area_id, radiko_auth.area_name)
        else:
            logger.warning("Radiko認証失敗 (日本IPではない可能性)。Radiko番組はスキップ")

    # 対象日の計算 (過去→未来の順)
    base_date = (
        datetime.fromisoformat(args.date).replace(tzinfo=JST)
        if args.date
        else datetime.now(JST)
    )
    start_offset = -args.past_days
    end_offset = args.days

    total_programs = 0
    for i in range(start_offset, end_offset):
        target = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        logger.info("番組表取得: %s", target)
        programs = fetch_programs(config, target)
        total_programs += len(programs)

        # Radiko番組も追加取得
        if radiko_auth:
            rp = radiko.fetch_programs(radiko_auth.area_id, target)
            # RadikoProgram -> Program 互換dict変換
            for p in rp:
                programs.append(_radiko_to_program(p))
            total_programs += len(rp)

        # 番組リストをJSON保存 (未来分のみ、過去分はシリーズ蓄積のみ)
        if i >= 0:
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
                entry = series_index[p.series_id]
                # より古い日付なら first_seen を更新
                if target < entry.get("first_seen", target):
                    entry["first_seen"] = target
                # より新しい日付なら last_seen を更新
                if target > entry.get("last_seen", ""):
                    entry["last_seen"] = target
                # サンプル情報を最新のもので上書き (番組内容の新鮮度確保)
                entry["sample_title"] = p.title
                if p.content:
                    entry["sample_description"] = p.content[:200]
                # ジャンルは最新値で更新
                if p.genre:
                    entry["genre"] = p.genre

    save_series_index(series_file, series_index)
    logger.info(
        "シリーズ一覧更新: %s (合計 %d 件 / 取得 %d 番組)",
        series_file, len(series_index), total_programs,
    )

    # 最新番組表のエイリアスを作成 (latest.json = 今日)
    today_str = base_date.strftime("%Y-%m-%d")
    today_file = output_dir / f"programs-{today_str}.json"
    latest_file = output_dir / "programs-latest.json"
    if today_file.exists():
        with open(today_file, encoding="utf-8") as f:
            latest_data = json.load(f)
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump(latest_data, f, ensure_ascii=False, indent=2)
        logger.info("最新エイリアス: %s", latest_file)

    # 古いファイルを削除
    prune_old_programs(output_dir, args.prune_days)


if __name__ == "__main__":
    main()
