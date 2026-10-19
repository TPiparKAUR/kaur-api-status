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
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

USER_AGENT = "KAUR-API-monitor/1.0 (availability monitoring; Keskkonnaagentuur)"

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"

# Stages at or below this index failing means we could not reach the host at
# all, which may equally well be our own network. The caller decides.
# Stages in which the request never reached the server's application layer.
# "breaker" belongs here too: a skipped endpoint is one whose host was already
# judged unreachable, and must count the same way in the local-network check.
_REACHABILITY_STAGES = frozenset({"dns", "connect", "breaker"})

_OWS_EXCEPTION_TAGS = frozenset({"serviceexceptionreport", "exceptionreport"})

_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_MAX_BYTES = 4 * 1024 * 1024
_ERROR_BODY_BYTES = 1024
_RETRY_DELAY_S = 5.0

# Almost the entire inventory sits behind one host (keskkonnaandmed.envir.ee),
# so this is really "how many requests may be in flight against that host at
# once", independent of --workers. 4 was chosen as a cautious default, not a
# measured one — nobody involved in this project runs that service.
DEFAULT_MAX_PER_HOST = 4

# Consecutive connection-level failures (no HTTP response at all) on one host
# before the rest of that host's endpoints in the same run are not dialled.
# Six is above the per-host concurrency cap, so a host that is merely slow for
# a few endpoints does not trip it, while a host that is gone is written off
# after about two rounds instead of 279 timeouts (run 231: 72 minutes).
BREAKER_THRESHOLD = 6

# A 429 says when to come back. Honour it up to this many seconds; beyond that
# the endpoint is recorded as limited rather than holding the run open.
_RETRY_AFTER_CAP_S = 30.0


# Log schema version. Bumped when a field is added or a record's meaning
# changes — 2 adds 'attempts' and the group fields ('members', 'ok') that
# collapse_groups started writing on 2026-09-14. Records from before that
# date simply lack these keys; nothing downstream requires them.
LOG_SCHEMA_VERSION = 2


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_timestamp(raw: str) -> datetime | None:
    raw = raw.strip()
    if re.fullmatch(r"\d{9,13}", raw):
        value = int(raw)
        if value > 10_000_000_000:
            value //= 1000
        return datetime.fromtimestamp(value, tz=UTC)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
        expires = datetime.strptime(str(cert["notAfter"]), "%b %d %H:%M:%S %Y %Z")
    except ValueError:
        return None
    return (expires.replace(tzinfo=UTC) - datetime.now(UTC)).days


class CertCache:
    """Per-run cache of TLS expiry lookups, keyed by (host, port).

    Most of the inventory sits behind two hosts, so without this every one of
    283 endpoints would open its own extra TLS handshake — identical to the
    one the actual request makes a moment later — just to read a certificate
    that is the same for every endpoint on that host. One instance is meant
    to be shared across a whole run's ThreadPoolExecutor; the lock only ever
    guards the dict, never the network call, so concurrent lookups for
    different hosts do not block each other.
    """

    def __init__(self) -> None:
        self._values: dict[tuple[str, int], int | None] = {}
        self._lock = threading.Lock()

    def get(self, host: str, port: int, timeout: float) -> int | None:
        key = (host, port)
        with self._lock:
            if key in self._values:
                return self._values[key]
        days = _tls_expiry_days(host, port, timeout)
        with self._lock:
            # A second thread may have raced us to the same host; whichever
            # answer landed first stands; a duplicate handshake is wasted
            # work, not a correctness problem.
            self._values.setdefault(key, days)
            return self._values[key]


class HostLimiter:
    """Caps concurrent in-flight requests per host, independent of --workers.

    --workers controls total parallelism across the whole run; it says
    nothing about how much of that lands on any one host. Since almost the
    entire inventory sits behind a single PostgREST host, --workers alone
    decides how many simultaneous requests that one service sees — a monitor
    is a guest on the service it watches, and unlimited concurrency there is
    not politeness. One instance is meant to be shared across a run; a
    semaphore is created per host on first use and reused after that.
    """

    def __init__(self, max_per_host: int = DEFAULT_MAX_PER_HOST) -> None:
        self._max_per_host = max_per_host
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    def _semaphore(self, host: str) -> threading.Semaphore:
        with self._lock:
            semaphore = self._semaphores.get(host)
            if semaphore is None:
                semaphore = threading.Semaphore(self._max_per_host)
                self._semaphores[host] = semaphore
            return semaphore

    def slot(self, host: str) -> threading.Semaphore:
        """A context manager (use with ``with``) that blocks until a slot for
        this host is free. A Semaphore is itself a context manager."""
        return self._semaphore(host)


class HostBreaker:
    """Stops dialling a host for the rest of a run once it has plainly gone.

    Counts consecutive connection-level failures per host: no HTTP response at
    all (DNS, refused, timeout). Any response, even a 500 or a 429, proves the
    host is answering and resets the count, because an HTTP status is a
    service talking, not a service absent. Once a host reaches the threshold
    it stays open for this run; the next scheduled run starts closed and probes
    again, so recovery is seen within one interval.

    Why it exists: a dead host with 279 endpoints and a 30 s timeout took 72
    minutes of runtime to say the same thing 279 times, and every one of those
    timeouts was load aimed at a service that was already not answering.
    """

    def __init__(self, threshold: int = BREAKER_THRESHOLD) -> None:
        self._threshold = max(1, int(threshold))
        self._consecutive: dict[str, int] = {}
        self._open: set[str] = set()
        self._lock = threading.Lock()

    def is_open(self, host: str) -> bool:
        with self._lock:
            return host in self._open

    def observe(self, host: str, connection_failed: bool) -> None:
        with self._lock:
            if not connection_failed:
                self._consecutive[host] = 0
                return
            count = self._consecutive.get(host, 0) + 1
            self._consecutive[host] = count
            if count >= self._threshold:
                self._open.add(host)

    @property
    def threshold(self) -> int:
        return self._threshold

    def open_hosts(self) -> list[str]:
        with self._lock:
            return sorted(self._open)


def _find_service_exception(body: bytes) -> str | None:
    """Return the exception text if the payload is an OGC/OWS exception report.

    The body is sniffed rather than trusted to match a declared ``expect``:
    the default is "any", and a service answering 200 with an exception report
    would otherwise pass as healthy.
    """
    if not body[:200].lstrip().startswith(b"<"):
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


def check_endpoint(
    endpoint: dict[str, Any],
    cert_cache: CertCache | None = None,
    *,
    retry: bool = False,
    retry_delay_s: float = _RETRY_DELAY_S,
    host_limiter: HostLimiter | None = None,
    breaker: HostBreaker | None = None,
) -> dict[str, Any]:
    """Run one endpoint through every configured stage, and never raise.

    Returns a flat record suitable for one JSONL line. The never-raises
    guarantee lives in ``_safe_check`` rather than trusted to the body below,
    because the caller maps this over every endpoint: one escaping exception
    would lose the whole run's log, report and notifications, not just this
    endpoint. Malformed config reaches us as ordinary data (a bad regex, a
    non-numeric timeout), so it must degrade to a result, not a crash.

    With ``retry`` set, a non-ok result is checked once more after
    ``retry_delay_s`` seconds before being returned: a single dropped packet
    or a service mid-restart should not by itself become a logged outage and
    an Issue — that is what turns one blip into a false alarm. Off by default
    so existing callers (and tests hitting a deliberately unreachable host)
    are not made to wait; the scheduled run turns it on.

    ``host_limiter``, when given, bounds how many requests may be in flight
    against the same host at once, independent of how many worker threads the
    caller runs — see ``HostLimiter``. Off by default for the same reason as
    ``retry``: existing callers and tests must not silently start blocking on
    a shared semaphore they never asked for.
    """
    cache = cert_cache if cert_cache is not None else CertCache()
    host = _host_of(endpoint)
    if breaker is not None and host is not None and breaker.is_open(host):
        return _skipped_record(endpoint, host, breaker)

    record = _safe_check(endpoint, cache, host_limiter)
    if retry and _worth_retrying(record) and not _breaker_open(breaker, host):
        time.sleep(_retry_delay(record, retry_delay_s))
        record = _safe_check(endpoint, cache, host_limiter)
        record["attempts"] = 2
    if breaker is not None and host is not None:
        breaker.observe(host, _is_connection_failure(record))
    return record


def _host_of(endpoint: dict[str, Any]) -> str | None:
    try:
        return urllib.parse.urlsplit(str(endpoint.get("url", ""))).hostname or None
    except ValueError:
        return None


def _breaker_open(breaker: HostBreaker | None, host: str | None) -> bool:
    return breaker is not None and host is not None and breaker.is_open(host)


def _is_connection_failure(record: dict[str, Any]) -> bool:
    """No HTTP response at all, and the failure happened on the network path."""
    return (
        record.get("status") == STATUS_DOWN
        and record.get("http") is None
        and record.get("stage") in {"dns", "connect"}
    )


def _worth_retrying(record: dict[str, Any]) -> bool:
    """A second attempt only where a transient cause is plausible.

    A 4xx other than 408/429 is the server saying the request is wrong (406 for
    a misspelled PostgREST profile, 404, 403); repeating it five seconds later
    changes nothing and costs one more request. A config-stage failure is local
    and deterministic. A breaker-skipped endpoint was never attempted at all.
    """
    if record.get("status") == STATUS_OK:
        return False
    if record.get("stage") in {"config", "breaker"}:
        return False
    http = record.get("http")
    if isinstance(http, int) and 400 <= http < 500 and http not in (408, 429):
        return False
    return True


def _retry_delay(record: dict[str, Any], default: float) -> float:
    """Wait as long as a 429 asks, up to a cap; otherwise the usual short pause."""
    retry_after = record.get("retry_after_s")
    if record.get("http") == 429 and isinstance(retry_after, int):
        return float(min(retry_after, _RETRY_AFTER_CAP_S))
    return default


def _skipped_record(endpoint: dict[str, Any], host: str, breaker: HostBreaker) -> dict[str, Any]:
    """Recorded as down, deliberately: the host really is failing, and hiding
    that as ``unknown`` would erase the outage from the availability figures.
    The detail says the endpoint was not dialled, so nobody reads it as a
    measurement of this endpoint on its own."""
    return {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "id": str(endpoint.get("id", "?")),
        "status": STATUS_DOWN,
        "stage": "breaker",
        "http": None,
        "ms": None,
        "bytes": None,
        "sha256": None,
        "cert_days": None,
        "age_s": None,
        "detail": (
            f"not dialled: {host} gave no response to {breaker.threshold} "
            f"connections in a row earlier in this run"
        ),
        "attempts": 1,
        "v": LOG_SCHEMA_VERSION,
    }


def _parse_retry_after(raw: str | None) -> int | None:
    """Delta-seconds form only. The HTTP-date form is rare from these hosts and
    is not guessed at: None means "no usable value", and the default pause runs."""
    if raw is None:
        return None
    value = raw.strip()
    return int(value) if value.isdigit() else None


def _safe_check(
    endpoint: dict[str, Any], cert_cache: CertCache, host_limiter: HostLimiter | None = None
) -> dict[str, Any]:
    try:
        return _check_endpoint(endpoint, cert_cache, host_limiter)
    except Exception as exc:
        return {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "id": str(endpoint.get("id", "?")),
            "status": STATUS_DOWN,
            "stage": "config",
            "http": None,
            "ms": None,
            "bytes": None,
            "sha256": None,
            "cert_days": None,
            "age_s": None,
            "detail": f"check aborted: {type(exc).__name__}: {exc}"[:300],
            "attempts": 1,
            "v": LOG_SCHEMA_VERSION,
        }


def _check_endpoint(
    endpoint: dict[str, Any], cert_cache: CertCache, host_limiter: HostLimiter | None = None
) -> dict[str, Any]:
    url = endpoint["url"]
    timeout = float(endpoint.get("timeout_s", _DEFAULT_TIMEOUT_S))
    max_bytes = int(endpoint.get("max_bytes", _DEFAULT_MAX_BYTES))
    expect = str(endpoint.get("expect", "any")).lower()

    record: dict[str, Any] = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        "attempts": 1,
        "v": LOG_SCHEMA_VERSION,
    }

    parts = urllib.parse.urlsplit(url)
    host = parts.hostname
    if not host:
        record["detail"] = f"unparseable url: {url}"
        return record
    port = parts.port or (443 if parts.scheme == "https" else 80)

    # This clock is only for the dns-failure path below. It deliberately does
    # not time the certificate check that follows: that check opens its own
    # TLS handshake purely to read an expiry date, on top of the one the
    # actual request makes a moment later, and folding it into 'ms' would
    # inflate every published response time by a whole extra round trip.
    dns_started = time.monotonic()

    try:
        socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        record["detail"] = f"dns lookup failed: {exc}"
        record["ms"] = int((time.monotonic() - dns_started) * 1000)
        return record

    record["stage"] = "connect"
    if parts.scheme == "https":
        record["cert_days"] = cert_cache.get(host, port, timeout)

    method = str(endpoint.get("method", "GET")).upper()
    # Per-endpoint headers matter for content negotiation: a PostgREST service
    # needs Accept-Profile to select the right database schema, and without it
    # answers from an unspecified one.
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    extra = endpoint.get("headers")
    if isinstance(extra, dict):
        headers.update({str(key): str(value) for key, value in extra.items()})

    # Some read paths are reachable only by POST with a query document — KAIA's
    # document search is one — so a request body is part of describing an
    # endpoint, not a sign that the check mutates anything.
    raw_body = endpoint.get("body")
    data = None if raw_body is None else str(raw_body).encode("utf-8")
    if data is not None:
        headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(url, data=data, method=method, headers=headers)

    body = b""
    content_type = ""
    truncated = False
    # A wait for a free per-host slot is not the service's response time, so
    # timing starts only once the slot (if any) is actually held — right
    # before the request this endpoint is being checked for.
    limiter_slot = host_limiter.slot(host) if host_limiter is not None else nullcontext()
    try:
        with limiter_slot:
            started = time.monotonic()
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
        # Which layer answered, and whether it said when to come back. Cloudflare
        # (cf-ray) versus the origin (server) is the one thing that separates
        # "the service limits us" from "a bot filter in front of it does" — see
        # CLAUDE.md, 429 measurements. Present only on HTTP error records.
        error_headers = exc.headers
        if error_headers is not None:
            record["server"] = (error_headers.get("Server") or "")[:64] or None
            record["cf_ray"] = (error_headers.get("CF-Ray") or "")[:64] or None
            record["retry_after_s"] = _parse_retry_after(error_headers.get("Retry-After"))
        # The error body usually says what is actually wrong — PostgREST, for
        # one, answers 406 with the list of schemas it will accept. Throwing it
        # away turns a self-explaining failure into a guessing game.
        try:
            snippet = exc.read(_ERROR_BODY_BYTES).decode("utf-8", errors="replace")
        except Exception:
            snippet = ""
        snippet = " ".join(snippet.split())
        if snippet:
            record["detail"] = f"{record['detail']} — {snippet[:300]}"
        return record
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
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
        # A HEAD request is supposed to come back empty.
        record["status"] = STATUS_OK if method == "HEAD" else STATUS_DEGRADED
        record["detail"] = "" if method == "HEAD" else "empty response body"
        return record

    record["stage"] = "content_type"
    if expect in ("json", "xml") and expect not in content_type:
        # Many Estonian services answer text/plain or text/html for XML. Only
        # treat it as degraded once the body also fails to parse, below.
        record["detail"] = f"content-type {content_type or 'missing'!r} does not state {expect}"

    record["stage"] = "parse"
    if truncated:
        # An exception report is never megabytes long, so skipping that stage is
        # safe. Skipping freshness is not: the endpoint asked to be checked for
        # staleness and silently reporting ok would hide a frozen feed.
        if endpoint.get("freshness_regex"):
            record["status"] = STATUS_DEGRADED
            record["detail"] = (
                f"body truncated at {max_bytes} bytes, freshness could not be checked "
                f"— raise max_bytes for this endpoint"
            )
        else:
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
    exception_text = _find_service_exception(body)
    if exception_text:
        record["status"] = STATUS_DOWN
        record["detail"] = f"OGC service exception: {exception_text}"
        return record

    record["stage"] = "freshness"
    pattern = endpoint.get("freshness_regex")
    if pattern:
        text = body.decode("utf-8", errors="replace")
        # re.findall returns tuples once a pattern has two or more groups and
        # bare strings otherwise, so match objects are used instead.
        raw_stamps = [
            match.group(1) if match.groups() else match.group(0)
            for match in re.finditer(pattern, text)
        ]
        found = [s for s in (_parse_timestamp(r) for r in raw_stamps) if s is not None]
        if not found:
            record["status"] = STATUS_DEGRADED
            record["detail"] = "freshness_regex matched no parseable timestamp"
            return record
        age = (datetime.now(UTC) - max(found)).total_seconds()
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


def looks_like_local_network_failure(
    records: list[dict[str, Any]], hosts: dict[str, str | None]
) -> bool:
    """True when the run looks like OUR network failed rather than the services.

    Every endpoint has to have failed before getting a response, and those
    failures have to span more than one host. A total failure confined to a
    single host is that host being down, and must be reported as such — which
    is the common case here, since most of the inventory sits behind one name.
    Reading it as a local fault would mean an inventory covering one service
    could never raise an alarm for that service going away.

    Two hosts failing at once is genuinely ambiguous, and this errs towards
    blaming ourselves: a false silence costs less than 18 false outages.
    """
    if not records:
        return False
    if not all(r["stage"] in _REACHABILITY_STAGES and r["status"] != STATUS_OK for r in records):
        return False
    failed_hosts = {hosts.get(r["id"]) for r in records}
    failed_hosts.discard(None)
    return len(failed_hosts) >= 2
