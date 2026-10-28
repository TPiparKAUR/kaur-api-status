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
from itertools import pairwise
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

_INCIDENT_KEYS = ("id", "name", "system", "start", "end", "duration_s", "worst", "detail")

# Events sent to the page. Each carries its member incidents, so this is the
# cap that keeps status.json small rather than a judgement about relevance.
_EVENTS_SHOWN = 100

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


_NOMINAL_INTERVAL_MIN = 30
# Records written by one run are seconds to a few minutes apart; a longer silence
# starts a new run. Well below the nominal interval, so two runs never merge.
_RUN_GAP = timedelta(minutes=10)
_CADENCE_DAYS = 7.0


def _cadence(records: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """How often the checks actually ran, measured from the log itself.

    GitHub treats a scheduled workflow as best effort and may delay or drop
    runs, so the nominal interval is a wish, not a fact. Run starts are
    recovered from record timestamps (a run is a cluster of records), and the
    gaps between them are summarised. None when there are too few runs to say
    anything — the page then states the nominal interval only, as before.
    """
    since = now - timedelta(days=_CADENCE_DAYS)
    stamps: list[datetime] = []
    for record in records:
        try:
            moment = datetime.fromisoformat(str(record["ts"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if moment >= since:
            stamps.append(moment)
    stamps.sort()
    starts: list[datetime] = []
    previous: datetime | None = None
    for moment in stamps:
        if previous is None or moment - previous > _RUN_GAP:
            starts.append(moment)
        previous = moment
    if len(starts) < 4:
        return None
    gaps = sorted((b - a).total_seconds() / 60 for a, b in pairwise(starts))
    return {
        "nominal_minutes": _NOMINAL_INTERVAL_MIN,
        "days": _CADENCE_DAYS,
        "runs": len(starts),
        # What the schedule promises over the same window, so the page can say
        # "42 of 336" — received against expected, the way WMO's WDQMS reports
        # observation availability — rather than leave the reader to divide.
        "expected_runs": round(_CADENCE_DAYS * 24 * 60 / _NOMINAL_INTERVAL_MIN),
        "median_gap_minutes": round(gaps[len(gaps) // 2]),
        "p90_gap_minutes": round(gaps[min(len(gaps) - 1, int(0.9 * len(gaps)))]),
        "max_gap_minutes": round(gaps[-1]),
    }


# Checked in order; the first prefix or fragment found in a failure's detail
# names its cause. The page turns each key into Estonian words — the raw
# detail (for a 429, Cloudflare's own HTML) stays one click away, but it is
# not what a reader deciding "is this real" should have to parse first.
_CAUSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rate_limited", ("http 429",)),
    ("not_dialled", ("not dialled",)),
    ("dns", ("dns lookup failed",)),
    ("no_response", ("connection failed",)),
    ("server_error", ("http 5",)),
    ("client_error", ("http 4",)),
    ("service_exception", ("ogc service exception",)),
    ("stale", ("stale data", "freshness_regex")),
    ("unreadable", ("invalid json", "invalid xml", "empty response body", "content-type")),
    ("check_error", ("check aborted", "unexpected error", "unparseable url")),
)


# An endpoint skipped by the circuit breaker failed because its host had just
# stopped answering other endpoints in the same run: one outage, not two
# events side by side. The members keep their own cause.
_EVENT_CAUSE = {"not_dialled": "no_response"}


def classify_cause(detail: str) -> str:
    """One of the _CAUSES keys, or 'other'.

    A group record's detail reads "7/7 ei vasta: member (member's detail), …";
    the group failed for whatever its first named member failed for, so the
    text inside the first parenthesis is what gets classified.
    """
    text = (detail or "").strip().lower()
    if " ei vasta: " in text and "(" in text:
        text = text.split("(", 1)[1]
    for cause, fragments in _CAUSES:
        if text.startswith(fragments):
            return cause
    return "other"


def _union_seconds(spans: list[tuple[datetime, datetime]]) -> int:
    """Calendar time covered by at least one span. Two endpoints down for the
    same hour is one hour here, which is what "how long was the service
    disturbed" means — summing them would say two."""
    covered = 0.0
    reach: datetime | None = None
    for begin, finish in sorted(spans):
        if reach is None or begin > reach:
            covered += (finish - begin).total_seconds()
            reach = finish
        elif finish > reach:
            covered += (finish - reach).total_seconds()
            reach = finish
    return int(covered)


def _spans(
    incidents: list[dict[str, Any]], now: datetime
) -> dict[str, list[tuple[datetime, datetime]]]:
    """Each incident's time on the axis three ways: observed failing (first to
    last failing check), as reported (first failing to first ok check), and
    the widest it can have been (last ok before, or the window's start, to
    first ok after)."""
    out: dict[str, list[tuple[datetime, datetime]]] = {"min": [], "point": [], "max": []}
    for incident in incidents:
        start = store.parse_ts(incident["start"])
        if start is None:
            continue
        end = store.parse_ts(incident["end"]) or now
        last = store.parse_ts(incident.get("last_ts")) or start
        after = store.parse_ts(incident.get("after_bound")) or start
        out["min"].append((start, max(start, last)))
        out["point"].append((start, end))
        out["max"].append((after, end))
    return out


# Only what differs per member: name, service and verified flag are already in
# `endpoints` under the same id, and members of one event share a cause, so
# the event carries one sample detail. Repeating those per member — a
# 200-character Cloudflare page each time — doubled a file committed every run.
_EVENT_MEMBER_KEYS = ("id", "end", "min_s", "max_s")


def _events(incidents: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Incidents with the same cause that began in the same check run.

    One host stopping answering, or one rate limit switching on, opens a
    separate incident on every endpoint behind it, and a log of those reads as
    fifteen problems when it is one. Grouping says only what was observed —
    same run, same cause — not that they share a root cause.
    """

    def key(incident: dict[str, Any]) -> str:
        return _EVENT_CAUSE.get(incident["cause"], incident["cause"])

    ordered = sorted(
        (i for i in incidents if store.parse_ts(i["start"]) is not None),
        key=lambda i: (key(i), i["start"]),
    )
    clusters: list[list[dict[str, Any]]] = []
    anchor: datetime | None = None
    for incident in ordered:
        start = store.parse_ts(incident["start"])
        assert start is not None
        if (
            clusters
            and key(clusters[-1][0]) == key(incident)
            and anchor is not None
            and start - anchor <= _RUN_GAP
        ):
            clusters[-1].append(incident)
        else:
            clusters.append([incident])
            anchor = start

    events = []
    for members in clusters:
        afters = [m["after"] for m in members if m.get("after") is not None]
        open_ = any(m["end"] is None for m in members)
        start = min(m["start"] for m in members)
        end = None if open_ else max(m["end"] for m in members)
        spans = _spans(members, now)
        lower = _union_seconds(spans["min"])
        events.append(
            {
                "start": start,
                # The event began after the earliest of its members' last ok
                # checks; unknown if any member opened the log already failing.
                "after": min(afters) if len(afters) == len(members) else None,
                "end": end,
                "last_ts": max(m.get("last_ts") or m["start"] for m in members),
                "duration_s": _union_seconds(spans["point"]),
                "min_s": lower,
                "max_s": max(lower, _union_seconds(spans["max"])),
                "cause": key(members[0]),
                "detail": members[0]["detail"],
                "count": len(members),
                "verified": sum(1 for m in members if m["verified"]),
                "systems": sorted({m["system"] for m in members}),
                "members": [
                    {k: m[k] for k in _EVENT_MEMBER_KEYS}
                    for m in sorted(members, key=lambda m: (m["system"], m["name"], m["id"]))
                ],
            }
        )
    events.sort(key=lambda e: (e["start"], e["cause"]), reverse=True)
    return events


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
    since = store.window_start(analysis.WINDOW_DAYS)
    records = list(store.read_all(since=since))
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
        ok_24h, checks_24h = analysis.uptime_counts(series, day_ago)
        ok_7d, checks_7d = analysis.uptime_counts(series, week_ago)
        avail_24h = 100.0 * ok_24h / checks_24h if checks_24h else None
        avail_7d = 100.0 * ok_7d / checks_7d if checks_7d else None
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
                # The counts behind both percentages: 50 % of 6 checks and
                # 50 % of 600 are different claims, and the page shows which.
                "checks_24h": checks_24h,
                "ok_24h": ok_24h,
                "checks_7d": checks_7d,
                "ok_7d": ok_7d,
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
        system_ok_24h, system_checks_24h = analysis.uptime_counts(pooled, day_ago)
        systems.append(
            {
                "name": name,
                "description": descriptions.get(name, ""),
                "endpoints": len(members),
                "ok": sum(1 for e in members if e["status"] == "ok"),
                "problem": sum(1 for e in members if e["status"] in _PROBLEM),
                "avail_24h": (
                    round(100.0 * system_ok_24h / system_checks_24h, 2)
                    if system_checks_24h
                    else None
                ),
                "ok_24h": system_ok_24h,
                "checks_24h": system_checks_24h,
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
            # A series that opens failing has no ok check before it in the
            # window, but the window's own start still bounds it: nothing on
            # this page claims to know about time before that. Kept separate
            # from 'after' so the page can still say "since the log began".
            after_bound = incident.get("after") or since.strftime("%Y-%m-%dT%H:%M:%SZ")
            lower, upper = analysis.duration_bounds({**incident, "after": after_bound}, now)
            incidents.append(
                {
                    "id": eid,
                    "name": by_name.get(eid, {}).get("name", eid),
                    "system": by_name.get(eid, {}).get("system", "Muu"),
                    "start": incident["start"],
                    "after": incident.get("after"),
                    "after_bound": after_bound,
                    "end": incident["end"],
                    "last_ts": incident.get("last_ts"),
                    "duration_s": None if seconds is None else int(seconds),
                    "min_s": None if lower is None else int(lower),
                    "max_s": None if upper is None else int(upper),
                    "worst": incident["worst"],
                    "cause": classify_cause(incident.get("detail") or ""),
                    # An id no longer in the inventory has nobody vouching for
                    # its URL either, so it counts as unverified.
                    "verified": bool(by_name.get(eid, {}).get("verified", False)),
                    "detail": (incident.get("detail") or "")[:200],
                }
            )
    incidents.sort(key=lambda i: (i["start"] or "", i["id"]), reverse=True)

    # One endpoint's incidents never overlap, so summing them is its calendar
    # downtime; the bounds travel with it because with checks hours apart the
    # point figure alone claims a precision the log does not have.
    tally: dict[str, dict[str, Any]] = {}
    for incident in incidents:
        row = tally.setdefault(
            incident["id"],
            {
                "id": incident["id"],
                "name": incident["name"],
                "count": 0,
                "total_s": 0,
                "total_min_s": 0,
                "total_max_s": 0,
            },
        )
        row["count"] += 1
        row["total_s"] += incident["duration_s"] or 0
        row["total_min_s"] += incident["min_s"] or 0
        row["total_max_s"] += incident["max_s"] or 0
    outages_by_endpoint = sorted(tally.values(), key=lambda r: (-r["count"], -r["total_s"]))

    # The same incidents, one level up: a reader thinking in business terms (a
    # manager, a product owner) asks "which service", not "which of its 261
    # tables" — EELIS's members would otherwise never surface here at all,
    # since none of them individually cracks the top 10 by endpoint. Time is
    # the union across the service's endpoints, not their sum: three
    # endpoints down for the same hour disturbed the service for one hour.
    by_system: dict[str, list[dict[str, Any]]] = {}
    for incident in incidents:
        by_system.setdefault(incident["system"], []).append(incident)
    outages_by_system: list[dict[str, Any]] = []
    for name, members in by_system.items():
        spans = _spans(members, now)
        lower = _union_seconds(spans["min"])
        outages_by_system.append(
            {
                "name": name,
                "count": len(members),
                "affected_s": _union_seconds(spans["point"]),
                "affected_min_s": lower,
                "affected_max_s": max(lower, _union_seconds(spans["max"])),
            }
        )
    outages_by_system.sort(key=lambda r: (-r["affected_s"], -r["count"]))

    events = _events(incidents, now)

    overall_ok_24h, overall_checks = analysis.uptime_counts(records, day_ago)
    overall_ok_7d, overall_checks_7d = analysis.uptime_counts(records, week_ago)
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
        "interval_minutes": _NOMINAL_INTERVAL_MIN,
        "cadence": _cadence(records, now),
        "window_days": int(analysis.WINDOW_DAYS),
        "chart_days": _CHART_DAYS,
        "chart_dates": chart_dates,
        "first_record": min(stamps).strftime("%Y-%m-%dT%H:%M:%SZ") if stamps else None,
        # The newest record, as distinct from generated_at: the page measures
        # the data's age against the reader's clock from this.
        "last_check": max(stamps).strftime("%Y-%m-%dT%H:%M:%SZ") if stamps else None,
        "totals": totals,
        "availability": {
            "h24": (round(100.0 * overall_ok_24h / overall_checks, 2) if overall_checks else None),
            "d7": (
                round(100.0 * overall_ok_7d / overall_checks_7d, 2) if overall_checks_7d else None
            ),
            "checks_24h": overall_checks,
            "ok_24h": overall_ok_24h,
            "checks_7d": overall_checks_7d,
            "ok_7d": overall_ok_7d,
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
        # The per-endpoint list feeds the RSS feed and stays in its published
        # shape; the page itself reads `events`, which carry the bounds.
        "incidents": [{k: i[k] for k in _INCIDENT_KEYS} for i in incidents[:200]],
        "incident_count": len(incidents),
        "events": events[:_EVENTS_SHOWN],
        "event_count": len(events),
        # Counted over every event, not just the ones sent, so the page's
        # "how many of these involve a verified endpoint" stays true when the
        # list is truncated.
        "event_count_verified": sum(1 for e in events if e["verified"]),
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
    # The feed sits beside the data file it describes. Deriving it from `path`
    # (rather than a module constant) means a caller writing to a scratch
    # location cannot silently overwrite the published feed — a test once did.
    feed_path = path.parent / FEED_PATH.name
    feed_path.write_text(render_incidents_feed(data), encoding="utf-8")
    return path
