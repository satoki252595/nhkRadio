import logging
import math
import time
from pathlib import Path
from typing import Callable, TypeVar

import httpx

from .api import Program
from .config import Config

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
PART_SIZE = 10 * 1024 * 1024  # 10MB
SMALL_FILE_LIMIT = 20 * 1024 * 1024  # 20MB

# リトライ設定: Notion API は瞬断・タイムアウトが時々起きるため、
# 録音成功後にアップロード失敗すると永久に消失するので必ずリトライする。
RETRY_MAX_ATTEMPTS = 4
RETRY_BACKOFF_BASE = 3.0  # 秒 (3s, 6s, 12s)

T = TypeVar("T")


def _retry(label: str, func: Callable[[], T]) -> T | None:
    """指数バックオフで func() をリトライ。最終失敗時は None を返す。"""
    last_exc: Exception | None = None
    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            return func()
        except (httpx.RequestError, httpx.HTTPStatusError, httpx.TransportError) as e:
            last_exc = e
            if attempt < RETRY_MAX_ATTEMPTS:
                wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "%s リトライ %d/%d (%.0fs後): %s",
                    label, attempt, RETRY_MAX_ATTEMPTS - 1, wait, e,
                )
                time.sleep(wait)
            else:
                logger.error("%s 最終失敗 (%d回試行): %s", label, RETRY_MAX_ATTEMPTS, e)
    return None


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }


def _json_headers(token: str) -> dict[str, str]:
    return {
        **_headers(token),
        "Content-Type": "application/json",
    }


def upload_file(token: str, file_path: Path) -> str | None:
    """ファイルをNotionにアップロードし、file_upload IDを返す。

    20MB以下: single mode
    20MB超: multi_part mode
    """
    file_size = file_path.stat().st_size
    filename = file_path.name
    content_type = "audio/mp4"  # M4A

    if file_size <= SMALL_FILE_LIMIT:
        return _upload_single(token, file_path, filename, content_type)
    else:
        return _upload_multipart(token, file_path, filename, content_type, file_size)


def _upload_single(token: str, file_path: Path, filename: str, content_type: str) -> str | None:
    """20MB以下のファイルをsingleモードでアップロード。リトライ対応。"""
    # Step 1: Create file upload
    def _create():
        r = httpx.post(
            f"{NOTION_API_BASE}/file_uploads",
            headers=_json_headers(token),
            json={"filename": filename, "content_type": content_type},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    upload_data = _retry("ファイルアップロード作成", _create)
    if not upload_data:
        return None

    upload_id = upload_data["id"]
    upload_url = upload_data.get("upload_url", f"{NOTION_API_BASE}/file_uploads/{upload_id}/send")

    # Step 2: Send file (リトライ毎にファイルを開き直す)
    def _send():
        with open(file_path, "rb") as f:
            r = httpx.post(
                upload_url,
                headers=_headers(token),
                files={"file": (filename, f, content_type)},
                timeout=300,
            )
        r.raise_for_status()
        return r.json()

    result = _retry(f"ファイル送信 ({filename})", _send)
    if not result:
        return None

    if result.get("status") == "uploaded":
        logger.info("ファイルアップロード完了: %s (%s)", filename, upload_id)
        return upload_id

    logger.error("アップロードステータス異常: %s", result.get("status"))
    return None


def _upload_multipart(
    token: str, file_path: Path, filename: str, content_type: str, file_size: int
) -> str | None:
    """20MB超のファイルをmulti_partモードでアップロード。リトライ対応。"""
    number_of_parts = math.ceil(file_size / PART_SIZE)

    # Step 1: Create multi-part upload
    def _create():
        r = httpx.post(
            f"{NOTION_API_BASE}/file_uploads",
            headers=_json_headers(token),
            json={
                "mode": "multi_part",
                "number_of_parts": number_of_parts,
                "filename": filename,
                "content_type": content_type,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    upload_data = _retry("マルチパートアップロード作成", _create)
    if not upload_data:
        return None

    upload_id = upload_data["id"]

    # Step 2: Send parts (各パートを個別にリトライ)
    with open(file_path, "rb") as f:
        for part_num in range(1, number_of_parts + 1):
            chunk = f.read(PART_SIZE)

            def _send_part(_chunk=chunk, _part=part_num):
                r = httpx.post(
                    f"{NOTION_API_BASE}/file_uploads/{upload_id}/send",
                    headers=_headers(token),
                    files={"file": (filename, _chunk, content_type)},
                    data={"part_number": str(_part)},
                    timeout=300,
                )
                r.raise_for_status()
                return r.json()

            result = _retry(f"パート{part_num}送信", _send_part)
            if result is None:
                return None
            logger.info("パート %d/%d アップロード完了", part_num, number_of_parts)

    # Step 3: Complete upload
    complete_url = upload_data.get("complete_url", f"{NOTION_API_BASE}/file_uploads/{upload_id}/complete")

    def _complete():
        r = httpx.post(complete_url, headers=_json_headers(token), timeout=30)
        r.raise_for_status()
        return r.json()

    if _retry("アップロード完了処理", _complete) is None:
        return None

    logger.info("マルチパートアップロード完了: %s (%d parts)", filename, number_of_parts)
    return upload_id


def create_recording_page(
    token: str,
    database_id: str,
    program: Program,
    file_upload_id: str,
    matched_keywords: list[str],
) -> str | None:
    """録音データのページをNotionデータベースに作成する。"""
    start_str = program.start_time.strftime("%H:%M")
    end_str = program.end_time.strftime("%H:%M")
    date_str = program.start_time.strftime("%Y-%m-%d")
    channel = program.service.upper()

    properties = {
        "番組名": {
            "title": [{"text": {"content": program.title}}],
        },
        "チャンネル": {
            "select": {"name": channel},
        },
        "放送日": {
            "date": {"start": date_str},
        },
        "時間帯": {
            "rich_text": [{"text": {"content": f"{start_str}-{end_str}"}}],
        },
        "録音時間(分)": {
            "number": program.duration // 60,
        },
        "キーワード": {
            "multi_select": [{"name": kw} for kw in matched_keywords],
        },
        "音声ファイル": {
            "files": [
                {
                    "type": "file_upload",
                    "file_upload": {"id": file_upload_id},
                    "name": f"{date_str}_{channel}_{program.title}.m4a",
                }
            ],
        },
    }

    def _create_page():
        r = httpx.post(
            f"{NOTION_API_BASE}/pages",
            headers=_json_headers(token),
            json={
                "parent": {"database_id": database_id},
                "properties": properties,
                "icon": {"emoji": "📻"},
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    page_data = _retry(f"ページ作成 ({program.title[:30]})", _create_page)
    if not page_data:
        return None

    page_id = page_data["id"]
    logger.info("Notionページ作成完了: %s - %s", program.title, page_id)
    return page_id


def _normalize_title(title: str) -> str:
    """番組タイトルを正規化 (局名プレフィックスや全角空白の違いを吸収)。"""
    import re
    t = re.sub(r"^\[[^\]]+\]\s*", "", title)
    t = re.sub(r"[\s　]+", " ", t).strip()
    return t


def _check_duplicate(
    token: str,
    database_id: str,
    program: Program,
) -> bool:
    """Notion DBに同一番組が既に登録済みかチェックする。

    (放送日, 時間帯) でフィルタし、タイトルを正規化して比較する。
    NHK本家 (R3) と Radiko同時配信 (JOAK-FM) の重複も検出する。
    """
    date_str = program.start_time.strftime("%Y-%m-%d")
    start_str = program.start_time.strftime("%H:%M")
    end_str = program.end_time.strftime("%H:%M")
    time_slot = f"{start_str}-{end_str}"

    try:
        resp = httpx.post(
            f"{NOTION_API_BASE}/databases/{database_id}/query",
            headers=_json_headers(token),
            json={
                "filter": {
                    "and": [
                        {"property": "放送日", "date": {"equals": date_str}},
                        {"property": "時間帯", "rich_text": {"equals": time_slot}},
                    ]
                },
                "page_size": 10,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("Notion重複チェック失敗 (HTTP %d)、アップロード続行", resp.status_code)
            return False

        results = resp.json().get("results", [])
        if not results:
            return False

        norm_new = _normalize_title(program.title)
        for page in results:
            props = page.get("properties", {})
            title_arr = props.get("番組名", {}).get("title", [])
            existing_title = title_arr[0]["plain_text"] if title_arr else ""
            if _normalize_title(existing_title) == norm_new:
                return True

        return False
    except httpx.RequestError as e:
        logger.warning("Notion重複チェックエラー: %s、アップロード続行", e)
        return False


def upload_recording(
    config: Config,
    program: Program,
    file_path: Path,
    matched_keywords: list[str],
) -> bool:
    """録音ファイルをNotionにアップロードし、データベースエントリを作成する。"""
    if not config.notion_token or not config.notion_database_id:
        logger.debug("Notion連携が未設定のためスキップ")
        return False

    if not file_path.exists():
        logger.error("録音ファイルが見つかりません: %s", file_path)
        return False

    # 重複チェック (同一番組が既にアップロード済みならスキップ)
    if _check_duplicate(config.notion_token, config.notion_database_id, program):
        logger.info("重複スキップ: %s (Notionに登録済み)", program.title)
        return True

    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    logger.info("Notionアップロード開始: %s (%.1fMB)", file_path.name, file_size_mb)

    # ファイルアップロード
    file_upload_id = upload_file(config.notion_token, file_path)
    if not file_upload_id:
        return False

    # ページ作成
    page_id = create_recording_page(
        config.notion_token,
        config.notion_database_id,
        program,
        file_upload_id,
        matched_keywords,
    )
    return page_id is not None
