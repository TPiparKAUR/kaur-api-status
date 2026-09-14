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
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kaur_monitor import inventory, store  # noqa: E402

API = "https://api.github.com"
LABEL = "api-incident"
MARKER = "<!-- kaur-monitor:{id} -->"


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


def _latest_by_endpoint() -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in store.read_all(since=store.window_start(2)):
        endpoint_id = record.get("id")
        if not endpoint_id:
            continue
        previous = latest.get(endpoint_id)
        if previous is None or (record.get("ts") or "") >= (previous.get("ts") or ""):
            latest[endpoint_id] = record
    return latest


def main() -> int:
    token = os.environ.get("GH_TOKEN")
    repo = os.environ.get("GH_REPO")
    if not token or not repo:
        print("GH_TOKEN või GH_REPO puudub — teavitused vahele jäetud.")
        return 0

    try:
        entries = {e["id"]: e for e in inventory.load()}
    except inventory.InventoryError as exc:
        print(f"Inventari ei saa lugeda: {exc}")
        return 0

    latest = _latest_by_endpoint()
    if not latest:
        print("Logis pole värskeid kirjeid.")
        return 0

    try:
        open_issues = _request(
            "GET", f"/repos/{repo}/issues?state=open&labels={LABEL}&per_page=100", token
        )
    except (urllib.error.URLError, ValueError) as exc:
        print(f"Ei saanud Issue'sid lugeda: {exc}")
        return 0

    by_endpoint: dict[str, int] = {}
    for issue in open_issues if isinstance(open_issues, list) else []:
        body = issue.get("body") or ""
        for endpoint_id in latest:
            if MARKER.format(id=endpoint_id) in body:
                by_endpoint[endpoint_id] = issue["number"]

    opened = closed = 0
    for endpoint_id, record in sorted(latest.items()):
        status = record.get("status")
        # 'unknown' means our own checker had no network. Never page on that.
        if status == "unknown":
            continue
        name = entries.get(endpoint_id, {}).get("name", endpoint_id)
        url = entries.get(endpoint_id, {}).get("url", "")
        existing = by_endpoint.get(endpoint_id)

        try:
            if status in ("down", "degraded") and existing is None:
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
                    {"body": f"Teenus taastus {record.get('ts')} (UTC). Vastas {record.get('ms')} ms."},
                )
                _request(
                    "PATCH",
                    f"/repos/{repo}/issues/{existing}",
                    token,
                    {"state": "closed", "state_reason": "completed"},
                )
                closed += 1
        except (urllib.error.URLError, ValueError) as exc:
            print(f"Issue'de uuendamine ebaõnnestus ({endpoint_id}): {exc}")

    print(f"Teavitused: {opened} avatud, {closed} suletud.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
