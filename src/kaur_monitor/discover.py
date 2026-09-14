"""Populate the inventory from a catalogue, or from a plain list of URLs.

Two paths, because the first one may not work:

``from_ckan``   queries a CKAN-style open data catalogue. Most national open
                data portals expose this, but the exact shape of
                avaandmed.eesti.ee has NOT been verified by the author of this
                module. If the response does not match, the function says so
                loudly instead of inventing entries.

``from_urls``   reads a plain text file, one URL per line. Always works, needs
                no catalogue API, and is the fastest way to get a first
                assessment of a known set of endpoints.

Neither path ever marks an entry ``verified``. That flag is for humans.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .check import USER_AGENT

CKAN_SEARCH_PATH = "/api/3/action/package_search"


class DiscoveryError(Exception):
    """The catalogue could not be reached or did not answer in a usable shape."""


def slug(*parts: str) -> str:
    text = "-".join(p for p in parts if p).lower()
    text = (
        text.replace("õ", "o")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("ü", "u")
        .replace("š", "s")
        .replace("ž", "z")
    )
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:60] or "endpoint"


def _expect_for(url: str, declared_format: str = "") -> str:
    haystack = f"{declared_format} {url}".lower()
    if "json" in haystack:
        return "json"
    if any(token in haystack for token in ("xml", "wfs", "wms", "gml", "rss", "atom")):
        return "xml"
    return "any"


def _fetch_json(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(16 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        raise DiscoveryError(f"catalogue answered HTTP {exc.code} for {url}") from exc
    except Exception as exc:
        raise DiscoveryError(f"could not reach catalogue {url}: {exc}") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise DiscoveryError(f"catalogue response from {url} is not JSON: {exc}") from exc


def from_ckan(
    base_url: str, query: str = "", rows: int = 1000, timeout: float = 60.0
) -> list[dict[str, Any]]:
    """Harvest distribution URLs from a CKAN-style catalogue."""
    params = urllib.parse.urlencode({"q": query, "rows": rows})
    url = f"{base_url.rstrip('/')}{CKAN_SEARCH_PATH}?{params}"
    payload = _fetch_json(url, timeout)

    if not isinstance(payload, dict) or "result" not in payload:
        raise DiscoveryError(
            f"{url} did not answer in CKAN shape (no 'result' key). "
            f"This catalogue probably uses a different API. Inspect it and use "
            f"'monitor.py import-urls' with a hand-collected list instead."
        )
    datasets = payload.get("result", {}).get("results")
    if not isinstance(datasets, list):
        raise DiscoveryError(f"{url}: 'result.results' is not a list")

    found: list[dict[str, Any]] = []
    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        dataset_name = dataset.get("title") or dataset.get("name") or "dataset"
        for resource in dataset.get("resources") or []:
            if not isinstance(resource, dict):
                continue
            resource_url = resource.get("url")
            if not isinstance(resource_url, str) or not resource_url.startswith("http"):
                continue
            declared = str(resource.get("format") or "")
            found.append(
                {
                    "id": slug(
                        dataset.get("name") or dataset_name, resource.get("name") or declared
                    ),
                    "name": f"{dataset_name} — {resource.get('name') or declared or 'ressurss'}"[
                        :160
                    ],
                    "system": str(
                        (dataset.get("organization") or {}).get("title")
                        or dataset.get("organization")
                        or ""
                    )[:120]
                    or None,
                    "url": resource_url,
                    "expect": _expect_for(resource_url, declared),
                    "enabled": True,
                    "source": "ckan",
                    "verified": False,
                }
            )
    return found


def from_urls(path: Path) -> list[dict[str, Any]]:
    """Read one URL per line. Blank lines and '#' comments are ignored.

    An optional label may follow the URL after whitespace:
        https://example.org/wfs?request=GetCapabilities   EELIS WFS
    """
    if not path.exists():
        raise DiscoveryError(f"{path} not found")

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, _, label = line.partition(" ")
        url = url.strip()
        label = label.strip()
        if not url.startswith(("http://", "https://")):
            continue
        host = urllib.parse.urlsplit(url).hostname or "endpoint"
        candidate = slug(host, label or urllib.parse.urlsplit(url).path)
        identifier = candidate
        suffix = 2
        while identifier in seen:
            identifier = f"{candidate}-{suffix}"
            suffix += 1
        seen.add(identifier)
        found.append(
            {
                "id": identifier,
                "name": label or url[:160],
                "url": url,
                "expect": _expect_for(url),
                "enabled": True,
                "source": "import",
                "verified": False,
            }
        )
    return found
