"""Turn the check log into REPORT.md: current state, outages, availability.

Times are stored in the log as UTC ISO 8601 and rendered here in Estonian local
time (EET/EEST), labelled, because the report is read by people rather than
machines.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import store

try:
    from zoneinfo import ZoneInfo

    _TALLINN: ZoneInfo | timezone = ZoneInfo("Europe/Tallinn")
    _TZ_LABEL = "EET/EEST"
except Exception:  # tz database unavailable
    _TALLINN = timezone.utc
    _TZ_LABEL = "UTC"

REPORT_PATH = Path("REPORT.md")

_LABEL = {
    "ok": "KORRAS",
    "degraded": "HÄIRE",
    "down": "MAAS",
    "unknown": "TEADMATA",
}

_WINDOWS = ((1.0, "24 h"), (7.0, "7 päeva"), (30.0, "30 päeva"))


def _local(raw: str | None) -> str:
    stamp = store.parse_ts(raw)
    if stamp is None:
        return "-"
    return stamp.astimezone(_TALLINN).strftime("%Y-%m-%d %H:%M")


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {mins} min"
    days, hrs = divmod(hours, 24)
    return f"{days} p {hrs} h"


def _by_endpoint(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record.get("id", "?"), []).append(record)
    for series in grouped.values():
        series.sort(key=lambda r: r.get("ts") or "")
    return grouped


def _incidents(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Contiguous runs of non-ok status.

    'unknown' is treated as a gap rather than an outage: it means our own check
    could not reach the network, which says nothing about the service.
    """
    incidents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for record in series:
        status = record.get("status")
        if status == "unknown":
            continue
        if status == "ok":
            if current is not None:
                current["end"] = record.get("ts")
                incidents.append(current)
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
        incidents.append(current)
    return incidents


def _uptime(series: list[dict[str, Any]], since: datetime) -> tuple[float | None, int]:
    considered = [
        r
        for r in series
        if r.get("status") != "unknown" and (store.parse_ts(r.get("ts")) or since) >= since
    ]
    if not considered:
        return None, 0
    ok = sum(1 for r in considered if r.get("status") == "ok")
    return 100.0 * ok / len(considered), len(considered)


def build(entries: list[dict[str, Any]]) -> str:
    records = list(store.read_all())
    grouped = _by_endpoint(records)
    by_id = {e["id"]: e for e in entries}
    now = datetime.now(timezone.utc).astimezone(_TALLINN)

    out: list[str] = [
        "# Keskkonnaagentuuri API-de seisundiraport",
        "",
        f"Koostatud: **{now:%Y-%m-%d %H:%M}** ({_TZ_LABEL}) · "
        f"jälgitavaid otspunkte: **{len(entries)}** · "
        f"kontrollikirjeid logis: **{len(records)}**",
        "",
    ]

    if not records:
        out += [
            "> Logi on tühi — ühtegi kontrolli pole veel tehtud.",
            "> Käivita `python monitor.py check`.",
            "",
        ]
        return "\n".join(out)

    latest = {eid: series[-1] for eid, series in grouped.items() if series}
    tally: dict[str, int] = {}
    for record in latest.values():
        tally[record.get("status", "unknown")] = tally.get(record.get("status", "unknown"), 0) + 1
    summary = " · ".join(f"{_LABEL.get(k, k)}: **{v}**" for k, v in sorted(tally.items()))
    out += [f"Hetkeseis — {summary}", "", "## Praegune seis", ""]

    out += [
        "| Otspunkt | Seisund | Vastus | Andmete vanus | Viimane kontroll | Märkus |",
        "|---|---|---|---|---|---|",
    ]
    for eid in sorted(latest):
        record = latest[eid]
        entry = by_id.get(eid, {})
        name = entry.get("name", eid)
        http = record.get("http")
        ms = record.get("ms")
        response = f"{http} · {ms} ms" if http else (f"{ms} ms" if ms else "-")
        age = f"{_duration(record['age_s'])}" if record.get("age_s") is not None else "-"
        detail = (record.get("detail") or "").replace("|", "/")[:80]
        out.append(
            f"| `{eid}`<br><sub>{name}</sub> | **{_LABEL.get(record.get('status'), '?')}** "
            f"| {response} | {age} | {_local(record.get('ts'))} | {detail} |"
        )
    out.append("")

    out += ["## Käideldavus", "", "| Otspunkt | " + " | ".join(w[1] for w in _WINDOWS) + " |"]
    out.append("|---" * (len(_WINDOWS) + 1) + "|")
    for eid in sorted(grouped):
        cells = []
        for days, _ in _WINDOWS:
            pct, count = _uptime(grouped[eid], store.window_start(days))
            cells.append(f"{pct:.1f} % <sub>(n={count})</sub>" if pct is not None else "-")
        out.append(f"| `{eid}` | " + " | ".join(cells) + " |")
    out.append("")

    out += ["## Katkestused", ""]
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for eid, series in grouped.items():
        for incident in _incidents(series):
            rows.append((incident["start"] or "", eid, incident))
    rows.sort(reverse=True)

    if not rows:
        out += ["Logitud perioodil katkestusi ei ole.", ""]
    else:
        out += [
            "| Algus | Lõpp | Kestus | Otspunkt | Tüüp | Põhjus |",
            "|---|---|---|---|---|---|",
        ]
        for _, eid, incident in rows[:100]:
            start = store.parse_ts(incident["start"])
            end = store.parse_ts(incident["end"])
            if start and end:
                length = _duration((end - start).total_seconds())
            elif start:
                length = _duration((datetime.now(timezone.utc) - start).total_seconds())
            else:
                length = "-"
            ongoing = incident["end"] is None
            detail = (incident.get("detail") or "").replace("|", "/")[:90]
            out.append(
                f"| {_local(incident['start'])} "
                f"| {'**kestab**' if ongoing else _local(incident['end'])} "
                f"| {length} | `{eid}` | {_LABEL.get(incident['worst'], '?')} | {detail} |"
            )
        if len(rows) > 100:
            out.append(f"| … | | | | | _ja veel {len(rows) - 100} katkestust_ |")
        out.append("")

    warnings: list[str] = []
    expiring: dict[str, int] = {}
    for eid, record in latest.items():
        days = record.get("cert_days")
        if days is None or days >= 30:
            continue
        host = urlsplit(by_id.get(eid, {}).get("url", "")).hostname or eid
        expiring[host] = min(expiring.get(host, days), days)
    for host, days in sorted(expiring.items()):
        warnings.append(f"- `{host}`: TLS-sertifikaat aegub **{days} päeva** pärast")
    for entry in sorted(entries, key=lambda e: e["id"]):
        if not entry.get("verified", False):
            warnings.append(
                f"- `{entry['id']}`: URL on **kontrollimata** "
                f"(`verified = false`) — allikas: {entry.get('source', 'teadmata')}"
            )
    if warnings:
        out += ["## Hoiatused", "", *warnings, ""]

    out += [
        "---",
        "",
        f"Ajad on {_TZ_LABEL} vööndis. Logi hoiab UTC ISO 8601 kujul kaustas `logs/`.",
        "Seisund **TEADMATA** tähendab, et kontrollija ise ei saanud võrku — "
        "see ei lähe käideldavuse arvestusse.",
        "",
    ]
    return "\n".join(out)


def write(entries: list[dict[str, Any]], path: Path = REPORT_PATH) -> Path:
    path.write_text(build(entries), encoding="utf-8")
    return path
