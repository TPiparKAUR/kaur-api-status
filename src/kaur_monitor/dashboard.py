"""Render the check log into the JSON the public status page reads.

The page is static: it fetches one file and draws it. Everything that needs the
log — current state, availability, daily aggregates, the outage list — is
computed here, on the runner, so the browser never sees a 200 000 line log.

Nothing is invented. Where there is no data the arrays come back empty and the
page says so, rather than drawing a plausible-looking line.
"""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import analysis, store

DATA_PATH = Path("docs/data/status.json")
SYSTEMS_PATH = Path("config/systems.toml")

# Daily aggregates are what the 30-day charts plot. One more day than that is
# read so the oldest plotted day is whole.
_CHART_DAYS = 30

_PROBLEM = ("down", "degraded")


def load_system_descriptions(path: Path = SYSTEMS_PATH) -> dict[str, str]:
    """Plain-language text per system. Missing file just means no descriptions."""
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        name: " ".join(str(body.get("description", "")).split())
        for name, body in raw.items()
        if isinstance(body, dict)
    }


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _daily(records: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """One row per calendar day (UTC): availability and response-time spread.

    Only days that actually have checks appear. A day with no data is absent
    rather than zero, because zero would read as a total outage.
    """
    buckets: dict[str, dict[str, list[Any]]] = {}
    earliest = now - timedelta(days=_CHART_DAYS)
    for record in records:
        stamp = store.parse_ts(record.get("ts"))
        if stamp is None or stamp < earliest:
            continue
        status = record.get("status")
        if status == "unknown":
            continue
        day = buckets.setdefault(f"{stamp:%Y-%m-%d}", {"status": [], "ms": []})
        day["status"].append(status)
        if status == "ok" and isinstance(record.get("ms"), int):
            day["ms"].append(record["ms"])

    rows = []
    for date in sorted(buckets):
        statuses = buckets[date]["status"]
        latencies = buckets[date]["ms"]
        ok = sum(1 for s in statuses if s == "ok")
        rows.append(
            {
                "date": date,
                "checks": len(statuses),
                "ok": ok,
                "avail_pct": round(100.0 * ok / len(statuses), 2),
                "p50_ms": _percentile(latencies, 0.5),
                "p95_ms": _percentile(latencies, 0.95),
            }
        )
    return rows


def build(entries: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(UTC)
    records = list(store.read_all(since=store.window_start(analysis.WINDOW_DAYS)))
    grouped = analysis.by_endpoint(records)
    descriptions = load_system_descriptions()

    day_ago = store.window_start(1.0)
    week_ago = store.window_start(7.0)

    endpoints: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda e: (str(e.get("system") or ""), e["id"])):
        eid = entry["id"]
        series = grouped.get(eid, [])
        latest = series[-1] if series else None
        avail_24h, checks_24h = analysis.uptime(series, day_ago)
        avail_7d, _ = analysis.uptime(series, week_ago)
        endpoints.append(
            {
                "id": eid,
                "name": entry.get("name", eid),
                "system": entry.get("system") or "Muu",
                "url": entry["url"],
                "status": (latest or {}).get("status", "unchecked"),
                "http": (latest or {}).get("http"),
                "ms": (latest or {}).get("ms"),
                "ts": (latest or {}).get("ts"),
                "detail": (latest or {}).get("detail") or "",
                "avail_24h": None if avail_24h is None else round(avail_24h, 2),
                "avail_7d": None if avail_7d is None else round(avail_7d, 2),
                "checks_24h": checks_24h,
            }
        )

    totals: dict[str, int] = {"endpoints": len(endpoints)}
    for item in endpoints:
        totals[item["status"]] = totals.get(item["status"], 0) + 1

    systems: list[dict[str, Any]] = []
    for name in sorted({e["system"] for e in endpoints}):
        members = [e for e in endpoints if e["system"] == name]
        rated = [e["avail_24h"] for e in members if e["avail_24h"] is not None]
        systems.append(
            {
                "name": name,
                "description": descriptions.get(name, ""),
                "endpoints": len(members),
                "ok": sum(1 for e in members if e["status"] == "ok"),
                "problem": sum(1 for e in members if e["status"] in _PROBLEM),
                "avail_24h": round(sum(rated) / len(rated), 2) if rated else None,
            }
        )

    by_name = {e["id"]: e for e in endpoints}
    incidents: list[dict[str, Any]] = []
    for eid, series in grouped.items():
        for incident in analysis.incidents(series):
            seconds = analysis.duration_seconds(incident, now)
            incidents.append(
                {
                    "id": eid,
                    "name": by_name.get(eid, {}).get("name", eid),
                    "system": by_name.get(eid, {}).get("system", "Muu"),
                    "start": incident["start"],
                    "end": incident["end"],
                    "duration_s": None if seconds is None else int(seconds),
                    "worst": incident["worst"],
                    "detail": (incident.get("detail") or "")[:200],
                }
            )
    incidents.sort(key=lambda i: (i["start"] or "", i["id"]), reverse=True)

    tally: dict[str, dict[str, Any]] = {}
    for incident in incidents:
        row = tally.setdefault(
            incident["id"],
            {"id": incident["id"], "name": incident["name"], "count": 0, "total_s": 0},
        )
        row["count"] += 1
        row["total_s"] += incident["duration_s"] or 0
    outages_by_endpoint = sorted(tally.values(), key=lambda r: (-r["count"], -r["total_s"]))

    overall_24h, overall_checks = analysis.uptime(records, day_ago)
    overall_7d, _ = analysis.uptime(records, week_ago)
    stamps = [s for s in (store.parse_ts(r.get("ts")) for r in records) if s is not None]

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval_minutes": 30,
        "window_days": int(analysis.WINDOW_DAYS),
        "chart_days": _CHART_DAYS,
        "first_record": min(stamps).strftime("%Y-%m-%dT%H:%M:%SZ") if stamps else None,
        "totals": totals,
        "availability": {
            "h24": None if overall_24h is None else round(overall_24h, 2),
            "d7": None if overall_7d is None else round(overall_7d, 2),
            "checks_24h": overall_checks,
        },
        "systems": systems,
        "endpoints": endpoints,
        "daily": _daily(records, now),
        "incidents": incidents[:200],
        "incident_count": len(incidents),
        "outages_by_endpoint": outages_by_endpoint[:10],
    }


def write(entries: list[dict[str, Any]], path: Path = DATA_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build(entries), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
