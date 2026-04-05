import logging
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

CONFIG_URL = "https://www.nhk.or.jp/radio/config/config_web.xml"

# 大阪のフォールバックURL
FALLBACK_URLS = {
    "r1": "https://simul.drdi.st.nhk/live/12/joined/master.m3u8",
    "r3": "https://simul.drdi.st.nhk/live/13/joined/master.m3u8",  # FM
}

# APIサービスID → XMLタグ名の対応
SERVICE_TO_TAG = {
    "r1": "r1hls",
    "r3": "fmhls",  # v3 APIではFMはr3、XMLではfmhls
}


def get_stream_urls(area: str = "270") -> dict[str, str]:
    """NHKのconfig_web.xmlからストリームURLを取得する。"""
    try:
        resp = httpx.get(CONFIG_URL, timeout=30)
        resp.raise_for_status()
        return _parse_config_xml(resp.text, area)
    except Exception as e:
        logger.warning("config_web.xmlの取得に失敗、フォールバックURLを使用: %s", e)
        return FALLBACK_URLS.copy()


def _parse_config_xml(xml_text: str, area: str) -> dict[str, str]:
    """config_web.xmlをパースしてストリームURLを抽出する。"""
    root = ET.fromstring(xml_text)
    urls: dict[str, str] = {}

    for data_elem in root.iter("data"):
        areakey = data_elem.findtext("areakey", "").strip()
        if areakey != area:
            continue

        for service_id, tag_name in SERVICE_TO_TAG.items():
            url = data_elem.findtext(tag_name, "").strip()
            if url:
                urls[service_id] = url

        if urls:
            logger.info("ストリームURL取得完了 (area=%s): %s", area, list(urls.keys()))
            return urls

    logger.warning("エリア %s のURLが見つかりません。フォールバックURLを使用", area)
    return FALLBACK_URLS.copy()
