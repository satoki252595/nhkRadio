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
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import radiko as radiko_mod
from . import radiru as radiru_mod
from . import vpn_manager
from .api import Program, fetch_programs
from .config import Config, load_config
from .matcher import filter_by_series, filter_programs
from .notion import _find_duplicates, upload_recording
from .recorder import make_output_path
from .schedule_verify import build_schedule_index, verify_program
from .vpngate import fetch_jp_servers

JST = timezone(timedelta(hours=9))

# NHK / Radiko の放送日は JST 5:00 - 翌 4:55
BROADCAST_DAY_HOUR = 5

# VPN 接続の最大試行回数 (足りない area を探し続ける上限)
MAX_VPN_ATTEMPTS = 15

# radiru (NHK) フェーズ全体に許す累計時間予算 (秒)。
#
# 2026-06-08〜07-04 にほぼ毎日発生した障害の実測: VPN Gate の JP サーバーは
# どれに繋いでも vod-stream.nhk.jp の HLS 取得が yt-dlp/ffmpeg 双方で
# 600 秒タイムアウトに達し、15 回の VPN 試行のうち事実上すべての時間が
# radiru の空振りリトライに溶けて、民放 (Radiko) が一度も DL される前に
# runner が "shutdown signal" (preemption) で強制終了されていた
# (2026-07-04 run 28720634773: 21:47 開始 → 22:20 に shutdown、その間
# radiko の DL 試行はエリア不一致で 0 件のまま)。
#
# radiru は日本国内 IP 限定で VPN 自体は必要 (b99ae7d で実測済み) だが、
# 同じ理由で失敗し続ける番組を 15 回すべての VPN セッションで律儀に
# リトライする価値はない。累計 radiru 処理時間がこの予算を超えたら、
# 残り試行はすべて Radiko 専用にして (未取得の NHK 番組は翌日 cron の
# 2 日分フォールバックに委ねる)、民放が全滅する事故を防ぐ。
RADIRU_TIME_BUDGET_SEC = 40 * 60


def _handle_sigterm(signum, _frame) -> None:
    """SIGTERM を通常の例外経路へ載せ、finally で子プロセスを回収する。"""
    raise SystemExit(128 + signum)


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


def _matched_keywords(program: Program, keywords: list[str]) -> list[str]:
    search_text = f"{program.title} {program.subtitle} {program.content}"
    return [kw for kw in keywords if kw in search_text]


def _is_already_uploaded(program: Program, config: Config) -> bool:
    """Notion DB に同じ番組が既登録なら True (DL 自体不要)。

    NHK r3 (vod-stream.nhk.jp の m3u8) は yt-dlp フォールバックで
    1 番組あたり 17〜39 分かかる。重複番組を捨てるためだけに DL を
    走らせると 6 件中 3 件重複するケースで 1 時間以上失う (2026-05-04
    の 2 時間ロングランの主因)。VPN ループ突入前にバッチで既登録判定し、
    DL 対象から除外する。Notion 未設定時は常に False。
    """
    if not (config.notion_token and config.notion_database_id):
        return False
    try:
        return bool(_find_duplicates(
            config.notion_token, config.notion_database_id, program,
        ))
    except Exception:
        # Notion 側の一時的不調なら DL は実施し、後段の upload_recording
        # 内の二重チェックに委ねる (defense in depth)。
        return False


def _upload_to_notion(
    program: Program,
    output_path: Path,
    config: Config,
    keywords: list[str],
) -> bool:
    """録音ファイルを Notion にアップする (Notion 未設定なら True を返す)。"""
    logger = logging.getLogger(__name__)
    if not (config.notion_token and config.notion_database_id):
        return True
    matched_kw = _matched_keywords(program, keywords)
    try:
        return bool(upload_recording(config, program, output_path, matched_kw))
    except Exception as e:
        logger.error("Notion アップロード失敗: %s - %s", program.title[:50], e)
        return False


def _download_nhk_via_radiru(
    program: Program,
    config: Config,
    keywords: list[str],
    counters: dict,
    counters_lock: threading.Lock,
    *,
    deadline: float | None = None,
) -> str:
    """NHK 番組を らじる★らじる 聴き逃し API で取得して Notion にアップする。

    Radiko へのフォールバックは行わない (Radiko 経由は NHK 配信停止で
    アナウンス音源しか取れないため)。

    Returns:
        - "uploaded": ダウンロード + Notion アップ成功 (or Notion 未設定)
        - "missing": 該当エピソードが radiru API に存在しない (永久スキップ)
        - "dl_failed": エピソードは存在するが m3u8 取得に失敗 (例: 国外 IP に
          よる 403)。VPN を張り替えてリトライする価値あり。
        - "no_series_id": program に series_id が無い (永久スキップ)
        - "upload_failed": DL は成功したが Notion アップロードに失敗
    """
    logger = logging.getLogger(__name__)
    if not program.series_id:
        logger.debug("series_id 未設定 (%s)、radiru 取得スキップ", program.title[:30])
        return "no_series_id"

    # find_episode 内で予期せぬ例外が起きた場合も Phase 1 全体を止めず
    # 次の番組に進めるよう、ここで安全網を張る (例: NHK API 仕様変更で
    # 想定外の応答が来た場合等)。
    try:
        episode = radiru_mod.find_episode(
            program.series_id, program.start_time,
            expected_title=program.title,  # 再放送枠で時刻不一致時のタイトル fallback 用
        )
    except Exception as e:
        logger.warning(
            "radiru find_episode 例外 (%s/%s): %s",
            program.series_id, program.title[:40], e,
        )
        # 一時的なネットワーク不調や API 揺らぎの可能性があるので、
        # "dl_failed" 扱いにして次の VPN パスでリトライさせる。
        return "dl_failed"
    if not episode:
        return "missing"

    output_path = make_output_path(config.output_dir, program)
    logger.info(
        "→ radiru DL: [%s] %s (%s)",
        program.service, program.title[:50], episode.program_title[:40],
    )
    ok = radiru_mod.download_ondemand(
        episode.stream_url, output_path, config.ffmpeg_path,
        deadline=deadline,
    )
    if not ok:
        logger.error("radiru DL 失敗: %s", program.title[:50])
        return "dl_failed"

    if deadline is not None and time.monotonic() >= deadline:
        logger.warning(
            "radiru DL 後に全体期限へ到達、upload を開始しない: %s",
            program.title[:50],
        )
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        return "dl_failed"

    uploaded = _upload_to_notion(program, output_path, config, keywords)
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass

    with counters_lock:
        if uploaded:
            counters["success"] += 1
            counters["via_radiru"] = counters.get("via_radiru", 0) + 1
        else:
            counters["failed"] += 1
    return "uploaded" if uploaded else "upload_failed"


def _download_and_upload(
    program: Program,
    station_id: str,
    auth: "radiko_mod.RadikoAuth",
    config: Config,
    keywords: list[str],
    counters: dict,
    counters_lock: threading.Lock,
    *,
    deadline: float | None = None,
) -> None:
    """1 番組を Radiko タイムフリーで DL して Notion にアップする (民放向け)。

    NHK 番組はこのパスに来ない (Phase 1 で radiru 経由で処理、radiru に
    無ければ丸ごとスキップ)。
    """
    output_path = make_output_path(config.output_dir, program)
    logger = logging.getLogger(__name__)
    logger.info("→ Radiko DL: [%s→%s] %s", program.service, station_id, program.title[:50])

    ok = radiko_mod.download_timefree(
        auth, station_id,
        program.start_time, program.end_time,
        output_path, config.ffmpeg_path,
        deadline=deadline,
    )
    if not ok:
        logger.error("DL 失敗: %s", program.title[:50])
        with counters_lock:
            counters["failed"] += 1
        return

    if deadline is not None and time.monotonic() >= deadline:
        logger.warning(
            "Radiko DL 後に全体期限へ到達、upload を開始しない: %s",
            program.title[:50],
        )
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        with counters_lock:
            counters["failed"] += 1
        return

    uploaded = _upload_to_notion(program, output_path, config, keywords)
    with counters_lock:
        if uploaded:
            counters["success"] += 1
        else:
            counters["failed"] += 1

    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass


RADIRU_PARALLELISM = 3
"""NHK radiru の並列 DL 数。

3 にしている理由:
- NHK API / vod-stream.nhk.jp は同一 IP からの 3 並列程度は十分捌ける
  (実測: 3 並列で 403/429 を観測せず)。
- ubuntu-latest runner は 2 vCPU / 7 GB RAM。yt-dlp + ffmpeg 1 プロセス
  あたり ~300 MB のため 3 並列で ~1 GB、十分余裕がある。
- VPN Gate JP サーバーの帯域は 1〜100 Mbps 幅広く、3 並列の HLS なら
  細い回線でもストールしにくい。
- 並列 1 → 3 で 6 件の NHK pass が 1h+ から 30 分前後に短縮 (3 倍弱)、
  GitHub Actions の runner preemption リスクを大幅に下げる。
"""


def _run_radiru_pass(
    pending: list[Program],
    config: Config,
    keywords: list[str],
    counters: dict,
    counters_lock: threading.Lock,
    max_workers: int = RADIRU_PARALLELISM,
    *,
    deadline: float | None = None,
) -> list[Program]:
    """現 VPN セッションで NHK 番組を radiru 経由で並列 DL する。

    NHK の m3u8 配信 (vod-stream.nhk.jp) は日本国内 IP 限定で、国外 IP からは
    HTTP 403 が返る。よって本処理は VPN 接続中 (日本 IP) でのみ意味を持つ。

    並列化の意義: 直列処理だと長尺音楽番組 (115 分の 名演奏ライブラリー 等)
    で 1 件 30+ 分を費やし、6 件で 1 時間を超えて runner preemption の
    リスクが高まる (実測 2026-05-23: 1h11m で外部 cancel)。並列化で job
    全体時間を短縮し、orchestrator cancel される確率を下げる。

    Returns:
        この VPN パスで DL できなかった番組 (次の VPN で再試行)。
        "missing" / "no_series_id" / "uploaded" / "upload_failed" は
        いずれも次パスで再試行しない (永久確定) のでリストから除外する。
    """
    logger = logging.getLogger(__name__)
    now = datetime.now(JST)

    # 未放送は timefree に存在しないので並列 DL 対象から除外 (即時 skip)
    eligible: list[Program] = []
    for p in pending:
        if p.end_time > now:
            logger.info(
                "未放送スキップ: [%s] %s %s",
                p.service, p.start_time.strftime("%Y-%m-%d %H:%M"),
                p.title[:50],
            )
            with counters_lock:
                counters["skipped"] += 1
        else:
            eligible.append(p)

    if not eligible:
        return []

    workers = min(max_workers, len(eligible))
    logger.info("radiru 並列 DL: %d 件 (並列度 %d)", len(eligible), workers)

    # 並列実行: 1 thread = 1 番組の find_episode → DL → Notion upload を完結。
    # _download_nhk_via_radiru は counters_lock を使うため thread-safe。
    statuses: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="radiru") as ex:
        future_to_program = {
            ex.submit(
                _download_nhk_via_radiru,
                p, config, keywords, counters, counters_lock,
                deadline=deadline,
            ): p
            for p in eligible
        }
        for fut, p in future_to_program.items():
            try:
                statuses[p.id] = fut.result()
            except Exception as e:
                # _download_nhk_via_radiru 自体は内部で例外を握っているが、
                # 予期せぬ事故 (例: スレッド起動失敗) で漏れた場合の保険。
                logger.error(
                    "radiru 並列実行内例外 (%s): %s", p.title[:40], e,
                )
                statuses[p.id] = "dl_failed"

    # status に応じて remaining (次パス再試行) を組み立てる。
    # 元の逐次版と同じ判定ルールを維持し、ログも同じ文言で出力する。
    remaining: list[Program] = []
    for p in eligible:
        s = statuses.get(p.id, "dl_failed")
        if s == "dl_failed":
            # 国外 IP (VPN 切断 or area 不一致) で 403 の可能性が高い。
            # 次の VPN サーバーで再試行する。
            remaining.append(p)
        elif s in ("missing", "no_series_id"):
            logger.warning(
                "radiru 未収録でスキップ (再放送/配信期間切れ等): [%s] %s %s",
                p.service, p.start_time.strftime("%Y-%m-%d %H:%M"),
                p.title[:50],
            )
            with counters_lock:
                counters["radiru_missing"] += 1
        # "uploaded" / "upload_failed" はカウンタ更新済み、次パス不要

    return remaining


def _run_one_pass(
    pending: list[Program],
    auth: "radiko_mod.RadikoAuth",
    config: Config,
    keywords: list[str],
    counters: dict,
    counters_lock: threading.Lock,
    verify_schedule: bool = True,
    *,
    deadline: float | None = None,
) -> list[Program]:
    """現在の VPN セッションで取得可能な番組を並列 DL し、残りを返す。

    Args:
        pending: まだ DL できていない番組
        verify_schedule: True の場合、録音直前に Radiko 最新スケジュールで
            予定タイトルとクロスチェックし、差し替えられた番組を弾く。

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

    # Radiko 最新スケジュールでキャッシュ JSON をクロスチェック。
    # 同日に番組が差し替えられたケース (例: 2026-04-14 の「放送していない
    # 番組を録音」) はキャッシュと乖離するためここで検出する。
    schedule_index: dict = {}
    if verify_schedule and pending:
        target_dates = sorted({
            _broadcast_date(p.start_time.astimezone(JST)) for p in pending
        })
        try:
            schedule_index = build_schedule_index(auth.area_id, target_dates)
        except Exception as e:
            logger.warning(
                "Radiko スケジュール取得失敗、検証をスキップ: %s", e,
            )
            schedule_index = {}

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

        # Radiko 最新スケジュールとクロスチェック
        # NHK 本家 (r1/r3) は NHK 同時配信局 (JOAK/JOBK/-FM) の Radiko 側
        # スケジュールを参照する (同じ放送内容が流れる)。
        if verify_schedule and schedule_index:
            verify_station = station_id
            actual = verify_program(p, verify_station, schedule_index)
            if not actual.ok:
                logger.warning(
                    "スケジュール不一致で録音スキップ: [%s] %s %s-%s 予定=%r 実際=%r (%s)",
                    p.service,
                    p.start_time.strftime("%Y-%m-%d"),
                    p.start_time.strftime("%H:%M"),
                    p.end_time.strftime("%H:%M"),
                    p.title[:50],
                    actual.actual_title[:50],
                    actual.reason,
                )
                with counters_lock:
                    counters["mismatch"] = counters.get("mismatch", 0) + 1
                # 不一致は次の area でも同じ結果 (Radiko データは area 非依存の
                # 時間軸) なので remaining には残さず破棄する。
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
            kwargs={"deadline": deadline},
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
        help=f"最大 VPN 試行回数 (デフォルト: {MAX_VPN_ATTEMPTS})",
    )
    parser.add_argument(
        "--max-runtime-sec", type=int,
        help="全体実行時間の上限秒数 (未指定なら制限なし)",
    )
    parser.add_argument(
        "--vpn-config", default="vpn.ovpn",
        help="openvpn 設定ファイルの書き出し先 (デフォルト: vpn.ovpn)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="DL せず対象番組一覧のみ表示",
    )
    parser.add_argument(
        "--no-verify-schedule", action="store_true",
        help="Radiko 最新スケジュールでのクロスチェックを無効にする "
             "(デフォルト: 有効。差し替え番組の誤録音を防止)",
    )
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _handle_sigterm)
    if args.max_runtime_sec is not None and args.max_runtime_sec <= 0:
        parser.error("--max-runtime-sec は正の整数を指定してください")
    run_deadline = (
        time.monotonic() + args.max_runtime_sec
        if args.max_runtime_sec is not None else None
    )

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    config.output_dir.mkdir(parents=True, exist_ok=True)

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

    # Notion 既登録フィルタ (DL 前)
    # ダウンロード後に upload_recording 内で重複検知すると、最大 30 分以上の
    # radiru DL が無駄になる。VPN ループ突入前にバッチクエリで除外する。
    already_uploaded = 0
    if not args.dry_run and config.notion_token and config.notion_database_id:
        not_yet: list[Program] = []
        for p in matched:
            if _is_already_uploaded(p, config):
                logger.info(
                    "Notion 既登録スキップ: [%s] %s %s-%s %s",
                    p.service,
                    p.start_time.strftime("%Y-%m-%d"),
                    p.start_time.strftime("%H:%M"),
                    p.end_time.strftime("%H:%M"),
                    p.title[:50],
                )
                already_uploaded += 1
            else:
                not_yet.append(p)
        if already_uploaded:
            logger.info(
                "Notion 既登録フィルタ: %d 件除外、残り %d 件を DL 対象",
                already_uploaded, len(not_yet),
            )
        matched = not_yet

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
        if run_deadline is not None and time.monotonic() >= run_deadline:
            logger.error("全体実行期限へ到達")
            sys.exit(124)
        logger.info("ドライラン完了")
        return

    if not matched:
        if run_deadline is not None and time.monotonic() >= run_deadline:
            logger.error("全体実行期限へ到達")
            sys.exit(124)
        logger.info("対象番組なし、終了")
        return

    counters = {
        "success": 0, "failed": 0, "skipped": 0,
        "mismatch": 0, "radiru_missing": 0, "via_radiru": 0,
        "already_uploaded": already_uploaded,
    }
    counters_lock = threading.Lock()

    # ================================================================
    # NHK 本家 (r1/r3) は らじる★らじる 聴き逃し経由でのみ取得する。
    # Radiko タイムフリーは NHK の多くの番組を「配信停止」扱いとし、
    # アクセスすると「大変申し訳ありませんが…配信を停止しております」という
    # アナウンス音源に置換される (2026-04-14 インシデントの真因)。
    #
    # ただし NHK の m3u8 ストリーム (vod-stream.nhk.jp) は **日本国内 IP 限定**
    # で、Azure runner などの国外 IP からは HTTP 403 が返るため、radiru
    # ダウンロードも VPN ループ内 (日本 IP に乗せ替えた状態) で行う必要がある。
    # ================================================================
    nhk_pending: list[Program] = [p for p in matched if p.service in ("r1", "r3")]
    radiko_pending: list[Program] = [p for p in matched if p.service not in ("r1", "r3")]
    logger.info(
        "対象内訳: NHK (radiru 経由) %d 件 / 民放 (Radiko 経由) %d 件",
        len(nhk_pending), len(radiko_pending),
    )

    # ================================================================
    # マルチ VPN パス: 各セッションで NHK (radiru) → 民放 (Radiko) の順に DL
    # ================================================================
    if run_deadline is not None and time.monotonic() >= run_deadline:
        logger.error("全体実行期限へ到達")
        sys.exit(124)
    logger.info("VPN Gate サーバーリスト取得中...")
    vpn_servers = fetch_jp_servers(limit=50)
    if run_deadline is not None and time.monotonic() >= run_deadline:
        logger.error("VPN Gate サーバー取得中に全体実行期限へ到達")
        sys.exit(124)
    if not vpn_servers:
        logger.error("VPN Gate サーバー取得失敗")
        sys.exit(2)

    # private (一般ユーザー提供) サーバーを優先して並べる。
    # public-vpn-* (筑波大 SoftEther 公式) は高スコアだが出口エリアが
    # JP23/JP17/JP1 等に偏る。private サーバーは全国に分散しているため
    # JP27 (大阪=ABC) や JP13 (東京=LFR/TBS) に当たる確率が高い。
    import random
    private = [s for s in vpn_servers if not s.hostname.startswith("public-vpn-")]
    public = [s for s in vpn_servers if s.hostname.startswith("public-vpn-")]
    random.shuffle(private)  # private 内はランダムで area 多様性を確保
    vpn_servers = private + public
    logger.info(
        "VPN Gate: %d 台 (private %d + public %d)",
        len(vpn_servers), len(private), len(public),
    )

    attempted_radiko_areas: set[str] = set()
    vpn_config_path = Path(args.vpn_config)
    radiru_deadline = time.monotonic() + RADIRU_TIME_BUDGET_SEC
    if run_deadline is not None:
        radiru_deadline = min(radiru_deadline, run_deadline)
    radiru_budget_exhausted = False
    deadline_exhausted = False

    for attempt_idx, server in enumerate(vpn_servers, start=1):
        if run_deadline is not None and time.monotonic() >= run_deadline:
            deadline_exhausted = True
            break
        if not nhk_pending and not radiko_pending:
            logger.info("全番組 DL 完了、VPN ループ終了")
            break
        if not radiko_pending and radiru_budget_exhausted:
            # 民放は完了済み、NHK は時間予算切れで以降トライしないので
            # これ以上 VPN を張り替えても得るものがない。
            logger.info(
                "民放 DL 完了 + radiru 予算切れ、VPN ループ終了 "
                "(NHK %d 件は翌日 cron へ)",
                len(nhk_pending),
            )
            break
        if attempt_idx > args.max_vpn_attempts:
            logger.warning(
                "VPN 最大試行回数 %d に到達、残り NHK %d / 民放 %d 件未取得",
                args.max_vpn_attempts, len(nhk_pending), len(radiko_pending),
            )
            break

        logger.info(
            "=== VPN 試行 %d/%d: %s (IP=%s score=%d) "
            "[pending NHK %d / 民放 %d] ===",
            attempt_idx, args.max_vpn_attempts,
            server.hostname, server.ip, server.score,
            len(nhk_pending), len(radiko_pending),
        )

        # Config を書き出し
        try:
            server.write_ovpn(vpn_config_path)
        except (OSError, ValueError) as e:
            logger.error("ovpn 書き出し失敗: %s", e)
            continue

        try:
            # VPN 接続も try 内に置き、接続中の SIGTERM/例外でも回収する。
            if not vpn_manager.connect(vpn_config_path, deadline=run_deadline):
                logger.warning("VPN 接続失敗、次へ")
                continue

            # 1) 民放 Radiko を先に処理する (2026-07 障害対応で順序を反転)。
            #    radiru は 1 件あたり最大 timeout_sec 秒 (現状 600s) を
            #    3 並列で溶かし得るのに対し、Radiko 認証・番組表取得は
            #    数秒〜数十秒で完了/失敗が判明する。radiru を先にすると、
            #    VPN Gate の回線が細くて radiru が長時間スタックした場合に
            #    runner preemption ("shutdown signal") で job ごと落ちて
            #    Radiko が一度も試されない事故が起きる (2026-07-04
            #    run 28720634773 で実測)。Radiko を先に試すことで、この
            #    セッションの Japan IP を無駄にせず民放分だけでも稼げる。
            #    area 多様性のためエリア重複は skip。
            if radiko_pending:
                auth = radiko_mod.authenticate()
                if not auth:
                    logger.warning("Radiko 認証失敗、Radiko パートはスキップ")
                elif auth.area_id in attempted_radiko_areas:
                    logger.info(
                        "既に試した area=%s、Radiko パートはスキップ", auth.area_id,
                    )
                else:
                    logger.info("area=%s (%s) に接続", auth.area_id, auth.area_name)
                    attempted_radiko_areas.add(auth.area_id)
                    radiko_pending = _run_one_pass(
                        radiko_pending, auth, config, keywords, counters,
                        counters_lock,
                        verify_schedule=not args.no_verify_schedule,
                        deadline=run_deadline,
                    )

            if run_deadline is not None and time.monotonic() >= run_deadline:
                deadline_exhausted = True
                continue

            # 2) NHK radiru: 日本 IP でさえあれば area に依存しないので
            #    Radiko の結果に関わらず試す。ただし累計処理時間が
            #    RADIRU_TIME_BUDGET_SEC を超えたら、同じ理由 (VPN 回線の
            #    帯域不足) で今後も失敗し続ける可能性が高いと判断し、
            #    残り試行は Radiko 専用にする (未取得分は翌日 cron の
            #    2 日分フォールバックに委ねる)。
            if nhk_pending:
                if not radiru_budget_exhausted and (
                    time.monotonic() < radiru_deadline
                ):
                    logger.info(
                        "--- radiru で NHK %d 件を取得 ---", len(nhk_pending),
                    )
                    nhk_pending = _run_radiru_pass(
                        nhk_pending, config, keywords, counters, counters_lock,
                        deadline=radiru_deadline,
                    )
                elif not radiru_budget_exhausted:
                    radiru_budget_exhausted = True
                    logger.warning(
                        "radiru 累計処理時間が予算 %ds を超過、残り NHK %d 件は"
                        "以降の VPN 試行では取得せず翌日 cron に委ねる",
                        RADIRU_TIME_BUDGET_SEC, len(nhk_pending),
                    )
        finally:
            vpn_manager.disconnect()

    pending = nhk_pending + radiko_pending
    deadline_exhausted = deadline_exhausted or (
        run_deadline is not None and time.monotonic() >= run_deadline
    )
    if deadline_exhausted:
        logger.error("全体実行期限へ到達、残り %d 件", len(pending))
    _report_and_exit(
        counters, len(pending), logger, pending,
        deadline_exhausted=deadline_exhausted,
    )


def _report_and_exit(
    counters: dict,
    remaining_count: int,
    logger: logging.Logger,
    pending: list[Program] | None = None,
    *,
    deadline_exhausted: bool = False,
) -> None:
    """最終レポートを出して、全滅していれば非ゼロで終了する。"""
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
        "=== 完了: 成功 %d (うち radiru %d) / 失敗 %d / "
        "既登録 %d / radiru 未収録 %d / 未放送スキップ %d / "
        "差替スキップ %d / 未カバー %d ===",
        counters["success"],
        counters.get("via_radiru", 0),
        counters["failed"],
        counters.get("already_uploaded", 0),
        counters.get("radiru_missing", 0),
        counters["skipped"],
        counters["mismatch"],
        remaining_count,
    )

    if deadline_exhausted:
        sys.exit(124)
    if (
        counters["success"] == 0
        and counters["failed"] > 0
        and counters["skipped"] == 0
    ):
        sys.exit(3)


if __name__ == "__main__":
    main()
