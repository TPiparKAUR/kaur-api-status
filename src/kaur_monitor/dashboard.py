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
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from . import analysis, store

DATA_PATH = Path("docs/data/status.json")
FEED_PATH = Path("docs/data/incidents.xml")
SYSTEMS_PATH = Path("config/systems.toml")

# Same GitHub Pages URL already hardcoded in docs/index.html's footer link to
# this repository's Issues. RSS's <link> and <guid> both want an absolute
# URI, and this is the page's own published address, not a monitored
# endpoint — the "never write an endpoint URL into source" rule is about
# invented targets for the checker to call, not this project's own identity.
PAGE_URL = "https://tpiparkaur.github.io/kaur-api-status/"

# How many of the most recent incidents the feed carries. A subscriber wants
# to know what changed recently, not the full 194-and-growing history —
# that's what the page's own table is for.
_FEED_ITEMS = 50

# Daily aggregates are what the 30-day charts plot. One more day than that is
# read so the oldest plotted day is whole.
_CHART_DAYS = 30

_PROBLEM = ("down", "degraded")

# The latency chart pools every system into one line by default, which
# compares KAIA (file downloads) against PostgREST queries — different
# things with different natural response times. Split two ways rather than
# one line per system (6 systems today; a 6-colour categorical palette is a
# design task in its own right — see the dataviz skill — for a management
# audience that mainly needs "the file service" vs "the data service").
# Revisit this constant if a third genuinely different service type joins.
_KAIA_SYSTEM = "KAIA"


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


def _unit_days(series: list[dict[str, Any]], dates: list[str]) -> dict[str, list[Any]]:
    """One unit's daily checks/ok/median, aligned position-for-position to `dates`.

    Three parallel arrays rather than a list of objects: the page needs a
    30-value sparkline and a 30-cell uptime strip per unit, and at 42 units the
    object form costs several times the bytes for the same numbers in a file
    that is regenerated and committed every half hour.

    A day on which this unit was never checked is `checks = 0` and
    `p50_ms = None`, never `avail = 0` — "we did not look" and "it was down"
    must not render as the same cell.
    """
    wanted = {date: index for index, date in enumerate(dates)}
    ok = [0] * len(dates)
    checks = [0] * len(dates)
    latencies: list[list[int]] = [[] for _ in dates]
    for record in series:
        stamp = store.parse_ts(record.get("ts"))
        status = record.get("status")
        if stamp is None or status == "unknown":
            continue
        index = wanted.get(f"{stamp:%Y-%m-%d}")
        if index is None:
            continue
        checks[index] += 1
        if status == "ok":
            ok[index] += 1
            if isinstance(record.get("ms"), int):
                latencies[index].append(record["ms"])
    return {
        "checks": checks,
        "ok": ok,
        "p50_ms": [_percentile(values, 0.5) for values in latencies],
    }


def build(entries: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(UTC)
    records = list(store.read_all(since=store.window_start(analysis.WINDOW_DAYS)))
    grouped = analysis.by_endpoint(records)
    descriptions = load_system_descriptions()

    day_ago = store.window_start(1.0)
    week_ago = store.window_start(7.0)

    overall_daily = _daily(records, now)
    # The shared date axis for every per-unit array below. Only days that
    # actually carry checks appear, so a gap in the log stays a gap.
    chart_dates = [row["date"] for row in overall_daily]

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
                # A grouped unit stands for many endpoints; say how many rather
                # than letting one row quietly represent 261.
                "members": entry.get("members"),
                # Shown on the page, not just in REPORT.md: a reader comparing
                # an unverified endpoint's number against a verified one's
                # should not assume the two carry the same authority.
                "verified": bool(entry.get("verified", False)),
                # Per-day history, aligned to the top-level chart_dates. This
                # is what lets the table show a unit's 30-day uptime strip and
                # response-time sparkline in the row itself, instead of making
                # the reader hover a pooled chart to learn anything per unit.
                "days": _unit_days(series, chart_dates),
            }
        )

    totals: dict[str, int] = {"endpoints": len(endpoints)}
    totals["unverified"] = sum(1 for e in endpoints if not e["verified"])
    for item in endpoints:
        totals[item["status"]] = totals.get(item["status"], 0) + 1

    systems: list[dict[str, Any]] = []
    for name in sorted({e["system"] for e in endpoints}):
        members = [e for e in endpoints if e["system"] == name]
        # Pool the members' raw check records and run analysis.uptime over
        # them, rather than averaging each member's already-rounded avail_24h:
        # an unweighted average of percentages silently overweights a member
        # with few checks (e.g. new, or mostly 'unknown') against one with
        # many, and treats a 261-endpoint group unit as equal to a single one.
        pooled = [record for e in members for record in grouped.get(e["id"], [])]
        system_avail_24h, _ = analysis.uptime(pooled, day_ago)
        systems.append(
            {
                "name": name,
                "description": descriptions.get(name, ""),
                "endpoints": len(members),
                "ok": sum(1 for e in members if e["status"] == "ok"),
                "problem": sum(1 for e in members if e["status"] in _PROBLEM),
                "avail_24h": None if system_avail_24h is None else round(system_avail_24h, 2),
            }
        )

    by_name = {e["id"]: e for e in endpoints}
    incidents: list[dict[str, Any]] = []
    for eid, series in grouped.items():
        for incident in analysis.incidents(series):
            # An open incident on an id nobody checks any more (disabled, or
            # superseded by a grouping change) is not still running — we
            # stopped looking. Close it at the last failure observed instead
            # of showing a duration that grows forever.
            if incident["end"] is None and eid not in by_name:
                incident = {**incident, "end": incident.get("last_ts")}
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

    # The same tally, one level up: a reader thinking in business terms (a
    # manager, a product owner) asks "which service", not "which of its 261
    # tables" — EELIS's members would otherwise never surface here at all,
    # since none of them individually cracks the top 10 by endpoint.
    system_tally: dict[str, dict[str, Any]] = {}
    for incident in incidents:
        row = system_tally.setdefault(
            incident["system"], {"name": incident["system"], "count": 0, "total_s": 0}
        )
        row["count"] += 1
        row["total_s"] += incident["duration_s"] or 0
    outages_by_system = sorted(system_tally.values(), key=lambda r: (-r["total_s"], -r["count"]))

    overall_24h, overall_checks = analysis.uptime(records, day_ago)
    overall_7d, _ = analysis.uptime(records, week_ago)
    stamps = [s for s in (store.parse_ts(r.get("ts")) for r in records) if s is not None]

    # Same pooled-records approach as the per-system availability fix above:
    # partition the raw records by which group their unit belongs to, then
    # reuse _daily's own pooling rather than averaging two sets of daily rows.
    # A record whose id names no currently-known unit (e.g. one superseded by
    # a later grouping change, still inside the window) goes to neither side
    # rather than being guessed into one — the same reasoning as Hetkeseis.
    system_of = {e["id"]: e["system"] for e in endpoints}
    kaia_records = [r for r in records if system_of.get(r.get("id")) == _KAIA_SYSTEM]
    postgrest_records = [
        r for r in records if r.get("id") in system_of and system_of[r["id"]] != _KAIA_SYSTEM
    ]

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval_minutes": 30,
        "window_days": int(analysis.WINDOW_DAYS),
        "chart_days": _CHART_DAYS,
        "chart_dates": chart_dates,
        "first_record": min(stamps).strftime("%Y-%m-%dT%H:%M:%SZ") if stamps else None,
        "totals": totals,
        "availability": {
            "h24": None if overall_24h is None else round(overall_24h, 2),
            "d7": None if overall_7d is None else round(overall_7d, 2),
            "checks_24h": overall_checks,
        },
        "systems": systems,
        "endpoints": endpoints,
        "daily": overall_daily,
        # For the latency chart's two lines. Everything else (the overall
        # availability chart, the tiles) intentionally keeps reading "daily",
        # not these — only response time differs enough by service type to
        # be worth splitting.
        "daily_postgrest": _daily(postgrest_records, now),
        "daily_kaia": _daily(kaia_records, now),
        "incidents": incidents[:200],
        "incident_count": len(incidents),
        # Summed over every incident, not just the 200 sent to the page: a
        # management tile reading "how much downtime" must not quietly become
        # "how much downtime among the 200 most recent" once the list is
        # truncated.
        "outage_total_s": sum(i["duration_s"] or 0 for i in incidents),
        "outages_by_endpoint": outages_by_endpoint[:10],
        "outages_by_system": outages_by_system,
    }


def _feed_item(incident: dict[str, Any], now: datetime) -> str:
    """One RSS <item> for one incident, open or closed.

    guid is the incident's own id and start time: stable across regenerations
    of this file (the same incident always gets the same guid), and distinct
    from every other incident on the same endpoint, so a reader's feed client
    treats a still-open incident as the same item (title updates in place)
    rather than a new one each half hour.
    """
    ongoing = incident["end"] is None
    title = f"{incident['name']}: {'ei vasta' if incident['worst'] == 'down' else 'häiritud'}"
    if ongoing:
        title += " (kestab)"
    started = store.parse_ts(incident["start"])
    pub_date = format_datetime(started) if started else format_datetime(now)
    duration = "kestab endiselt" if ongoing else duration_words(incident["duration_s"])
    # CDATA, not escape(): a 429 response's error body is itself HTML
    # (Cloudflare's block page), truncated into `detail` verbatim — an
    # escaped string would still be readable, but CDATA is what an RSS
    # description field is for and avoids double-escaping if a reader's
    # client renders it as HTML.
    body = (
        f"Teenus: {incident['system']}\n"
        f"Algus: {incident['start']} (UTC)\n"
        f"Kestus: {duration}\n"
        f"Põhjus: {incident['detail'] or '-'}"
    )
    # `detail` is a truncated snippet of whatever the failing service sent
    # back — for a 429 that is Cloudflare's own HTML block page. A CDATA
    # section is not allowed to contain the literal "]]>" anywhere inside it;
    # the standard escape is to close the section, emit an escaped ">", and
    # reopen a new one, which is invisible to any reader but keeps the XML
    # well-formed no matter what a service's error body happens to contain.
    body = body.replace("]]>", "]]]]><![CDATA[>")
    guid = f"{incident['id']}-{incident['start']}"
    return (
        "<item>"
        f"<title>{escape(title)}</title>"
        f"<link>{escape(PAGE_URL)}#row-{escape(incident['id'])}</link>"
        f'<guid isPermaLink="false">{escape(guid)}</guid>'
        f"<pubDate>{pub_date}</pubDate>"
        f"<category>{escape(incident['system'])}</category>"
        f"<description><![CDATA[{body}]]></description>"
        "</item>"
    )


def duration_words(seconds: int | None) -> str:
    """'2 h 5 min' etc. — the same wording the page's own duration() uses in
    JS, kept here only for the feed, which has no JS runtime to format in."""
    if seconds is None:
        return "-"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} p {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return f"{sec} s"


def render_incidents_feed(data: dict[str, Any]) -> str:
    """RSS 2.0 for the most recent incidents — the machine-readable channel
    for "notify me when something changes" rather than "show me a page"."""
    now = datetime.now(UTC)
    items = "".join(_feed_item(i, now) for i in data["incidents"][:_FEED_ITEMS])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n<channel>'
        "<title>Keskkonnaagentuuri API-de katkestused</title>"
        f"<link>{escape(PAGE_URL)}</link>"
        "<description>Keskkonnaagentuuri avalike andmeteenuste katkestused, "
        "uuemad eespool. Genereeritud automaatsest seirest iga kontrollitsükli "
        "järel.</description>"
        "<language>et</language>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        f"{items}"
        "</channel></rss>\n"
    )


def write(entries: list[dict[str, Any]], path: Path = DATA_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build(entries)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEED_PATH.write_text(render_incidents_feed(data), encoding="utf-8")
    return path
