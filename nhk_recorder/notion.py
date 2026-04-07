import logging
import math
from pathlib import Path

import httpx

from .api import Program
from .config import Config

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
PART_SIZE = 10 * 1024 * 1024  # 10MB
SMALL_FILE_LIMIT = 20 * 1024 * 1024  # 20MB


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
    """20MB以下のファイルをsingleモードでアップロード。"""
    # Step 1: Create file upload
    resp = httpx.post(
        f"{NOTION_API_BASE}/file_uploads",
        headers=_json_headers(token),
        json={"filename": filename, "content_type": content_type},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error("ファイルアップロード作成失敗: %s %s", resp.status_code, resp.text)
        return None

    upload_data = resp.json()
    upload_id = upload_data["id"]
    upload_url = upload_data.get("upload_url", f"{NOTION_API_BASE}/file_uploads/{upload_id}/send")

    # Step 2: Send file
    with open(file_path, "rb") as f:
        resp = httpx.post(
            upload_url,
            headers=_headers(token),
            files={"file": (filename, f, content_type)},
            timeout=300,
        )

    if resp.status_code != 200:
        logger.error("ファイル送信失敗: %s %s", resp.status_code, resp.text)
        return None

    result = resp.json()
    if result.get("status") == "uploaded":
        logger.info("ファイルアップロード完了: %s (%s)", filename, upload_id)
        return upload_id

    logger.error("アップロードステータス異常: %s", result.get("status"))
    return None


def _upload_multipart(
    token: str, file_path: Path, filename: str, content_type: str, file_size: int
) -> str | None:
    """20MB超のファイルをmulti_partモードでアップロード。"""
    number_of_parts = math.ceil(file_size / PART_SIZE)

    # Step 1: Create multi-part upload
    resp = httpx.post(
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
    if resp.status_code != 200:
        logger.error("マルチパートアップロード作成失敗: %s %s", resp.status_code, resp.text)
        return None

    upload_data = resp.json()
    upload_id = upload_data["id"]

    # Step 2: Send parts
    with open(file_path, "rb") as f:
        for part_num in range(1, number_of_parts + 1):
            chunk = f.read(PART_SIZE)
            resp = httpx.post(
                f"{NOTION_API_BASE}/file_uploads/{upload_id}/send",
                headers=_headers(token),
                files={"file": (filename, chunk, content_type)},
                data={"part_number": str(part_num)},
                timeout=300,
            )
            if resp.status_code != 200:
                logger.error("パート%d送信失敗: %s %s", part_num, resp.status_code, resp.text)
                return None
            logger.info("パート %d/%d アップロード完了", part_num, number_of_parts)

    # Step 3: Complete upload
    complete_url = upload_data.get("complete_url", f"{NOTION_API_BASE}/file_uploads/{upload_id}/complete")
    resp = httpx.post(
        complete_url,
        headers=_json_headers(token),
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error("アップロード完了処理失敗: %s %s", resp.status_code, resp.text)
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

    resp = httpx.post(
        f"{NOTION_API_BASE}/pages",
        headers=_json_headers(token),
        json={
            "parent": {"database_id": database_id},
            "properties": properties,
            "icon": {"emoji": "📻"},
        },
        timeout=60,
    )

    if resp.status_code != 200:
        logger.error("Notionページ作成失敗: %s %s", resp.status_code, resp.text)
        return None

    page_data = resp.json()
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
