"""Turning check records into the things people ask about: outages and uptime.

One implementation, used by both the Markdown report and the dashboard data.
If each rendered its own idea of when an outage started, the two would disagree
in front of the reader eventually.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import store

# Reading the whole log costs time that grows without limit; every caller wants
# a window, and one day past the widest reported window keeps that window whole.
WINDOW_DAYS = 31.0


# 'unknown' is not a severity, it is an absence of evidence, so it is set aside
# when picking the group's status and only wins when it is all there is.
_WORST_FIRST = ("down", "degraded", "ok")
_NAMED_FAILURES = 5


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def collapse_groups(
    records: list[dict[str, Any]], group_of: dict[str, str]
) -> list[dict[str, Any]]:
    """Replace each group's member records with one record standing for the group.

    Every member is still checked; only the recording is collapsed. One failing
    member makes the group fail — that is the point, since a reader wants to
    know EELIS is not fully answering, not to scan 261 rows to find out.

    The record names the members that failed, so the aggregate never hides
    which one it was, and keeps the counts so availability stays meaningful.
    """
    if not group_of:
        return records

    kept: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        group_id = group_of.get(str(record.get("id")))
        if group_id is None:
            kept.append(record)
        else:
            grouped.setdefault(group_id, []).append(record)

    for group_id, members in sorted(grouped.items()):
        statuses = {str(m.get("status")) for m in members}
        if statuses == {"unknown"}:
            status = "unknown"
        else:
            evidence = statuses - {"unknown"}
            status = next((s for s in _WORST_FIRST if s in evidence), "ok")

        failed = [m for m in members if m.get("status") not in ("ok", "unknown")]
        detail = ""
        if failed:
            named = ", ".join(
                f"{m.get('id')} ({(m.get('detail') or m.get('status') or '')[:60]})"
                for m in failed[:_NAMED_FAILURES]
            )
            more = (
                f" ja veel {len(failed) - _NAMED_FAILURES}" if len(failed) > _NAMED_FAILURES else ""
            )
            detail = f"{len(failed)}/{len(members)} ei vasta: {named}{more}"

        certs = [m["cert_days"] for m in members if isinstance(m.get("cert_days"), int)]
        kept.append(
            {
                "ts": members[0].get("ts"),
                "id": group_id,
                "status": status,
                "stage": "group",
                "http": None,
                "ms": _median([m["ms"] for m in members if isinstance(m.get("ms"), int)]),
                "bytes": None,
                "sha256": None,
                "cert_days": min(certs) if certs else None,
                "age_s": None,
                "detail": detail[:300],
                "members": len(members),
                "ok": sum(1 for m in members if m.get("status") == "ok"),
            }
        )
    return kept


def by_endpoint(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group records per endpoint, each series oldest first."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record.get("id", "?"), []).append(record)
    for series in grouped.values():
        series.sort(key=lambda r: r.get("ts") or "")
    return grouped


def incidents(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Contiguous runs of non-ok status.

    'unknown' is treated as a gap rather than an outage: it means our own check
    could not reach the network, which says nothing about the service.
    """
    found: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for record in series:
        status = record.get("status")
        if status == "unknown":
            continue
        if status == "ok":
            if current is not None:
                current["end"] = record.get("ts")
                found.append(current)
                current = None
            continue
        if current is None:
            current = {
                "start": record.get("ts"),
                "end": None,
                "worst": status,
                "detail": record.get("detail") or "",
                "checks": 0,
            }
        if status == "down":
            current["worst"] = "down"
            if record.get("detail"):
                current["detail"] = record["detail"]
        current["checks"] += 1

    if current is not None:
        found.append(current)
    return found


def uptime(series: list[dict[str, Any]], since: datetime) -> tuple[float | None, int]:
    """Share of checks that succeeded, and how many were counted.

    Records in the 'unknown' state are left out of both: they say our own
    checker had no network, which is not evidence about the service. A record
    whose timestamp will not parse is dropped rather than counted, matching
    what store.read_all does, so the two paths cannot disagree.
    """
    considered = []
    for record in series:
        if record.get("status") == "unknown":
            continue
        stamp = store.parse_ts(record.get("ts"))
        if stamp is None or stamp < since:
            continue
        considered.append(record)
    if not considered:
        return None, 0
    ok = sum(1 for r in considered if r.get("status") == "ok")
    return 100.0 * ok / len(considered), len(considered)


def duration_seconds(incident: dict[str, Any], now: datetime) -> float | None:
    """How long an outage lasted, or has lasted so far if it is still open."""
    start = store.parse_ts(incident.get("start"))
    if start is None:
        return None
    end = store.parse_ts(incident.get("end")) or now
    return max(0.0, (end - start).total_seconds())
