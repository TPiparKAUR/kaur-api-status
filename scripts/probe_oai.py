#!/usr/bin/env python3
"""THROWAWAY. One-off probe: does andmed.eesti.ee serve DCAT-AP over OAI-PMH?

Delete this script, scripts/oai-probe-urls.txt and the workflow that runs them
once the question is answered. It exists because an authoring session cannot
reach andmed.eesti.ee — the agent proxy denies Estonian government domains, and
example.com with it — so a claim about what that portal exposes can only be
settled from the Actions runner. Guessing is what this repository's first hard
rule forbids.

It writes nothing and changes nothing. It prints:
  - status, content type and size for every URL in the input file
  - for an OAI-PMH response: the verb's own payload, decoded — repository
    identity, the metadata prefixes actually on offer, the sets, or the error
    code the server answers with
  - for a `harvest:` line: every page of a ListRecords response, followed via
    resumptionToken, reduced to the records that mention Keskkonnaagentuur and
    flattened into one `field = value` line per DCAT property, which is what
    makes the catalogue's endpointURL and endpointDescription values readable
  - a bounded head of any JSON body, and title plus size for HTML

No URL is hardcoded here: the list comes from the file named on the command
line, which keeps this consistent with the rule that endpoint addresses live in
data, not in source.

Usage:  python scripts/probe_oai.py scripts/oai-probe-urls.txt
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

USER_AGENT = "KAUR-API-monitor/1.0 (one-off OAI-PMH probe; Keskkonnaagentuur)"
TIMEOUT_S = 180.0
# The portal answers ListRecords with the whole catalogue in one response: the
# first probe read 8 MiB and was still truncated. Identify advertises gzip, so
# the transfer is compressed; this cap is on the decompressed body.
MAX_BYTES = 256 * 1024 * 1024
DELAY_S = 0.5  # a courtesy gap; this is someone else's public portal
MAX_PAGES = 60
MAX_RECORDS = 20000

# A harvested record is kept when its XML mentions any of these. The portal
# carries every Estonian publisher; only ours is being checked here.
KEEP = ("keskkonnaagentuur", "envir.ee", "ilmateenistus", "keskkonnaportaal")

# rdf:resource is where DCAT puts a URL that is a reference rather than a
# literal, which is exactly where endpointURL and accessURL live.
RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def local(tag: str) -> str:
    """'{ns}name' -> 'name'. Namespace prefixes vary between implementations."""
    return tag.rpartition("}")[2]


def _decode(body: bytes, encoding: str) -> bytes:
    if "gzip" not in encoding.lower():
        return body
    try:
        return gzip.decompress(body)
    except OSError:
        return body


def fetch(url: str) -> tuple[int | str, str, bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml, */*",
            # Identify advertises gzip and the uncompressed catalogue runs to
            # tens of megabytes; asking for it is politeness as much as speed.
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            raw = response.read(MAX_BYTES)
            if len(raw) == MAX_BYTES:
                print(f"    WARNING truncated at {MAX_BYTES} bytes")
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                _decode(raw, response.headers.get("Content-Encoding", "")),
            )
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read(4096)
        except Exception:
            pass
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", body
    except Exception as exc:
        # A probe reports what happened; it never raises past this point.
        return f"ERROR {type(exc).__name__}: {exc}", "", b""


def parse_xml(body: bytes) -> ET.Element | None:
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        return None


def oai_error(root: ET.Element) -> list[str]:
    return [
        f"{node.get('code', '?')}: {(node.text or '').strip()}"
        for node in root
        if local(node.tag) == "error"
    ]


def describe_oai(root: ET.Element) -> None:
    """Print whatever the verb in this response actually returned."""
    errors = oai_error(root)
    if errors:
        for message in errors:
            print(f"    OAI error  {message}")
        return

    for node in root:
        verb = local(node.tag)
        if verb in ("responseDate", "request"):
            if verb == "request":
                print(f"    request    {node.text} {dict(node.attrib)}")
            continue
        print(f"    verb       {verb}")

        if verb == "Identify":
            for child in node:
                name = local(child.tag)
                text = (child.text or "").strip()
                if text:
                    print(f"      {name:<18} {text}")
        elif verb == "ListMetadataFormats":
            for fmt in node:
                fields = {local(c.tag): (c.text or "").strip() for c in fmt}
                print(
                    f"      prefix={fields.get('metadataPrefix', '?'):<12}"
                    f" ns={fields.get('metadataNamespace', '-')}"
                )
        elif verb == "ListSets":
            for entry in node:
                fields = {local(c.tag): (c.text or "").strip() for c in entry}
                print(f"      set={fields.get('setSpec', '?'):<16} {fields.get('setName', '')}")
        elif verb in ("ListRecords", "ListIdentifiers"):
            records = [c for c in node if local(c.tag) in ("record", "header")]
            print(f"      records on this page: {len(records)}")
            token = next((c for c in node if local(c.tag) == "resumptionToken"), None)
            if token is not None:
                print(
                    f"      resumptionToken completeListSize="
                    f"{token.get('completeListSize', '?')} cursor={token.get('cursor', '?')}"
                )
            if records:
                head = ET.tostring(records[0])[:600].decode("utf-8", "replace")
                print(f"      first record head: {head}")


def metadata_prefixes(root: ET.Element) -> list[str]:
    out: list[str] = []
    for node in root:
        if local(node.tag) != "ListMetadataFormats":
            continue
        for fmt in node:
            for child in fmt:
                if local(child.tag) == "metadataPrefix" and (child.text or "").strip():
                    out.append(child.text.strip())
    return out


def flatten(element: ET.Element, depth: int = 0) -> list[tuple[str, str]]:
    """Every (localname, value) pair under an element, in document order.

    `value` is the element text when it has one, otherwise its rdf:resource or
    rdf:about — a DCAT URL is nearly always the latter.
    """
    rows: list[tuple[str, str]] = []
    for child in element.iter():
        name = local(child.tag)
        text = (child.text or "").strip()
        value = text or child.get(RDF_RESOURCE) or child.get(RDF_ABOUT) or ""
        if value:
            rows.append((name, value))
    return rows


def record_kinds(element: ET.Element) -> list[str]:
    """DCAT class names present in a record: Dataset, DataService, Distribution."""
    return sorted(
        {
            local(c.tag)
            for c in element.iter()
            if local(c.tag)
            in ("Dataset", "DataService", "Distribution", "Catalog", "CatalogRecord")
        }
    )


def harvest(url: str, detail: bool = True) -> None:
    """Follow ListRecords through every resumptionToken; keep our own records.

    With `detail` off only the counts and the compact summary are printed,
    which is what a subset endpoint needs — its records are the same ones the
    full harvest already listed.
    """
    base = url.split("?")[0]
    seen = 0
    kept: list[tuple[str, ET.Element]] = []
    page = 0
    next_url: str | None = url

    while next_url and page < MAX_PAGES and seen < MAX_RECORDS:
        page += 1
        status, _content_type, body = fetch(next_url)
        print(f"    page {page:>3}  status={status} bytes={len(body)}")
        root = parse_xml(body) if body else None
        if root is None:
            print(f"      not XML; head: {body[:300].decode('utf-8', 'replace')}")
            return
        errors = oai_error(root)
        if errors:
            for message in errors:
                print(f"      OAI error  {message}")
            return

        token_value: str | None = None
        for node in root:
            if local(node.tag) not in ("ListRecords", "ListIdentifiers"):
                continue
            for child in node:
                name = local(child.tag)
                if name == "record":
                    seen += 1
                    blob = ET.tostring(child, encoding="unicode").lower()
                    if any(needle in blob for needle in KEEP):
                        kept.append((identifier_of(child), child))
                elif name == "resumptionToken":
                    token_value = (child.text or "").strip()
                    if page == 1:
                        print(f"      completeListSize={child.get('completeListSize', '?')}")
        next_url = (
            f"{base}?verb=ListRecords&resumptionToken={urllib.parse.quote(token_value)}"
            if token_value
            else None
        )
        time.sleep(DELAY_S)

    if next_url:
        print(f"    STOPPED EARLY at page {page}: a resumptionToken is still pending")
    print(f"\n    harvested {seen} records over {page} page(s); {len(kept)} match {KEEP}\n")
    if detail:
        for index, (identifier, record) in enumerate(kept, start=1):
            print(f"    --- [{index}] {identifier}")
            outline(record)
            print()
    summarise(kept)


# Properties worth printing per DCAT node. Everything else — the ADMS concept
# schemes, the licence boilerplate, the EU vocabulary URIs — is the same on
# every record and says nothing about findability.
INTERESTING = (
    "title",
    "description",
    "endpointURL",
    "endpointDescription",
    "servesDataset",
    "accessURL",
    "downloadURL",
    "format",
    "mediaType",
    "landingPage",
    "documentation",
    "conformsTo",
    "accessService",
    "fn",
    "identifier",
)


def outline(record: ET.Element) -> None:
    """Print each DCAT node in a record with its own direct properties.

    Flattening a whole record loses which endpointURL belongs to which service
    and which accessURL to which distribution, and that distinction is the
    entire question here.
    """
    for node in record.iter():
        kind = local(node.tag)
        if kind not in ("Dataset", "DataService", "Distribution", "CatalogRecord"):
            continue
        print(f"      {kind} {node.get(RDF_ABOUT, '')}")
        for child in node:
            name = local(child.tag)
            if name not in INTERESTING:
                continue
            text = (child.text or "").strip()
            value = text or child.get(RDF_RESOURCE) or child.get(RDF_ABOUT) or ""
            if not value:
                # A wrapper element such as dcat:distribution; its own child
                # carries the value and is reached on a later iteration.
                continue
            print(f"        {name:<22} {value[:220]}")


def summarise(kept: list[tuple[str, ET.Element]]) -> None:
    """One line per kept record: what a reader of the letter actually needs.

    The question behind this is how many of our catalogue entries point at a
    machine interface rather than at a web page, so endpointURL and
    endpointDescription are pulled out by name and everything else collapses
    to a count.
    """
    print("    === compact summary ===")
    services = 0
    with_endpoint_description = 0
    for _identifier, record in kept:
        fields: dict[str, list[str]] = {}
        for name, value in flatten(record):
            fields.setdefault(name, []).append(value)
        kinds = record_kinds(record)
        title = (fields.get("title") or ["-"])[0]
        endpoints = fields.get("endpointURL", [])
        descriptions = fields.get("endpointDescription", [])
        access = fields.get("accessURL", []) + fields.get("downloadURL", [])
        if "DataService" in kinds:
            services += 1
            if descriptions:
                with_endpoint_description += 1
        print(
            f"      {'/'.join(kinds) or '?':<12} {title[:46]:<46}"
            f" endpointURL={endpoints or '-'} endpointDescription={descriptions or '-'}"
            f" access/downloadURLs={len(access)}"
        )
    print(
        f"    DataService records kept: {services};"
        f" of those with an endpointDescription: {with_endpoint_description}"
    )


def identifier_of(record: ET.Element) -> str:
    for child in record.iter():
        if local(child.tag) == "identifier" and (child.text or "").strip():
            return child.text.strip()
    return "?"


def report_body(url: str, content_type: str, body: bytes) -> None:
    lowered = content_type.lower()
    if "json" in lowered:
        try:
            parsed: Any = json.loads(body)
            head = json.dumps(parsed, ensure_ascii=False)[:1200]
        except ValueError:
            head = body[:1200].decode("utf-8", "replace")
        print(f"    json head: {' '.join(head.split())}")
        return
    root = parse_xml(body)
    if root is not None:
        print(f"    xml root: {local(root.tag)}")
        if local(root.tag) == "OAI-PMH":
            describe_oai(root)
        else:
            print(f"    head: {body[:400].decode('utf-8', 'replace')}")
        return
    text = body.decode("utf-8", "replace")
    match = _TITLE.search(text)
    print(f"    html title: {match.group(1).strip()[:160] if match else '-'}")
    print(f"    head: {' '.join(text[:300].split())}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    lines = [
        line.strip()
        for line in Path(argv[1]).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    print(f"Probing {len(lines)} targets\n")

    prefixes: list[str] = []
    for index, line in enumerate(lines, start=1):
        is_harvest = line.startswith(("harvest:", "count:"))
        detail = line.startswith("harvest:")
        url = line.split(":", 1)[1] if is_harvest else line

        if "metadataPrefix=AUTO" in url:
            if not prefixes:
                print(f"[{index}/{len(lines)}] {url}\n    skipped: no prefix discovered yet\n")
                continue
            chosen = next((p for p in prefixes if "dcat" in p.lower()), prefixes[0])
            url = url.replace("metadataPrefix=AUTO", f"metadataPrefix={chosen}")
            print(f"    (AUTO resolved to metadataPrefix={chosen})")

        print(f"[{index}/{len(lines)}] {'HARVEST ' if is_harvest else ''}{url}")
        if is_harvest:
            harvest(url, detail=detail)
            continue

        status, content_type, body = fetch(url)
        print(f"    status={status} type={content_type or '-'} bytes={len(body)}")
        if body:
            report_body(url, content_type, body)
            root = parse_xml(body)
            if root is not None and local(root.tag) == "OAI-PMH":
                prefixes.extend(p for p in metadata_prefixes(root) if p not in prefixes)
        print()
        time.sleep(DELAY_S)

    print(f"\n=== metadata prefixes discovered: {prefixes or 'none'} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
