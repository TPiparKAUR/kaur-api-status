"""Append-only JSONL check log, partitioned by month.

JSONL rather than a database or Parquet, deliberately: it is text, so git
delta-compresses it and a diff is readable; it is append-only, so concurrent
runs cannot corrupt earlier history; and it needs no tooling to inspect.

Volume is small. Twenty endpoints checked hourly is roughly 175k lines and
about 35 MB per year, which git handles comfortably.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

LOG_DIR = Path("logs")


def _month_path(when: datetime) -> Path:
    return LOG_DIR / f"{when:%Y-%m}.jsonl"


def append(records: list[dict[str, Any]]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _month_path(datetime.now(timezone.utc))
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def read_all(since: datetime | None = None) -> Iterator[dict[str, Any]]:
    """Yield every logged record, oldest month first, skipping corrupt lines."""
    if not LOG_DIR.exists():
        return
    for path in sorted(LOG_DIR.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if since is not None:
                stamp = parse_ts(record.get("ts"))
                if stamp is None or stamp < since:
                    continue
            yield record


def parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def window_start(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
