"""Roll old months of the check log into daily aggregates, and drop the raw.

Nothing downstream needs raw per-check history older than a month or so:
report.py and dashboard.py are both windowed to `analysis.WINDOW_DAYS` (31
days), so a raw record older than that is read by nothing except a human
opening the file by hand. Kept far longer than that anyway, by default (see
DEFAULT_RAW_RETENTION_DAYS) — the point of this module is not to shrink the
window, it is to stop `logs/*.jsonl` growing forever once a month is old
enough that nobody is going to want minute-by-minute detail on it anymore.

Past the cutoff, a whole month's raw file collapses into one row per
(unit, day) in `logs/daily/YYYY-MM.jsonl`: still enough to answer "was X
available on 3 March and how fast did it typically answer", not enough to
reconstruct a single run at 14:32. Nothing calls this automatically from
`check` — it runs by hand or from its own low-frequency scheduled workflow,
and is always safe to run again: a month that already has a daily file is
skipped, never re-aggregated or re-deleted.

The daily archive is not read by report.py, dashboard.py or analysis.py.
Nothing today needs history older than the 31-day window; if a future feature
wants a multi-year trend, it reads `logs/daily/*.jsonl` directly rather than
this module growing a second code path that pretends raw and aggregated rows
are interchangeable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import store

DAILY_DIR = Path("logs/daily")

# Comfortably past the 31-day window everything downstream actually reads;
# this is about not growing the raw log forever, not about the window.
DEFAULT_RAW_RETENTION_DAYS = 365


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def aggregate_month(path: Path) -> list[dict[str, Any]]:
    """One row per (id, date) summarising a raw month file.

    Fields mirror dashboard.py's own daily rollup so a reader who understands
    one understands the other: checks, ok, avail_pct, p50_ms, p95_ms.
    'unknown' records are excluded from availability the same way
    analysis.uptime excludes them — they say our own network had no
    connection, not anything about the service.
    """
    buckets: dict[tuple[str, str], dict[str, list[Any]]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            eid = record.get("id")
            stamp = store.parse_ts(record.get("ts"))
            status = record.get("status")
            if eid is None or stamp is None or status == "unknown":
                continue
            key = (str(eid), f"{stamp:%Y-%m-%d}")
            bucket = buckets.setdefault(key, {"status": [], "ms": []})
            bucket["status"].append(status)
            if status == "ok" and isinstance(record.get("ms"), int):
                bucket["ms"].append(record["ms"])

    rows: list[dict[str, Any]] = []
    for (eid, date), bucket in sorted(buckets.items()):
        statuses = bucket["status"]
        ok = sum(1 for s in statuses if s == "ok")
        rows.append(
            {
                "id": eid,
                "date": date,
                "checks": len(statuses),
                "ok": ok,
                "avail_pct": round(100.0 * ok / len(statuses), 2),
                "p50_ms": _percentile(bucket["ms"], 0.5),
                "p95_ms": _percentile(bucket["ms"], 0.95),
            }
        )
    return rows


def _daily_path(month_path: Path) -> Path:
    return DAILY_DIR / month_path.name


def rollup(
    older_than_days: int = DEFAULT_RAW_RETENTION_DAYS,
    now: datetime | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Aggregate and delete every raw month file older than the cutoff.

    Returns one summary dict per month actually processed (or, in a dry run,
    per month that *would* be). A month whose daily file already exists is
    skipped rather than redone — this is what makes running it repeatedly, or
    from a monthly schedule, safe. The current month is never a candidate:
    ``store.month_end`` places its end in the future, past any sane cutoff.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=older_than_days)
    results: list[dict[str, Any]] = []
    if not store.LOG_DIR.exists():
        return results

    for path in sorted(store.LOG_DIR.glob("*.jsonl")):
        end = store.month_end(path)
        if end is None or end > cutoff:
            continue  # too recent to touch, or a name we won't guess a month for
        target = _daily_path(path)
        if target.exists():
            continue  # already rolled up on an earlier run

        rows = aggregate_month(path)
        with path.open(encoding="utf-8") as handle:
            raw_lines = sum(1 for line in handle if line.strip())
        results.append({"month": path.stem, "raw_lines": raw_lines, "daily_rows": len(rows)})

        if dry_run:
            continue
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        body = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        target.write_text(body + "\n" if rows else "", encoding="utf-8")
        path.unlink()

    return results
