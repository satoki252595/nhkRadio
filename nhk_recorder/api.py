import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from .config import Config

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

API_BASE = "https://program-api.nhk.jp/v3/papiPgDateRadio"


@dataclass
class Program:
    id: str
    service: str
    title: str
    subtitle: str
    content: str
    start_time: datetime
    end_time: datetime
    # シリーズ情報 (v3 APIのidentifierGroup由来)
    series_id: str = ""
    series_name: str = ""
    episode_name: str = ""
    genre: list[str] = field(default_factory=list)
    # 視聴エリア (JP13=関東, JP27=関西, NHKは "NHK"固定)
    area: str = ""

    @property
    def duration(self) -> int:
        return int((self.end_time - self.start_time).total_seconds())


def fetch_programs(config: Config, date: str) -> list[Program]:
    """指定日の全サービスの番組を取得する (NHK API v3)。

    Args:
        config: 設定
        date: 日付 (YYYY-MM-DD形式)

    Returns:
        番組リスト
    """
    programs: list[Program] = []

    for service in config.services:
        params = {
            "service": service,
            "area": config.area,
            "date": date,
            "key": config.nhk_api_key,
        }
        try:
            resp = httpx.get(API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # v3レスポンス: {service: {publication: [...]}}
            service_data = data.get(service, {})
            publications = service_data.get("publication", [])

            for item in publications:
                try:
                    ident = item.get("identifierGroup", {})
                    genres = [g.get("name1", "") for g in ident.get("genre", []) if g.get("name1")]
                    program = Program(
                        id=item.get("id", ""),
                        service=service,
                        title=item.get("name", ""),
                        subtitle=ident.get("radioEpisodeName", ""),
                        content=item.get("description", ""),
                        start_time=datetime.fromisoformat(item["startDate"]),
                        end_time=datetime.fromisoformat(item["endDate"]),
                        series_id=ident.get("radioSeriesId", ""),
                        series_name=ident.get("radioSeriesName", ""),
                        episode_name=ident.get("radioEpisodeName", ""),
                        genre=genres,
                        area="NHK",  # NHKは全国共通
                    )
                    programs.append(program)
                except (KeyError, ValueError) as e:
                    logger.warning("番組データのパースに失敗: %s - %s", item.get("id", "?"), e)

            logger.info("%s: %d件の番組を取得", service, len(publications))

        except httpx.HTTPStatusError as e:
            logger.error("API HTTPエラー (%s): %s", service, e.response.status_code)
        except httpx.RequestError as e:
            logger.error("APIリクエストエラー (%s): %s", service, e)

    return programs
