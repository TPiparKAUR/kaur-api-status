import json
from pathlib import Path
from src.kaur.downloader import DataDownloader
from src.kaur.config import METADATA_DIR

def test_checksum():
    downloader = DataDownloader()
    data = b"test data"
    checksum = downloader.compute_checksum(data)
    assert len(checksum) == 64
    assert checksum == downloader.compute_checksum(data)

def test_metadata_paths():
    downloader = DataDownloader()
    path = downloader.get_metadata_path("test_source")
    assert "test_source.json" in str(path)

def test_json_processing():
    downloader = DataDownloader()
    json_data = json.dumps([
        {"name": "Test1", "value": 10},
        {"name": "Test2", "value": 20},
    ]).encode('utf-8')

    try:
        df = downloader._process_json(json_data, "test")
        assert len(df) == 2
        assert "downloaded_at" in df.columns
    except ImportError:
        pass
