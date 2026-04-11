import re
from pathlib import Path

from .api import Program


def make_output_path(output_dir: Path, program: Program) -> Path:
    """録音ファイルのパスを生成する。

    ファイル名例: 20260410_0900_r1_NHK_真打ち競演.m4a
                 20260410_1400_radiko-TBS_JP13_CITY_CHILL_CLUB.m4a
    """
    safe_title = re.sub(r'[\\/*?:"<>|\s]+', "_", program.title)[:50].rstrip("_")
    safe_service = re.sub(r'[\\/*?:"<>|\s]+', "-", program.service)
    area = getattr(program, "area", "") or "unknown"
    safe_area = re.sub(r'[\\/*?:"<>|\s]+', "-", area)
    ts = program.start_time.strftime("%Y%m%d_%H%M")
    return output_dir / f"{ts}_{safe_service}_{safe_area}_{safe_title}.m4a"
