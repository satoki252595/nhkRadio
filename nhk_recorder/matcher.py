import logging

from .api import Program

logger = logging.getLogger(__name__)


def filter_programs(programs: list[Program], keywords: list[str]) -> list[Program]:
    """キーワードにマッチする番組をフィルタリングする。

    title, subtitle, content のいずれかにキーワードが含まれていればマッチ。

    Args:
        programs: 番組リスト
        keywords: 検索キーワードリスト

    Returns:
        マッチした番組リスト (start_time順、重複排除済み)
    """
    if not keywords:
        return []

    seen_ids: set[str] = set()
    matched: list[Program] = []

    for program in programs:
        if program.id in seen_ids:
            continue

        search_text = f"{program.title} {program.subtitle} {program.content}"
        if any(kw in search_text for kw in keywords):
            matched.append(program)
            seen_ids.add(program.id)
            logger.debug("マッチ: [%s] %s (%s)", program.service, program.title, program.start_time)

    matched.sort(key=lambda p: p.start_time)
    return matched


def filter_by_series(programs: list[Program], series_ids: list[str]) -> list[Program]:
    """購読中のシリーズに一致する番組をフィルタリングする。

    Args:
        programs: 番組リスト
        series_ids: 購読中のシリーズIDリスト

    Returns:
        マッチした番組リスト (start_time順、重複排除済み)
    """
    if not series_ids:
        return []

    subscribed = set(series_ids)
    seen_ids: set[str] = set()
    matched: list[Program] = []

    for program in programs:
        if program.id in seen_ids:
            continue
        if program.series_id and program.series_id in subscribed:
            matched.append(program)
            seen_ids.add(program.id)
            logger.debug("シリーズマッチ: [%s] %s (%s)", program.service, program.title, program.series_name)

    matched.sort(key=lambda p: p.start_time)
    return matched
