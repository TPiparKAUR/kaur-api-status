"""Layered availability checks for a single HTTP endpoint.

An HTTP 200 does not mean an OGC or observation service is healthy: a WFS can
answer 200 with an ows:ExceptionReport body, and a weather API can answer 200
with data that stopped updating days ago. Each endpoint is therefore taken
through an ordered sequence of stages and the last stage reached is recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

USER_AGENT = "KAUR-API-monitor/1.0 (availability monitoring; Keskkonnaagentuur)"

STAGES = (
    "dns",
    "connect",
    "http",
    "content_type",
    "parse",
    "service_exception",
    "freshness",
)

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"

# Stages at or below this index failing means we could not reach the host at
# all, which may equally well be our own network. The caller decides.
_REACHABILITY_STAGES = frozenset({"dns", "connect"})

_OWS_EXCEPTION_TAGS = frozenset({"serviceexceptionreport", "exceptionreport"})

_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_MAX_BYTES = 4 * 1024 * 1024


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_timestamp(raw: str) -> datetime | None:
    raw = raw.strip()
    if re.fullmatch(r"\d{9,13}", raw):
        value = int(raw)
        if value > 10_000_000_000:
            value //= 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _tls_expiry_days(host: str, port: int, timeout: float) -> int | None:
    """Days until the TLS certificate expires. Silent expiry is a classic outage."""
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as raw_sock:
            with context.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
                cert = tls_sock.getpeercert()
    except Exception:
        return None
    if not cert or "notAfter" not in cert:
        return None
    try:
        expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
    except ValueError:
        return None
    return (expires.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days


def _find_service_exception(body: bytes, kind: str) -> str | None:
    """Return the exception text if the payload is an OGC/OWS exception report."""
    if kind != "xml":
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    if _localname(root.tag) not in _OWS_EXCEPTION_TAGS:
        return None
    texts = [(el.text or "").strip() for el in root.iter()]
    message = next((t for t in texts if t), "")
    return message[:200] or "service exception report returned"


def check_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    """Run one endpoint through every configured stage.

    Returns a flat record suitable for one JSONL line. Never raises: any
    unexpected failure is reported as a ``down`` result with a detail message,
    so a single bad endpoint can never abort a monitoring run.
    """
    url = endpoint["url"]
    timeout = float(endpoint.get("timeout_s", _DEFAULT_TIMEOUT_S))
    max_bytes = int(endpoint.get("max_bytes", _DEFAULT_MAX_BYTES))
    expect = str(endpoint.get("expect", "any")).lower()

    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "id": endpoint["id"],
        "status": STATUS_DOWN,
        "stage": "dns",
        "http": None,
        "ms": None,
        "bytes": None,
        "sha256": None,
        "cert_days": None,
        "age_s": None,
        "detail": "",
    }

    parts = urllib.parse.urlsplit(url)
    host = parts.hostname
    if not host:
        record["detail"] = f"unparseable url: {url}"
        return record
    port = parts.port or (443 if parts.scheme == "https" else 80)

    started = time.monotonic()

    try:
        socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        record["detail"] = f"dns lookup failed: {exc}"
        record["ms"] = int((time.monotonic() - started) * 1000)
        return record

    record["stage"] = "connect"
    if parts.scheme == "https":
        record["cert_days"] = _tls_expiry_days(host, port, timeout)

    request = urllib.request.Request(
        url,
        method=str(endpoint.get("method", "GET")).upper(),
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )

    body = b""
    content_type = ""
    truncated = False
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            record["stage"] = "http"
            record["http"] = response.status
            content_type = (response.headers.get("Content-Type") or "").lower()
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                body = body[:max_bytes]
                truncated = True
    except urllib.error.HTTPError as exc:
        record["stage"] = "http"
        record["http"] = exc.code
        record["ms"] = int((time.monotonic() - started) * 1000)
        record["detail"] = f"http {exc.code} {exc.reason}"
        return record
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        record["detail"] = f"connection failed: {reason}"
        record["ms"] = int((time.monotonic() - started) * 1000)
        return record
    except Exception as exc:
        record["detail"] = f"unexpected error: {type(exc).__name__}: {exc}"
        record["ms"] = int((time.monotonic() - started) * 1000)
        return record

    record["ms"] = int((time.monotonic() - started) * 1000)
    record["bytes"] = len(body)
    record["sha256"] = hashlib.sha256(body).hexdigest()[:16]

    if not body:
        record["status"] = STATUS_DEGRADED
        record["detail"] = "empty response body"
        return record

    record["stage"] = "content_type"
    if expect in ("json", "xml") and expect not in content_type:
        # Many Estonian services answer text/plain or text/html for XML. Only
        # treat it as degraded once the body also fails to parse, below.
        record["detail"] = f"content-type {content_type or 'missing'!r} does not state {expect}"

    record["stage"] = "parse"
    if truncated:
        record["status"] = STATUS_OK
        record["detail"] = f"body truncated at {max_bytes} bytes, parse skipped"
        return record

    if expect == "json":
        try:
            json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            record["status"] = STATUS_DEGRADED
            record["detail"] = f"invalid json: {exc}"
            return record
    elif expect == "xml":
        try:
            ET.fromstring(body)
        except ET.ParseError as exc:
            record["status"] = STATUS_DEGRADED
            record["detail"] = f"invalid xml: {exc}"
            return record

    record["stage"] = "service_exception"
    exception_text = _find_service_exception(body, expect)
    if exception_text:
        record["status"] = STATUS_DOWN
        record["detail"] = f"OGC service exception: {exception_text}"
        return record

    record["stage"] = "freshness"
    pattern = endpoint.get("freshness_regex")
    if pattern:
        text = body.decode("utf-8", errors="replace")
        stamps = [_parse_timestamp(m) for m in re.findall(pattern, text)]
        found = [s for s in stamps if s is not None]
        if not found:
            record["status"] = STATUS_DEGRADED
            record["detail"] = "freshness_regex matched no parseable timestamp"
            return record
        age = (datetime.now(timezone.utc) - max(found)).total_seconds()
        record["age_s"] = int(age)
        max_age = endpoint.get("max_age_s")
        if max_age is not None and age > float(max_age):
            record["status"] = STATUS_DEGRADED
            record["detail"] = f"stale data: newest record is {int(age)}s old (limit {max_age}s)"
            return record

    record["status"] = STATUS_OK
    if record["detail"]:
        # Content-type mismatch alone, with a body that parsed fine.
        record["detail"] = f"note: {record['detail']}"
    return record


def looks_like_local_network_failure(records: list[dict[str, Any]]) -> bool:
    """True when every endpoint failed before a response, i.e. probably our side."""
    if len(records) < 2:
        return False
    return all(r["stage"] in _REACHABILITY_STAGES and r["status"] != STATUS_OK for r in records)
