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
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .api import fetch_programs
from .config import load_config
from . import radiko

JST = timezone(timedelta(hours=9))

# NHKのradiko同時配信局 (NHKと重複するため優先度を下げる)
NHK_SIMULCAST_STATIONS = {"JOBK", "JOAK", "JOBK-FM", "JOAK-FM"}


def _normalize_title(title: str) -> str:
    """番組タイトルを正規化する (局名プレフィックスや全角空白の違いを吸収)。"""
    # 先頭の [局名] を除去
    t = re.sub(r"^\[[^\]]+\]\s*", "", title)
    # 全角スペース・連続空白を単一半角スペースへ
    t = re.sub(r"[\s　]+", " ", t).strip()
    return t


def _service_priority(service: str) -> int:
    """サービスの優先度を返す (大きいほど優先)。

    NHKの本家配信(r1/r3)を最優先、NHKのradiko同時配信(JOBK等)を削除対象にする。
    民放独自局は残す。
    """
    if service in ("r1", "r3"):
        return 100  # NHK本家 = 高音質 = 最優先
    if service.startswith("radiko:"):
        station = service.split(":", 1)[1]
        if station in NHK_SIMULCAST_STATIONS:
            return 10  # NHKのradiko配信 = 低音質 = NHK本家があれば削除
        return 50  # 民放独自
    return 0


def _dedupe_series_index(index: dict[str, dict]) -> dict[str, dict]:
    """シリーズindexから重複を排除する。

    同じ series_name が NHK(r1/r3) と radiko:JOBK 等の同時配信局に
    存在する場合、音質の良いNHK側を残す。民放独自シリーズはそのまま。
    """
    # 正規化名 → [(series_id, entry), ...] でグルーピング
    by_name: dict[str, list[tuple[str, dict]]] = {}
    for sid, entry in index.items():
        key = _normalize_title(entry.get("series_name", ""))
        by_name.setdefault(key, []).append((sid, entry))

    removed = 0
    for name, items in by_name.items():
        if len(items) < 2:
            continue
        # 優先度順にソート
        items.sort(key=lambda x: _service_priority(x[1].get("service", "")), reverse=True)
        # 先頭(最優先)以外を削除候補に
        top_priority = _service_priority(items[0][1].get("service", ""))
        for sid, entry in items[1:]:
            svc = entry.get("service", "")
            # 同じ優先度なら残す (R1とR3は両方残す、民放同士も両方残す)
            if _service_priority(svc) == top_priority:
                continue
            # NHK本家がある時に radiko:JOBK 等の同時配信を削除
            if svc.startswith("radiko:"):
                station = svc.split(":", 1)[1]
                if station in NHK_SIMULCAST_STATIONS:
                    index.pop(sid, None)
                    removed += 1

    if removed > 0:
        logger = logging.getLogger(__name__)
        logger.info("シリーズ重複排除: %d件削除 (NHK同時配信)", removed)
    return index


def dedupe_programs(programs: list) -> list:
    """同時刻・同タイトルの番組を重複排除する (優先度の高い方を残す)。

    Args:
        programs: Program オブジェクトのリスト

    Returns:
        重複排除後のリスト
    """
    # (start_time, normalized_title) をキーにグルーピング
    by_key: dict = {}
    for p in programs:
        key = (p.start_time.isoformat(), _normalize_title(p.title))
        existing = by_key.get(key)
        if existing is None or _service_priority(p.service) > _service_priority(existing.service):
            by_key[key] = p

    result = list(by_key.values())
    result.sort(key=lambda p: p.start_time)
    return result


def _strip_time_segment_marker(title: str) -> str:
    """タイトルから時間帯分割マーカーを除去する。

    Radikoでは長時間番組を時間帯で分割することがあり、以下のマーカーが付く:
    - (1) (2) (3) 等の数字サフィックス
    - ①②③ 等の丸数字
    - 【前半】【後半】【第1部】等
    - ＜前半＞＜後半＞
    - ・前半/・後半
    """
    t = title
    # 末尾の (1)(2)(3) や ①②③
    t = re.sub(r"\s*[(（][1-9][)）]\s*$", "", t)
    t = re.sub(r"\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*$", "", t)
    # 【前半】【後半】【第N部】等
    t = re.sub(r"\s*[【\[＜<](前半|後半|前編|後編|第[1-9]部)[】\]＞>]\s*$", "", t)
    # 末尾の "・前半" "・後半"
    t = re.sub(r"\s*[・･](前半|後半|前編|後編)\s*$", "", t)
    return t.strip()


def _radiko_to_program(rp):
    """RadikoProgram を NHK Program 互換オブジェクトに変換。

    service は radiko:{station_id} 形式 (例: radiko:ABC)。
    series_id は station_id + 正規化タイトルのハッシュ (時間帯分割を同一シリーズに)。
    """
    import hashlib
    from .api import Program

    # 時間帯マーカーを除去してからハッシュ (同番組を同一シリーズに統合)
    normalized_title = _strip_time_segment_marker(rp.title)
    series_key = f"{rp.station_id}|{normalized_title}"
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
        series_name=normalized_title,  # (1)(2)(3) を含まない名前
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
    parser.add_argument(
        "--rebuild-series", action="store_true",
        help="既存series.jsonを破棄して作り直す",
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
    if args.rebuild_series:
        series_index: dict[str, dict] = {}
        logger.info("series.json を再構築します (既存データを破棄)")
    else:
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
    total_deduped = 0
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

        # 重複排除 (NHK本家 vs radiko:JOBK等の同時配信)
        before_dedupe = len(programs)
        programs = dedupe_programs(programs)
        deduped_count = before_dedupe - len(programs)
        total_deduped += deduped_count
        if deduped_count > 0:
            logger.info("重複排除: %d件 → %d件 (%d件削除)", before_dedupe, len(programs), deduped_count)

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

    # シリーズレベルの重複排除: 同名シリーズがNHKとradiko:JOBK両方にある場合、radiko側を削除
    series_index = _dedupe_series_index(series_index)

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
