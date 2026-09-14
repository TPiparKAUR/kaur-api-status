from dataclasses import dataclass
from typing import Optional
from pathlib import Path

@dataclass
class DataSourceConfig:
    name: str
    url: str
    format: str = "json"
    incremental: bool = True
    auth_required: bool = False
    description: str = ""

KESKKONNAAGENTUURI_SOURCES: dict[str, DataSourceConfig] = {
    "kese": DataSourceConfig(
        name="KESE",
        url="https://eelis.ee/eelis/middleware/xml/public",
        description="Keskkonnateabe süsteemi avalik kuvand"
    ),
    "ilm": DataSourceConfig(
        name="Ilmateade",
        url="https://www.ilmateenistus.ee/xml/observations.php",
        format="xml",
        description="Eesti Meteoroloogia ja Hüdroökoloogia Instituut - Ilmaandmed"
    ),
    "emo": DataSourceConfig(
        name="EMO",
        url="https://www.ilmateenistus.ee/weather/rest/",
        format="json",
        description="EMO - Meteoroloogilised andmed"
    ),
}

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
METADATA_DIR = Path("data/.metadata")
METADATA_DIR.mkdir(exist_ok=True)
