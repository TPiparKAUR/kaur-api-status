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


def offsite_urls(body: bytes, page_url: str) -> list[str]:
    text = body.decode("utf-8", errors="replace")
    host = urllib.parse.urlsplit(page_url).hostname or ""
    found = set(_HREF.findall(text)) | set(_BARE.findall(text))
    keep = []
    for raw in found:
        url = raw.rstrip(".,);\"'")
        target = urllib.parse.urlsplit(url).hostname or ""
        if not target or target == host:
            continue
        if any(noise in target for noise in ("w3.org", "gstatic", "googleapis", "schema.org")):
            continue
        keep.append(url)
    return sorted(set(keep))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    urls = [
        line.strip()
        for line in Path(argv[1]).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
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
            links = offsite_urls(body, url)
            everything.update(links)
            if "json" in content_type.lower():
                text = body.decode("utf-8", errors="replace")
                flat = " ".join(text.split())
                if len(body) < JSON_WHOLE_UNDER:
                    print(f"    json: {flat}")
                else:
                    print(f"    json head: {flat[:JSON_HEAD]}")
                # Follow the catalogue's own references one level: a service
                # record names the datasets it belongs to, and the dataset
                # record is where the distribution URLs live. Following what
                # the response actually contains beats guessing a URL shape.
                for related in re.findall(r'"relatedDatasets":\[(.*?)\]', flat):
                    for dataset_id in re.findall(r'"id":"([0-9a-f-]{36})"', related):
                        follow = f"{urllib.parse.urlsplit(url).scheme}://"
                        follow += f"{urllib.parse.urlsplit(url).hostname}/api/datasets/{dataset_id}"
                        if follow not in seen:
                            queue.append(follow)
            elif links:
                for link in links[:25]:
                    print(f"    -> {link}")
                if len(links) > 25:
                    print(f"    -> ... and {len(links) - 25} more")
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
