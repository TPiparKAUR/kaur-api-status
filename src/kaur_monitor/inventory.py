"""The endpoint inventory: load, validate and write ``config/endpoints.toml``.

The inventory is data, not code. Nothing in this repository hardcodes a
Keskkonnaagentuur URL; entries arrive either from ``discover`` or from a human
editing the TOML. Every entry carries ``verified``, which stays false until a
person has confirmed the URL is the one the service actually publishes.
"""

from __future__ import annotations

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
    }
)
_VALID_EXPECT = frozenset({"json", "xml", "any"})


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
        seen.add(entry["id"])
        validated.append(entry)

    return validated


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


def save(entries: list[dict[str, Any]], path: Path = CONFIG_PATH) -> None:
    """Write the inventory back as TOML, preserving hand-editability."""
    lines = [
        "# Keskkonnaagentuur API endpoint inventory.",
        "#",
        "# verified = false means nobody has confirmed this URL yet. Unverified",
        "# entries are checked but flagged separately in the report.",
        "#",
        "# Regenerate discovered entries with: python monitor.py discover",
        '# Hand-written entries (source = "manual") are never overwritten.',
        "",
    ]
    for entry in sorted(entries, key=lambda e: e["id"]):
        lines.append("[[endpoint]]")
        for key in (
            "id",
            "name",
            "system",
            "url",
            "expect",
            "method",
            "headers",
            "timeout_s",
            "max_bytes",
            "freshness_regex",
            "max_age_s",
            "enabled",
            "source",
            "verified",
            "note",
        ):
            if key in entry and entry[key] is not None:
                lines.append(f"{key} = {_fmt(entry[key])}")
        lines.append("")

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
