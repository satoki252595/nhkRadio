import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    nhk_api_key: str
    area: str = "270"
    services: list[str] = field(default_factory=lambda: ["r1", "r3"])
    keywords: list[str] = field(default_factory=lambda: ["落語", "らくご", "英語"])
    output_dir: Path = Path("./recordings")
    log_level: str = "INFO"
    ffmpeg_path: str = "ffmpeg"
    # Notion連携
    notion_token: str = ""
    notion_database_id: str = ""


def _load_env(env_path: Path) -> None:
    """簡易.envローダー。python-dotenvなしで.envを読み込む。"""
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)


def load_config(config_path: str | None = None) -> Config:
    # .envファイルから環境変数をロード
    project_root = Path(__file__).parent.parent
    _load_env(project_root / ".env")

    # config.yamlがあればファイルから読み込み、なければ環境変数のみで構成
    if config_path is None:
        config_path = os.environ.get(
            "NHK_RECORDER_CONFIG",
            str(project_root / "config.yaml"),
        )

    path = Path(config_path)
    data: dict = {}

    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    # 環境変数でオーバーライド（.env含む）
    nhk_api_key = os.environ.get("NHK_API_KEY", data.get("nhk_api_key", ""))
    notion_token = os.environ.get("NOTION_TOKEN", data.get("notion_token", ""))
    notion_database_id = os.environ.get("NOTION_DATABASE_ID", data.get("notion_database_id", ""))

    if not nhk_api_key or nhk_api_key == "YOUR_API_KEY_HERE":
        raise ValueError(
            "NHK APIキーが未設定です。\n"
            "config.yaml の nhk_api_key または環境変数 NHK_API_KEY を設定してください"
        )

    config = Config(
        nhk_api_key=nhk_api_key,
        area=data.get("area", os.environ.get("NHK_AREA", "270")),
        services=data.get("services", ["r1", "r3"]),
        keywords=data.get("keywords", ["落語", "らくご", "英語"]),
        output_dir=Path(data.get("output_dir", "./recordings")),
        log_level=data.get("log_level", os.environ.get("LOG_LEVEL", "INFO")),
        ffmpeg_path=data.get("ffmpeg_path", "ffmpeg"),
        notion_token=notion_token,
        notion_database_id=notion_database_id,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    return config
