"""録音直前に Radiko の最新スケジュールで番組タイトルを検証するユーティリティ。

問題背景:
    programs-YYYY-MM-DD.json は放送当日の 04:30 JST に書き出され、その後
    一切更新されない。NHK / 民放が当日中にスケジュールを差し替えた場合、
    キャッシュには予定の番組タイトルが残るが Radiko タイムフリーは
    実際に流れた音声を返すため、Notion には「予定メタデータ × 差し替え音声」
    のミスマッチが保存される。

対策:
    録音直前に Radiko の最新スケジュールを取得し、各マッチ番組と同一の
    (station, start_time) に存在する番組タイトルを比較する。類似度が低い
    場合 (タイトルが大きく変わっている = 別番組に差し替えられた) は録音を
    スキップする。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from .api import Program
from . import radiko as radiko_mod

logger = logging.getLogger(__name__)

# 類似度がこれを下回ると「別番組」と判定する。
# 0.30 は経験的に、連続番組の回変更 (「第9回」→「第10回」) は通過させ、
# 完全に別番組への差し替えは弾く閾値。
SIMILARITY_THRESHOLD = 0.30


@dataclass
class VerificationResult:
    ok: bool
    reason: str = ""
    actual_title: str = ""


def _normalize_title(title: str) -> str:
    """データソース間のタイトル差 (局名プレフィックス, 回数, 全角空白) を吸収する。

    data_export._normalize_title と同じ振る舞い + 回数マーカー除去を
    まとめて行う (依存グラフをフラットに保つためここに複製)。
    """
    if not title:
        return ""
    t = re.sub(r"^\[[^\]]+\]\s*", "", title)
    # 全角英数を半角に正規化 (Lesson/(1) 系マーカーの扱いを簡単にする)
    t = _to_halfwidth(t)
    # エピソード番号・回数マーカー (順序重要: Lesson 系を先に剥がす)
    t = re.sub(r"\s*Lesson\s*\(\s*[0-9]+\s*\)\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\([1-9][0-9]{0,2}\)\s*$", "", t)
    t = re.sub(r"\s*第[1-9][0-9]*[部回話]\s*$", "", t)
    # (N) を剥がした後に取り残された trailing "Lesson"
    t = re.sub(r"\s+Lesson\s*$", "", t, flags=re.IGNORECASE)
    # 連続空白を単一半角へ
    t = re.sub(r"[\s　]+", " ", t).strip()
    return t


def _to_halfwidth(s: str) -> str:
    """全角英数・括弧を半角に正規化する。"""
    out: list[str] = []
    for ch in s:
        code = ord(ch)
        # 全角英数 (Ａ-Ｚａ-ｚ０-９) → 半角
        if 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A or 0xFF10 <= code <= 0xFF19:
            out.append(chr(code - 0xFEE0))
        elif ch == "（":
            out.append("(")
        elif ch == "）":
            out.append(")")
        else:
            out.append(ch)
    return "".join(out)


def _char_bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _similarity(a: str, b: str) -> float:
    """Jaccard 類似度 (文字 bigram)。0.0 - 1.0。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ba = _char_bigrams(a)
    bb = _char_bigrams(b)
    if not ba or not bb:
        return 0.0
    inter = len(ba & bb)
    union = len(ba | bb)
    return inter / union if union else 0.0


def _resolve_station_id(
    service: str,
    nhk_am: str | None,
    nhk_fm: str | None,
) -> str | None:
    """Program.service → Radiko station_id。main._service_to_station と同等。"""
    if service == "r1":
        return nhk_am
    if service == "r3":
        return nhk_fm
    if service.startswith("radiko:"):
        return service.split(":", 1)[1]
    return None


def build_schedule_index(
    area_id: str,
    dates: list[str],
) -> dict[tuple[str, str], "radiko_mod.RadikoProgram"]:
    """Radiko の指定エリア・日付の番組表から (station_id, start_iso) → RadikoProgram の索引を作る。

    Args:
        area_id: 例 "JP27"
        dates:   例 ["2026-04-14"] (放送日 YYYY-MM-DD、複数指定可)

    Returns:
        (station_id, start_time.isoformat()) をキーとした辞書。
        取得に失敗したら空辞書。
    """
    index: dict[tuple[str, str], "radiko_mod.RadikoProgram"] = {}
    for date in dates:
        progs = radiko_mod.fetch_programs(area_id, date)
        for rp in progs:
            index[(rp.station_id, rp.start_time.isoformat())] = rp
    logger.info(
        "Radiko スケジュール索引: %d エントリ (area=%s, dates=%s)",
        len(index), area_id, dates,
    )
    return index


def _nearest_slot(
    index: dict[tuple[str, str], "radiko_mod.RadikoProgram"],
    station_id: str,
    start_time: datetime,
    tolerance_sec: int = 300,
) -> "radiko_mod.RadikoProgram | None":
    """station_id 内で start_time に最も近い RadikoProgram を返す (±tolerance 以内)。

    NHK の :03 秒オフセットや Radiko 側の 0 秒丸めの差を吸収するため、完全一致
    だけでなく ±5 分以内の最近傍を取る。
    """
    # まず完全一致
    hit = index.get((station_id, start_time.isoformat()))
    if hit:
        return hit
    # フォールバック: 同一局で時刻が最も近いもの
    best: "radiko_mod.RadikoProgram | None" = None
    best_diff = tolerance_sec + 1
    for (sid, _iso), rp in index.items():
        if sid != station_id:
            continue
        diff = abs((rp.start_time - start_time).total_seconds())
        if diff <= tolerance_sec and diff < best_diff:
            best = rp
            best_diff = diff
    return best


def verify_program(
    program: Program,
    station_id: str,
    index: dict[tuple[str, str], "radiko_mod.RadikoProgram"],
) -> VerificationResult:
    """録音予定の番組が Radiko 最新スケジュールと一致するか検証する。

    - 該当 (station, start_time) に Radiko 番組が無ければミスマッチ (枠が消失)
    - タイトル類似度が閾値未満ならミスマッチ (差し替え)
    - 類似度閾値以上なら OK
    """
    actual = _nearest_slot(index, station_id, program.start_time)
    if actual is None:
        return VerificationResult(
            ok=False,
            reason="該当時間帯に Radiko スケジュール無し (枠消失/未放送)",
        )

    expected_norm = _normalize_title(program.title)
    actual_norm = _normalize_title(actual.title)
    sim = _similarity(expected_norm, actual_norm)

    if sim < SIMILARITY_THRESHOLD:
        return VerificationResult(
            ok=False,
            reason=f"タイトル不一致 (類似度 {sim:.2f} < {SIMILARITY_THRESHOLD})",
            actual_title=actual.title,
        )

    return VerificationResult(ok=True, actual_title=actual.title)
