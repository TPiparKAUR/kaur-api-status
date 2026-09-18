#!/usr/bin/env python3
"""Open a GitHub issue when a service goes down, close it when it recovers.

Issues are used as the notification channel because they need no secrets, no
SMTP and no third-party service: everyone watching the repository already gets
email for them, and the issue thread doubles as an outage record.

Fails soft. A notification problem must never fail the monitoring run, so any
error is reported and the script still exits 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kaur_monitor import inventory, store

API = "https://api.github.com"
LABEL = "api-incident"
MARKER = "<!-- kaur-monitor:{id} -->"
MARKER_PATTERN = re.compile(r"<!-- kaur-monitor:([^\s>]+) -->")

# One aggregate issue for "most of it is down at once", kept apart from the
# per-unit issues by its own marker id so the same open/close machinery works
# for both. See _broad_outage() for why it exists.
BROAD_ID = "broad-outage"
BROAD_SHARE = 1 / 3
BROAD_MIN_UNITS = 6


def _request(method: str, path: str, token: str, payload: dict | None = None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "kaur-monitor",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return json.loads(body) if body else {}


def _all_open_issues(repo: str, token: str, max_pages: int = 20) -> list[dict]:
    """Every open incident issue, following pagination.

    Without this, a repository with more than one page of open incident issues
    would look as though the later ones did not exist and duplicates would be
    opened on every run.
    """
    issues: list[dict] = []
    for page in range(1, max_pages + 1):
        batch = _request(
            "GET",
            f"/repos/{repo}/issues?state=open&labels={LABEL}&per_page=100&page={page}",
            token,
        )
        if not isinstance(batch, list) or not batch:
            break
        issues.extend(batch)
        if len(batch) < 100:
            break
    return issues


def _series_by_endpoint(days: float = 2.0) -> dict[str, list[dict]]:
    """Every logged record per unit, oldest first, for the last few days.

    A short window rather than the latest record alone: opening an Issue
    needs to know whether this is the first failure or the second in a row,
    which means looking at more than just the most recent line.
    """
    series: dict[str, list[dict]] = {}
    for record in store.read_all(since=store.window_start(days)):
        endpoint_id = record.get("id")
        if not endpoint_id:
            continue
        series.setdefault(endpoint_id, []).append(record)
    for records in series.values():
        records.sort(key=lambda r: r.get("ts") or "")
    return series


def _consecutive_failures(series: list[dict]) -> int:
    """How many checks in a row, most recent first, came back down/degraded.

    'unknown' means our own network had no connection, which says nothing
    about the service; it is skipped rather than breaking the streak, the
    same treatment analysis.incidents() gives it. A single bad check must not
    open an Issue on its own — this is what lets the caller require two.
    """
    streak = 0
    for record in reversed(series):
        status = record.get("status")
        if status == "unknown":
            continue
        if status in ("down", "degraded"):
            streak += 1
            continue
        break
    return streak


def _broad_outage(latest: dict[str, dict]) -> tuple[bool, list[str], int]:
    """Is a large share of all monitored units failing in this one check?

    The two-strike rule above counts *checks*, and that quietly assumes a check
    is cheap and the next one is along in half an hour. Measured 2026-09-18
    (run 231): keskkonnaandmed.envir.ee stopped answering, 303 of 308 endpoints
    timed out at 30 s each, and because HostLimiter admits 4 at a time the run
    itself took 72 minutes. The next run found everything healthy again, so a
    second consecutive failure never arrived and a 72-minute outage of nearly
    every monitored service produced no notification at all.

    A simultaneous failure across many independent units is not a dropped
    packet, so it does not need a second opinion. Unverified units count here,
    unlike in the per-unit rule: a wrong query explains one unit failing, not
    forty at once. 'unknown' units are excluded from both sides of the ratio —
    those are the checker's own network, and if everything is unknown there is
    nothing to say about the services.
    """
    checked = [
        endpoint_id for endpoint_id, record in latest.items() if record.get("status") != "unknown"
    ]
    failing = sorted(
        endpoint_id
        for endpoint_id in checked
        if latest[endpoint_id].get("status") in ("down", "degraded")
    )
    if len(checked) < BROAD_MIN_UNITS:
        # Too few units for a share to mean anything; the per-unit rule is the
        # only sensible reading of one or two failures.
        return False, failing, len(checked)
    return len(failing) / len(checked) >= BROAD_SHARE, failing, len(checked)


def _sync_broad_issue(
    repo: str,
    token: str,
    *,
    is_broad: bool,
    failing: list[str],
    total: int,
    existing: int | None,
    timestamp: str,
) -> tuple[int, int]:
    """Open the aggregate issue while the outage is broad, close it after."""
    if is_broad and existing is None:
        listed = ", ".join(f"`{unit}`" for unit in failing[:20])
        if len(failing) > 20:
            listed += f" (+{len(failing) - 20} veel)"
        body = (
            f"{MARKER.format(id=BROAD_ID)}\n\n"
            f"**{len(failing)} jälgitavat ühikut {total}-st ei vasta korraga.**\n\n"
            f"Nii lai üheaegne rike ei ole üksik pakikadu, seega ei oodata teist "
            f"järjestikust ebaõnnestumist nagu üksiku teenuse puhul.\n\n"
            f"**Ühikud:** {listed}\n"
            f"**Avastatud:** {timestamp} (UTC)\n\n"
            f"Issue sulgub automaatselt, kui langenud ühikute osakaal langeb "
            f"alla {BROAD_SHARE:.0%}."
        )
        _request(
            "POST",
            f"/repos/{repo}/issues",
            token,
            {
                "title": f"[üldrike] {len(failing)}/{total} ühikut korraga maas",
                "body": body,
                "labels": [LABEL],
            },
        )
        return 1, 0
    if not is_broad and existing is not None:
        _request(
            "POST",
            f"/repos/{repo}/issues/{existing}/comments",
            token,
            {"body": f"Üldrike lõppes {timestamp} (UTC). Maas {len(failing)}/{total} ühikut."},
        )
        _request(
            "PATCH",
            f"/repos/{repo}/issues/{existing}",
            token,
            {"state": "closed", "state_reason": "completed"},
        )
        return 0, 1
    return 0, 0


def main() -> int:
    token = os.environ.get("GH_TOKEN")
    repo = os.environ.get("GH_REPO")
    if not token or not repo:
        print("GH_TOKEN või GH_REPO puudub — teavitused vahele jäetud.")
        return 0

    try:
        # units(), not load(): the log records one line per monitored unit,
        # and a group (EELIS's 261 tables checked as one) only exists as an
        # id here — looking it up in the raw endpoint list would miss it
        # entirely and silently skip every group from notification.
        entries = {e["id"]: e for e in inventory.units(inventory.load(), inventory.load_groups())}
    except inventory.InventoryError as exc:
        print(f"Inventari ei saa lugeda: {exc}")
        return 0

    series_by_id = _series_by_endpoint()
    latest = {eid: records[-1] for eid, records in series_by_id.items() if records}
    if not latest:
        print("Logis pole värskeid kirjeid.")
        return 0

    try:
        open_issues = _all_open_issues(repo, token)
    except Exception as exc:
        print(f"Ei saanud Issue'sid lugeda: {exc}")
        return 0

    # Keyed by the marker embedded in the issue body, not by the endpoints seen
    # recently: an endpoint that was disabled or stopped being checked must
    # still have its open issue found, or it stays open forever.
    by_endpoint: dict[str, int] = {}
    for issue in open_issues:
        found = MARKER_PATTERN.search(issue.get("body") or "")
        if found:
            by_endpoint[found.group(1)] = issue["number"]

    opened = closed = 0

    # Deliberately one aggregate issue rather than paging on every unit at
    # once: run 231 would have opened fifteen. The per-unit rule below is
    # unchanged, so a single service still has to fail twice.
    is_broad, failing, checked = _broad_outage(latest)
    newest = max((r.get("ts") or "" for r in latest.values()), default="")
    try:
        broad_opened, broad_closed = _sync_broad_issue(
            repo,
            token,
            is_broad=is_broad,
            failing=failing,
            total=checked,
            existing=by_endpoint.get(BROAD_ID),
            timestamp=newest,
        )
        opened += broad_opened
        closed += broad_closed
        if is_broad and broad_opened:
            print(f"Üldrike: {len(failing)}/{checked} ühikut maas, Issue avatud kohe.")
    except Exception as exc:
        print(f"Üldrike Issue'd ei saanud uuendada: {exc}")

    for endpoint_id, record in sorted(latest.items()):
        status = record.get("status")
        # 'unknown' means our own checker had no network. Never page on that.
        if status == "unknown":
            continue
        entry = entries.get(endpoint_id, {})
        existing = by_endpoint.get(endpoint_id)
        # An unverified endpoint is one nobody has confirmed is real, so a
        # failure is as likely to be a wrong query as a service outage. It stays
        # in the report, but it does not page anyone. Recovery still closes an
        # issue that is already open, in case the flag was cleared later.
        if not entry.get("verified", False) and existing is None:
            continue
        name = entry.get("name", endpoint_id)
        url = entry.get("url", "")

        try:
            if status in ("down", "degraded") and existing is None:
                streak = _consecutive_failures(series_by_id.get(endpoint_id, []))
                if streak < 2:
                    # One bad check is as likely to be a dropped packet as an
                    # outage. check.py already retries once inside a run;
                    # this is the second, independent layer: an Issue opens
                    # only once two separate scheduled runs both failed. The
                    # case this bar used to miss — everything failing at once
                    # in a single very long run — is caught by _broad_outage()
                    # above instead, which pages without waiting.
                    print(f"{endpoint_id}: 1. ebaõnnestumine, Issue avatakse alles teise järel.")
                    continue
                title = f"[{endpoint_id}] {'ei vasta' if status == 'down' else 'häiritud'}"
                body = (
                    f"{MARKER.format(id=endpoint_id)}\n\n"
                    f"**Teenus:** {name}\n"
                    f"**URL:** {url}\n"
                    f"**Seisund:** `{status}`\n"
                    f"**Etapp:** `{record.get('stage')}`\n"
                    f"**HTTP:** `{record.get('http')}`\n"
                    f"**Põhjus:** {record.get('detail') or '-'}\n"
                    f"**Avastatud:** {record.get('ts')} (UTC)\n\n"
                    f"Issue sulgub automaatselt, kui teenus taastub."
                )
                _request(
                    "POST",
                    f"/repos/{repo}/issues",
                    token,
                    {"title": title, "body": body, "labels": [LABEL]},
                )
                opened += 1
            elif status == "ok" and existing is not None:
                _request(
                    "POST",
                    f"/repos/{repo}/issues/{existing}/comments",
                    token,
                    {
                        "body": (
                            f"Teenus taastus {record.get('ts')} (UTC). "
                            f"Vastas {record.get('ms')} ms."
                        )
                    },
                )
                _request(
                    "PATCH",
                    f"/repos/{repo}/issues/{existing}",
                    token,
                    {"state": "closed", "state_reason": "completed"},
                )
                closed += 1
        # Deliberately broad: a read timeout raises TimeoutError, not URLError,
        # and one slow GitHub call must not stop the remaining endpoints from
        # being notified.
        except Exception as exc:
            print(f"Issue'de uuendamine ebaõnnestus ({endpoint_id}): {exc}")

    print(f"Teavitused: {opened} avatud, {closed} suletud.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
