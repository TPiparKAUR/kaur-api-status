"""The endpoint inventory: load, validate and write ``config/endpoints.toml``.

The inventory is data, not code. Nothing in this repository hardcodes a
Keskkonnaagentuur URL; entries arrive either from ``discover`` or from a human
editing the TOML. Every entry carries ``verified``, which stays false until a
person has confirmed the URL is the one the service actually publishes.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("config/endpoints.toml")

_REQUIRED = ("id", "name", "url")
_ALLOWED = frozenset(
    {
        "id",
        "name",
        "url",
        "system",
        "expect",
        "method",
        "timeout_s",
        "max_bytes",
        "freshness_regex",
        "max_age_s",
        "enabled",
        "source",
        "verified",
        "note",
        "headers",
        "body",
        "group",
    }
)
_VALID_EXPECT = frozenset({"json", "xml", "any"})

# A monitor runs unattended every few minutes. Methods that can change state on
# the far side are refused outright rather than trusted to be harmless: KAIA,
# for one, publishes a PUT on the same path as its file download.
_SAFE_METHODS = frozenset({"GET", "HEAD", "POST", "OPTIONS"})


class InventoryError(Exception):
    """The inventory file is missing, malformed, or internally inconsistent."""


def load(path: Path = CONFIG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        raise InventoryError(
            f"{path} not found. Run 'python monitor.py discover' from a machine that "
            f"can reach the Estonian open data portal, or create the file by hand "
            f"(see config/endpoints.example.toml)."
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise InventoryError(f"{path} is not valid TOML: {exc}") from exc

    entries = raw.get("endpoint", [])
    if not isinstance(entries, list):
        raise InventoryError(f"{path}: 'endpoint' must be an array of tables")

    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        where = f"{path} endpoint #{index + 1}"
        for key in _REQUIRED:
            if not entry.get(key):
                raise InventoryError(f"{where}: missing required key '{key}'")
        unknown = set(entry) - _ALLOWED
        if unknown:
            raise InventoryError(f"{where}: unknown keys {sorted(unknown)}")
        if entry["id"] in seen:
            raise InventoryError(f"{where}: duplicate id '{entry['id']}'")
        expect = str(entry.get("expect", "any")).lower()
        if expect not in _VALID_EXPECT:
            raise InventoryError(f"{where}: expect must be one of {sorted(_VALID_EXPECT)}")
        if not str(entry["url"]).startswith(("http://", "https://")):
            raise InventoryError(f"{where}: url must be http(s)")
        # Caught here so a typo fails one clear validation instead of surfacing
        # as a mystery aborted check on every run.
        for key in ("timeout_s", "max_bytes", "max_age_s"):
            if key in entry and not isinstance(entry[key], (int, float)):
                raise InventoryError(f"{where}: {key} must be a number, got {entry[key]!r}")
        if "freshness_regex" in entry:
            try:
                re.compile(str(entry["freshness_regex"]))
            except re.error as exc:
                raise InventoryError(f"{where}: freshness_regex does not compile: {exc}") from exc
        if "headers" in entry:
            if not isinstance(entry["headers"], dict):
                raise InventoryError(f"{where}: headers must be a table of strings")
            for key, value in entry["headers"].items():
                if not isinstance(value, str):
                    raise InventoryError(f"{where}: header {key!r} must be a string")
        method = str(entry.get("method", "GET")).upper()
        if method not in _SAFE_METHODS:
            raise InventoryError(
                f"{where}: method {method} can change state on the monitored service; "
                f"only {', '.join(sorted(_SAFE_METHODS))} are allowed"
            )
        if "body" in entry:
            if not isinstance(entry["body"], str):
                raise InventoryError(f"{where}: body must be a string")
            if entry["body"].lstrip()[:1] in ("{", "["):
                try:
                    json.loads(entry["body"])
                except ValueError as exc:
                    raise InventoryError(
                        f"{where}: body looks like JSON but does not parse: {exc}"
                    ) from exc
        seen.add(entry["id"])
        validated.append(entry)

    known_groups = {g["id"] for g in load_groups(path)}
    for entry in validated:
        group_id = entry.get("group")
        if group_id and group_id not in known_groups:
            raise InventoryError(
                f"{path}: endpoint '{entry['id']}' names group '{group_id}', "
                f"which has no [[group]] entry"
            )

    return validated


_GROUP_ALLOWED = frozenset({"id", "name", "system", "url", "verified", "note"})


def load_groups(path: Path = CONFIG_PATH) -> list[dict[str, Any]]:
    """Groups: sets of endpoints that are one thing to a reader.

    EELIS publishes 261 tables behind one service. A reader wants to know
    whether EELIS answers, not which of 261 tables did; and logging all 261
    every half hour is most of a gigabyte a year of committed text. A group is
    checked in full but recorded, reported and displayed as one.
    """
    if not path.exists():
        return []
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    groups = raw.get("group", [])
    if not isinstance(groups, list):
        raise InventoryError(f"{path}: 'group' must be an array of tables")
    for index, group in enumerate(groups):
        where = f"{path} group #{index + 1}"
        if not group.get("id") or not group.get("name"):
            raise InventoryError(f"{where}: a group needs both 'id' and 'name'")
        unknown = set(group) - _GROUP_ALLOWED
        if unknown:
            raise InventoryError(f"{where}: unknown keys {sorted(unknown)}")
    return groups


def units(entries: list[dict[str, Any]], groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the log, the report and the page each count as one monitored thing.

    An ungrouped endpoint is its own unit. Grouped endpoints become a single
    synthetic unit carrying the group's name, so everything downstream can stay
    unaware that a unit might stand for hundreds of requests.
    """
    meta = {g["id"]: g for g in groups}
    members: dict[str, list[dict[str, Any]]] = {}
    out: list[dict[str, Any]] = []
    for entry in entries:
        group_id = entry.get("group")
        if group_id:
            members.setdefault(str(group_id), []).append(entry)
        else:
            out.append(entry)
    for group_id, group_members in sorted(members.items()):
        info = meta.get(group_id, {})
        out.append(
            {
                "id": group_id,
                "name": info.get("name", group_id),
                "system": info.get("system") or group_members[0].get("system") or "Muu",
                "url": info.get("url") or str(group_members[0]["url"]).split("?")[0],
                "verified": bool(info.get("verified", False)),
                "note": info.get("note", ""),
                "members": len(group_members),
            }
        )
    return out


def load_or_empty(path: Path = CONFIG_PATH) -> list[dict[str, Any]]:
    """Load the inventory, treating a missing file as empty rather than an error.

    Used by the scheduled check: having nothing to monitor yet is a normal
    starting state, and failing the job hourly until someone populates the file
    would train everyone to ignore the alerts. A file that exists but is
    malformed still raises, because that is a real mistake.
    """
    return load(path) if path.exists() else []


def enabled_only(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("enabled", True)]


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        pairs = ", ".join(f"{_fmt(str(k))} = {_fmt(str(v))}" for k, v in value.items())
        return f"{{ {pairs} }}"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _preamble(path: Path) -> list[str]:
    """Whatever a human wrote above the first table in an existing file.

    A discovery run rewrites this file wholesale, and once silently deleted the
    notes explaining why a documented header value is wrong and why certain
    endpoints are excluded — knowledge that belongs exactly where the next
    person edits. Anything above the first table is now carried across.
    """
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    for line in lines:
        if line.lstrip().startswith("[["):
            break
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return kept


_DEFAULT_PREAMBLE = [
    "# Keskkonnaagentuur API endpoint inventory.",
    "#",
    "# verified = false means nobody has confirmed this URL yet. Unverified",
    "# entries are checked but flagged separately in the report and never alert.",
    "#",
    "# Comments above the first table are preserved across a discovery run;",
    "# comments between tables are not, because the tables are regenerated.",
]

_ENTRY_ORDER = (
    "id",
    "name",
    "system",
    "group",
    "url",
    "expect",
    "method",
    "headers",
    "body",
    "timeout_s",
    "max_bytes",
    "freshness_regex",
    "max_age_s",
    "enabled",
    "source",
    "verified",
    "note",
)

_GROUP_ORDER = ("id", "name", "system", "url", "verified", "note")


def _table(kind: str, entry: dict[str, Any], order: tuple[str, ...]) -> list[str]:
    lines = [f"[[{kind}]]"]
    lines += [
        f"{key} = {_fmt(entry[key])}" for key in order if key in entry and entry[key] is not None
    ]
    lines.append("")
    return lines


def save(
    entries: list[dict[str, Any]],
    path: Path = CONFIG_PATH,
    groups: list[dict[str, Any]] | None = None,
) -> None:
    """Write the inventory back as TOML, preserving hand-editability.

    Groups are re-emitted rather than dropped: without this a discovery run
    would quietly delete the definition that makes 261 endpoints report as one.
    """
    if groups is None:
        groups = load_groups(path)

    lines = _preamble(path) or list(_DEFAULT_PREAMBLE)
    lines.append("")
    for group in sorted(groups, key=lambda g: g["id"]):
        lines += _table("group", group, _GROUP_ORDER)
    for entry in sorted(entries, key=lambda e: e["id"]):
        lines += _table("endpoint", entry, _ENTRY_ORDER)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def merge(
    existing: list[dict[str, Any]], discovered: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int, int]:
    """Add newly discovered endpoints without disturbing existing ones.

    Returns the merged list plus counts of added and skipped entries. Manual
    edits win: an id already present is never modified, so a human correcting a
    discovered URL does not have that correction reverted on the next run.
    """
    by_id = {e["id"]: e for e in existing}
    added = 0
    for entry in discovered:
        if entry["id"] in by_id:
            continue
        by_id[entry["id"]] = entry
        added += 1
    return list(by_id.values()), added, len(discovered) - added
