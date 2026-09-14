import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import polars as pl
import requests

from .config import KESKKONNAAGENTUURI_SOURCES, DATA_DIR, METADATA_DIR, DataSourceConfig

logger = logging.getLogger(__name__)

class DataDownloader:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()

    def compute_checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def get_metadata_path(self, source_name: str) -> Path:
        return METADATA_DIR / f"{source_name}.json"

    def load_metadata(self, source_name: str) -> dict:
        path = self.get_metadata_path(source_name)
        if path.exists():
            return json.loads(path.read_text())
        return {"checksum": None, "timestamp": None, "version": None}

    def save_metadata(self, source_name: str, metadata: dict) -> None:
        path = self.get_metadata_path(source_name)
        path.write_text(json.dumps(metadata, indent=2, default=str))

    def download(self, source: DataSourceConfig) -> Optional[bytes]:
        try:
            logger.info(f"Downloading {source.name} from {source.url}")
            response = self.session.get(source.url, timeout=self.timeout)
            response.raise_for_status()
            logger.info(f"Downloaded {source.name}: {len(response.content)} bytes")
            return response.content
        except requests.RequestException as e:
            logger.error(f"Failed to download {source.name}: {e}")
            return None

    def process_and_save(self, source_name: str, data: bytes) -> Optional[Path]:
        source = KESKKONNAAGENTUURI_SOURCES.get(source_name)
        if not source:
            logger.error(f"Unknown source: {source_name}")
            return None

        checksum = self.compute_checksum(data)
        metadata = self.load_metadata(source_name)

        if metadata.get("checksum") == checksum:
            logger.info(f"{source_name} unchanged (same checksum)")
            return None

        DATA_DIR.mkdir(exist_ok=True)
        parquet_path = DATA_DIR / f"{source_name}.parquet"

        try:
            if source.format == "json":
                df = self._process_json(data, source_name)
            elif source.format == "xml":
                df = self._process_xml(data, source_name)
            else:
                logger.error(f"Unknown format: {source.format}")
                return None

            df.write_parquet(parquet_path)
            logger.info(f"Saved {source_name} to {parquet_path}")

            new_metadata = {
                "checksum": checksum,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "1.0",
                "rows": len(df) if hasattr(df, '__len__') else 0,
            }
            self.save_metadata(source_name, new_metadata)

            return parquet_path
        except Exception as e:
            logger.error(f"Failed to process {source_name}: {e}")
            return None

    def _process_json(self, data: bytes, source_name: str) -> pl.DataFrame:
        text = data.decode('utf-8')
        records = json.loads(text)

        if isinstance(records, dict):
            records = [records]
        elif not isinstance(records, list):
            logger.warning(f"Unexpected JSON structure for {source_name}")
            records = [records]

        df = pl.DataFrame(records)
        df = df.with_columns([
            pl.lit(datetime.now(timezone.utc)).alias("downloaded_at"),
        ])
        return df

    def _process_xml(self, data: bytes, source_name: str) -> pl.DataFrame:
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(data)
            records = []

            for elem in root.findall('.//row'):
                record = {}
                for child in elem:
                    record[child.tag] = child.text
                records.append(record)

            if not records:
                logger.warning(f"No records found in XML for {source_name}")
                records = [{"raw_data": data.decode('utf-8', errors='ignore')}]

            df = pl.DataFrame(records)
            df = df.with_columns([
                pl.lit(datetime.now(timezone.utc)).alias("downloaded_at"),
            ])
            return df
        except Exception as e:
            logger.error(f"Failed to parse XML for {source_name}: {e}")
            raise

    def download_all_sources(self) -> dict[str, Path]:
        results = {}
        for source_name, source_config in KESKKONNAAGENTUURI_SOURCES.items():
            data = self.download(source_config)
            if data:
                path = self.process_and_save(source_name, data)
                if path:
                    results[source_name] = path
        return results
