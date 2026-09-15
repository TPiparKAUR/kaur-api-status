"""Append-only JSONL check log, partitioned by month.

JSONL rather than a database or Parquet, deliberately: it is text, so git
delta-compresses it and a diff is readable; it is append-only, so concurrent
runs cannot corrupt earlier history; and it needs no tooling to inspect.

Volume is small. Twenty endpoints checked hourly is roughly 175k lines and
about 35 MB per year, which git handles comfortably.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

LOG_DIR = Path("logs")


def _month_path(when: datetime) -> Path:
    return LOG_DIR / f"{when:%Y-%m}.jsonl"


def append(records: list[dict[str, Any]]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _month_path(datetime.now(UTC))
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def month_end(path: Path) -> datetime | None:
    """The instant just after the last record a ``YYYY-MM.jsonl`` file can hold.

    Public (not just for ``read_all``'s own skip-ahead): ``retention.py`` uses
    the same instant to decide whether a month is over and safe to roll up.
    """
    try:
        year, month = (int(part) for part in path.stem.split("-"))
        return datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=UTC)
    except ValueError:
        return None


def read_all(since: datetime | None = None) -> Iterator[dict[str, Any]]:
    """Yield logged records, oldest month first, skipping corrupt lines.

    With ``since`` set, whole month files that end before it are skipped without
    being opened. That is what keeps reading cheap as the log grows: the file
    name already says which month it holds, so there is no reason to parse a
    year of history to answer a question about the last 30 days.

    Lines are streamed rather than read into memory, because a month of checks
    at this cadence is on the order of 10 MB and there is no need to hold it.
    """
    if not LOG_DIR.exists():
        return
    for path in sorted(LOG_DIR.glob("*.jsonl")):
        if since is not None:
            end = month_end(path)
            if end is not None and end <= since:
                continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
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
    """Parse a log timestamp, always timezone-aware.

    A naive value can reach the log through a hand edit, a union-merge artefact
    or a foreign writer. Returning it naive would make every later comparison
    against an aware 'now' raise TypeError and take down report generation and
    notifications, so naive input is read as UTC, which is what the log stores.
    """
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def window_start(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
