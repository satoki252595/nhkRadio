import logging
import threading
from datetime import datetime, timedelta, timezone

from .api import Program
from .config import Config
from .notion import upload_recording
from .recorder import make_output_path, record

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def schedule_recordings(
    programs: list[Program],
    stream_urls: dict[str, str],
    config: Config,
    matched_keywords: list[str] | None = None,
) -> None:
    """番組の開始時刻に合わせて録音をスケジュールし、全完了まで待機する。"""
    now = datetime.now(JST)
    timers: list[threading.Timer] = []
    done_event = threading.Event()
    remaining = {"count": 0}
    lock = threading.Lock()

    def on_complete():
        with lock:
            remaining["count"] -= 1
            if remaining["count"] <= 0:
                done_event.set()

    for program in programs:
        stream_url = stream_urls.get(program.service)
        if not stream_url:
            logger.warning("ストリームURLが不明: %s", program.service)
            continue

        seconds_until = (program.start_time - now).total_seconds()

        if seconds_until < -program.duration:
            logger.info("既に終了済み: [%s] %s", program.service, program.title)
            continue

        output_path = make_output_path(config.output_dir, program)

        # 録音の実行関数
        def do_record(url=stream_url, dur=program.duration, path=output_path, title=program.title, prog=program):
            logger.info("録音実行: %s", title)
            success = record(url, dur, path, config.ffmpeg_path)
            if success:
                _upload_to_notion(config, prog, path, matched_keywords or [])
            on_complete()

        if seconds_until <= 30:
            # 既に開始している/まもなく開始 → 即録音
            remaining_duration = program.duration + int(min(seconds_until, 0))
            if remaining_duration <= 0:
                continue

            def do_record_now(url=stream_url, dur=remaining_duration, path=output_path, title=program.title, prog=program):
                logger.info("録音実行(即時): %s", title)
                success = record(url, dur, path, config.ffmpeg_path)
                if success:
                    _upload_to_notion(config, prog, path, matched_keywords or [])
                on_complete()

            remaining["count"] += 1
            t = threading.Thread(target=do_record_now)
            t.daemon = True
            t.start()
            logger.info(
                "即時録音開始: [%s] %s (%d秒)",
                program.service, program.title, remaining_duration,
            )
        else:
            remaining["count"] += 1
            timer = threading.Timer(seconds_until, do_record)
            timer.daemon = True
            timers.append(timer)
            timer.start()

            start_str = program.start_time.strftime("%H:%M")
            logger.info(
                "録音予約: [%s] %s %s開始 (あと%.0f分, %d秒間)",
                program.service, program.title, start_str,
                seconds_until / 60, program.duration,
            )

    if remaining["count"] == 0:
        logger.info("録音対象の番組がありません")
        return

    logger.info("全%d件の録音完了を待機中...", remaining["count"])
    done_event.wait()
    logger.info("全録音が完了しました")


def _upload_to_notion(config: Config, program: Program, file_path, keywords: list[str]) -> None:
    """録音完了後にNotionへアップロード。"""
    from pathlib import Path
    path = Path(file_path)
    if not config.notion_token or not config.notion_database_id:
        return

    # 番組にマッチしたキーワードのみ抽出
    search_text = f"{program.title} {program.subtitle} {program.content}"
    matched = [kw for kw in keywords if kw in search_text]

    try:
        upload_recording(config, program, path, matched)
    except Exception as e:
        logger.error("Notionアップロード失敗: %s - %s", program.title, e)
