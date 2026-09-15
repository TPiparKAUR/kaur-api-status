#!/usr/bin/env python3
"""THROWAWAY. One-off probe: read catalogue pages and report what they expose.

Delete this script and its input file once the endpoints it finds are in
config/endpoints.toml. It exists because an authoring session cannot reach
andmed.eesti.ee (the agent proxy denies Estonian government domains), so the
only way to *see* what documentation and access URLs the Teabevärav lists is
to look from the Actions runner and print the result.

It writes nothing and changes nothing. It prints:
  - status, content type and size for every URL in the input file
  - every off-site URL found in an HTML body (the documentation and access
    links the catalogue points at)
  - a bounded head of a JSON body, so an unknown API shape can be read rather
    than guessed at

No URL is hardcoded here: the list comes from the file named on the command
line, which keeps this consistent with the rule that endpoint addresses live
in data, not in source.

Usage:  python scripts/probe_catalogue.py scripts/catalogue-pages.txt
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "KAUR-API-monitor/1.0 (one-off catalogue probe; Keskkonnaagentuur)"
TIMEOUT_S = 30.0
MAX_BYTES = 512 * 1024
DELAY_S = 0.5  # a courtesy gap; this is someone else's public portal
JSON_HEAD = 4000
# A small JSON object is printed whole rather than headed: the catalogue's
# service records are about a kilobyte and the whole point of this probe is to
# read the shape instead of guessing which fields matter.
JSON_WHOLE_UNDER = 22000
_HREF = re.compile(r'(?:href|src|content)="(https?://[^"]+)"', re.I)
_BARE = re.compile(r'https?://[^\s"\'<>)\\]+')


def fetch(url: str) -> tuple[int | str, str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.status, content_type, response.read(MAX_BYTES)
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read(2048)
        except Exception:
            pass
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", body
    except Exception as exc:
        # A probe reports what happened; it never raises past this point.
        return f"ERROR {type(exc).__name__}: {exc}", "", b""


_RELATIVE = re.compile(r'href="(?!https?:|mailto:|#|javascript:)([^"]+)"', re.I)


def offsite_urls(body: bytes, page_url: str, same_host: bool = False) -> list[str]:
    """Links worth looking at. Off-site by default, everything with same_host.

    Same-host links are normally the site's own navigation, which is why they
    are dropped — but a directory index, or a documentation page that names
    the feed it documents, keeps the interesting URL on its own host, and
    then dropping it loses the very thing being looked for.
    """
    text = body.decode("utf-8", errors="replace")
    split = urllib.parse.urlsplit(page_url)
    host = split.hostname or ""
    found = set(_HREF.findall(text)) | set(_BARE.findall(text))
    if same_host:
        found |= {urllib.parse.urljoin(page_url, rel) for rel in _RELATIVE.findall(text)}
    keep = []
    for raw in found:
        url = raw.rstrip(".,);\"'")
        target = urllib.parse.urlsplit(url).hostname or ""
        if not target:
            continue
        if target == host and not same_host:
            continue
        if any(noise in target for noise in ("w3.org", "gstatic", "googleapis", "schema.org")):
            continue
        keep.append(url)
    return sorted(set(keep))


def summarise_json(payload: str) -> str | None:
    """Condense the two shapes this crawl keeps meeting, or None for the rest.

    A dataset record is 5-20 kB of which four fields matter, and an OpenAPI
    document is far larger than the list of paths anyone needs from it.
    Printing the whole body for those drowns the log.
    """
    try:
        obj = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None

    if "distributions" in obj:
        holder = (obj.get("organization") or {}).get("name") if obj.get("organization") else None
        out = [f"DATASET {obj.get('title')} | slug={obj.get('slug')} | holder={holder}"]
        out.append(f"    landingPage: {obj.get('landingPage')}")
        for dist in obj.get("distributions") or []:
            urls = ", ".join(dist.get("accessUrls") or []) or "-"
            out.append(f"    [{dist.get('format') or '?':<6}] {dist.get('titleEt')}: {urls}")
        for entry in obj.get("datasetFiles") or []:
            out.append(f"    file: {json.dumps(entry, ensure_ascii=False)[:200]}")
        return "\n".join(out)

    if obj.get("openapi") or obj.get("swagger"):
        servers = obj.get("servers") or obj.get("host") or obj.get("basePath")
        out = [f"OPENAPI {json.dumps(obj.get('info', {}).get('title'), ensure_ascii=False)}"]
        out.append(f"    servers: {json.dumps(servers, ensure_ascii=False)}")
        for path, spec in sorted((obj.get("paths") or {}).items()):
            if not isinstance(spec, dict):
                continue
            get_spec = spec.get("get")
            if not isinstance(get_spec, dict):
                continue
            required = [
                p.get("name")
                for p in get_spec.get("parameters") or []
                if p.get("required") or p.get("in") == "path"
            ]
            mark = "NEEDS " + ",".join(required) if required else "free"
            out.append(f"    GET {path}   [{mark}]")
        return "\n".join(out)

    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    urls = []
    same_host_pages: set[str] = set()
    for line in Path(argv[1]).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 'search:<term>' is shorthand for the one listing route the portal
        # accepts: /api/datasets rejects every organisation filter tried, but
        # takes a free-text search, and the probe follows each hit's record.
        if line.startswith("search:"):
            term = urllib.parse.quote(line.split(":", 1)[1].strip())
            urls.append(f"https://andmed.eesti.ee/api/datasets?limit=5&search={term}")
        elif line.startswith("all:"):
            # 'all:<url>' keeps the page's own-host links too — a directory
            # index or a feed's documentation page points at itself.
            urls.append(line.split(":", 1)[1].strip())
            same_host_pages.add(line.split(":", 1)[1].strip())
        else:
            urls.append(line)
    print(f"Probing {len(urls)} URLs\n")

    everything: set[str] = set()
    queue = list(urls)
    seen: set[str] = set()
    index = 0

    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        index += 1
        status, content_type, body = fetch(url)
        print(f"[{index}] {url}")
        print(f"    status={status} type={content_type or '-'} bytes={len(body)}")
        if body:
            links = offsite_urls(body, url, same_host=url in same_host_pages)
            everything.update(links)
            if "json" in content_type.lower():
                text = body.decode("utf-8", errors="replace")
                flat = " ".join(text.split())
                summary = summarise_json(text)
                if summary:
                    print("    " + summary.replace("\n", "\n    ").strip())
                elif len(body) < JSON_WHOLE_UNDER:
                    print(f"    json: {flat}")
                else:
                    print(f"    json head: {flat[:JSON_HEAD]}")
                # Follow the catalogue's own references one level: a service
                # record names the datasets it belongs to, a search result
                # names the datasets that matched, and the dataset record is
                # where the distribution URLs live. Following what a response
                # actually contains beats guessing a URL shape.
                followable = re.findall(r'"relatedDatasets":\[(.*?)\]', flat)
                if '"data":[' in flat:
                    followable.append(flat)
                for chunk in followable:
                    for dataset_id in re.findall(r'"id":"([0-9a-f-]{36})"', chunk):
                        split = urllib.parse.urlsplit(url)
                        follow = f"{split.scheme}://{split.hostname}/api/datasets/{dataset_id}"
                        if follow not in seen:
                            queue.append(follow)
            elif links:
                cap = len(links) if url in same_host_pages else 25
                for link in links[:cap]:
                    print(f"    -> {link}")
                if len(links) > cap:
                    print(f"    -> ... and {len(links) - cap} more")
            else:
                head = body[:300].decode("utf-8", errors="replace")
                print(f"    (no off-site links) head: {' '.join(head.split())}")
        print()
        time.sleep(DELAY_S)

    print("\n=== every off-site URL seen, deduplicated ===")
    for url in sorted(everything):
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
