"""Turn the check log into REPORT.md: current state, outages, availability.

Times are stored in the log as UTC ISO 8601 and rendered here in Estonian local
time (EET/EEST), labelled, because the report is read by people rather than
machines.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import analysis, store

try:
    from zoneinfo import ZoneInfo

    _TALLINN: ZoneInfo | timezone = ZoneInfo("Europe/Tallinn")
    _TZ_LABEL = "EET/EEST"
except Exception:  # tz database unavailable
    _TALLINN = UTC
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
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {mins} min"
    days, hrs = divmod(hours, 24)
    return f"{days} p {hrs} h"


def build(entries: list[dict[str, Any]]) -> str:
    records = list(store.read_all(since=store.window_start(analysis.WINDOW_DAYS)))
    grouped = analysis.by_endpoint(records)
    by_id = {e["id"]: e for e in entries}
    now = datetime.now(UTC).astimezone(_TALLINN)

    out: list[str] = [
        "# Keskkonnaagentuuri API-de seisundiraport",
        "",
        f"Koostatud: **{now:%Y-%m-%d %H:%M}** ({_TZ_LABEL}) · "
        f"jälgitavaid otspunkte: **{len(entries)}** · "
        f"kontrollikirjeid viimase {int(analysis.WINDOW_DAYS)} päeva jooksul: **{len(records)}**",
        "",
    ]

    if not records:
        out += [
            f"> Viimase {int(analysis.WINDOW_DAYS)} päeva kohta kirjeid ei ole.",
            "> Käivita `python monitor.py check`.",
            "",
        ]
        return "\n".join(out)

    # 'grouped' carries every id the 31-day window has ever seen, which after
    # a schema change like the EELIS grouping includes ids nobody currently
    # monitors (e.g. the individual eelis-f-* endpoints, superseded by the
    # 'eelis' group on 2026-09-14). Those matter for the availability and
    # incident history below — they really did run during the window — but a
    # *current* state view must only speak for units that exist today, or the
    # headline count silently drifts from "jälgitavaid otspunkte".
    latest = {eid: series[-1] for eid, series in grouped.items() if series}
    current = {eid: record for eid, record in latest.items() if eid in by_id}
    tally: dict[str, int] = {}
    for record in current.values():
        tally[record.get("status", "unknown")] = tally.get(record.get("status", "unknown"), 0) + 1
    summary = " · ".join(f"{_LABEL.get(k, k)}: **{v}**" for k, v in sorted(tally.items()))
    unchecked = len(by_id) - len(current)
    if unchecked:
        summary += f" · KONTROLLIMATA (uus): **{unchecked}**"
    out += [f"Hetkeseis — {summary}", "", "## Praegune seis", ""]

    out += [
        "| Otspunkt | Seisund | Vastus | Andmete vanus | Viimane kontroll | Märkus |",
        "|---|---|---|---|---|---|",
    ]
    for eid in sorted(current):
        record = current[eid]
        entry = by_id.get(eid, {})
        name = entry.get("name", eid)
        http = record.get("http")
        ms = record.get("ms")
        response = f"{http} · {ms} ms" if http else (f"{ms} ms" if ms else "-")
        age = f"{_duration(record['age_s'])}" if record.get("age_s") is not None else "-"
        detail = (record.get("detail") or "").replace("|", "/")[:80]
        label = _LABEL.get(str(record.get("status")), "?")
        out.append(
            f"| `{eid}`<br><sub>{name}</sub> | **{label}** "
            f"| {response} | {age} | {_local(record.get('ts'))} | {detail} |"
        )
    out.append("")

    out += ["## Käideldavus", "", "| Otspunkt | " + " | ".join(w[1] for w in _WINDOWS) + " |"]
    out.append("|---" * (len(_WINDOWS) + 1) + "|")
    for eid in sorted(grouped):
        cells = []
        for days, _ in _WINDOWS:
            pct, count = analysis.uptime(grouped[eid], store.window_start(days))
            cells.append(f"{pct:.1f} % <sub>(n={count})</sub>" if pct is not None else "-")
        out.append(f"| `{eid}` | " + " | ".join(cells) + " |")
    out.append("")

    out += ["## Katkestused", ""]
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for eid, series in grouped.items():
        for incident in analysis.incidents(series):
            # An open incident on an id nobody checks any more (disabled, or
            # superseded by a grouping change) is not still running — we
            # simply stopped looking. Close it at the last failure observed,
            # rather than let "kestab" and its duration grow forever.
            if incident["end"] is None and eid not in by_id:
                incident = {**incident, "end": incident.get("last_ts")}
            rows.append((incident["start"] or "", eid, incident))
    # Sort on the key alone: two incidents can share a start, and falling
    # through to compare the dicts would raise.
    rows.sort(key=lambda row: (row[0], row[1]), reverse=True)

    if not rows:
        out += ["Logitud perioodil katkestusi ei ole.", ""]
    else:
        out += [
            "| Algus | Lõpp | Kestus | Otspunkt | Tüüp | Põhjus |",
            "|---|---|---|---|---|---|",
        ]
        moment = datetime.now(UTC)
        for _, eid, incident in rows[:100]:
            seconds = analysis.duration_seconds(incident, moment)
            length = "-" if seconds is None else _duration(seconds)
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
    for eid, record in current.items():
        raw_days = record.get("cert_days")
        if raw_days is None or int(raw_days) >= 30:
            continue
        days = int(raw_days)
        host = urlsplit(str(by_id.get(eid, {}).get("url", ""))).hostname or eid
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
        f"Raport katab viimased {int(analysis.WINDOW_DAYS)} päeva. Vanem ajalugu jääb "
        "kaustas `logs/` alles, aga seda ei loeta.",
        "",
        f"Ajad on {_TZ_LABEL} vööndis. Logi hoiab UTC ISO 8601 kujul kaustas `logs/`.",
        "Seisund **TEADMATA** tähendab, et kontrollija ise ei saanud võrku — "
        "see ei lähe käideldavuse arvestusse.",
        "",
        "**Logi skeemi ajalugu.** Alates **2026-09-14** logitakse EELIS-e 261 "
        "tabelit ühe koondkirjena (üksus `eelis`) — varem kirjutati iga tabeli "
        "kohta oma rida. Sellest kuupäevast vanemad kirjed kannavad üksikuid "
        "otspunkti ID-sid (nt `eelis-f-...`) ja kaovad 31-päevasest aknast "
        "iseenesest. Samast kuupäevast kannab iga kirje väljad `v` (skeemi "
        "versioon) ja `attempts` (kas tulemus kinnitati teistkordse kontrolliga); "
        "vanemates kirjetes need väljad puuduvad ja seda tuleb lugeda kui "
        "`attempts = 1`.",
        "",
    ]
    return "\n".join(out)


def write(entries: list[dict[str, Any]], path: Path = REPORT_PATH) -> Path:
    path.write_text(build(entries), encoding="utf-8")
    return path
