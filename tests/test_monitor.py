"""Standard library tests: python -m unittest discover -s tests"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kaur_monitor import analysis, check, dashboard, discover, inventory, report, store


def _record(endpoint_id: str, status: str, minutes_ago: int, stage: str = "http") -> dict:
    stamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {
        "ts": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "id": endpoint_id,
        "status": status,
        "stage": stage,
        "detail": "",
    }


class TimestampParsing(unittest.TestCase):
    def test_iso_variants_and_epoch(self):
        cases = [
            "2026-09-14T10:00:00Z",
            "2026-09-14T13:00:00+03:00",
            "2026-09-14T10:00:00",
            "1789307400",
            "1789307400000",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                parsed = check._parse_timestamp(raw)
                self.assertIsNotNone(parsed)
                self.assertIsNotNone(parsed.tzinfo, "naive timestamps must be assumed UTC")

    def test_rejects_garbage(self):
        self.assertIsNone(check._parse_timestamp("eile hommikul"))


class LocalNetworkDetection(unittest.TestCase):
    TWO_HOSTS: ClassVar[dict[str, str]] = {"a": "one.example", "b": "two.example"}
    ONE_HOST: ClassVar[dict[str, str]] = {"a": "one.example", "b": "one.example"}

    def test_unreachable_across_two_hosts_is_probably_our_fault(self):
        records = [_record("a", "down", 0, "dns"), _record("b", "down", 0, "connect")]
        self.assertTrue(check.looks_like_local_network_failure(records, self.TWO_HOSTS))

    def test_a_single_host_going_dark_is_that_host_not_us(self):
        """The whole inventory behind one name must still be able to raise an alarm."""
        records = [_record("a", "down", 0, "connect"), _record("b", "down", 0, "connect")]
        self.assertFalse(check.looks_like_local_network_failure(records, self.ONE_HOST))

    def test_one_success_means_network_is_fine(self):
        records = [_record("a", "down", 0, "dns"), _record("b", "ok", 0, "freshness")]
        self.assertFalse(check.looks_like_local_network_failure(records, self.TWO_HOSTS))

    def test_real_http_failure_is_not_a_network_failure(self):
        records = [_record("a", "down", 0, "http"), _record("b", "down", 0, "http")]
        self.assertFalse(check.looks_like_local_network_failure(records, self.TWO_HOSTS))

    def test_a_lone_endpoint_going_dark_is_reported_not_excused(self):
        self.assertFalse(
            check.looks_like_local_network_failure(
                [_record("a", "down", 0, "dns")], {"a": "one.example"}
            )
        )

    def test_no_records_is_not_a_network_failure(self):
        self.assertFalse(check.looks_like_local_network_failure([], {}))

    def test_unknown_hosts_do_not_count_towards_the_two(self):
        records = [_record("a", "down", 0, "dns"), _record("b", "down", 0, "dns")]
        self.assertFalse(check.looks_like_local_network_failure(records, {"a": "one.example"}))


class CheckEndpoint(unittest.TestCase):
    def test_unresolvable_host_reports_down_without_raising(self):
        result = check.check_endpoint(
            {"id": "x", "url": "https://nope-does-not-exist-abc123.invalid/a"}
        )
        self.assertEqual(result["status"], "down")
        self.assertEqual(result["stage"], "dns")
        self.assertIn("dns", result["detail"])

    def test_malformed_url_is_reported_not_raised(self):
        result = check.check_endpoint({"id": "x", "url": "https:///no-host"})
        self.assertEqual(result["status"], "down")


class Incidents(unittest.TestCase):
    def test_closed_incident_has_start_and_end(self):
        series = [
            _record("a", "ok", 50),
            _record("a", "down", 40),
            _record("a", "down", 30),
            _record("a", "ok", 20),
        ]
        incidents = analysis.incidents(series)
        self.assertEqual(len(incidents), 1)
        self.assertIsNotNone(incidents[0]["end"])
        self.assertEqual(incidents[0]["worst"], "down")
        self.assertEqual(incidents[0]["checks"], 2)

    def test_ongoing_incident_has_no_end(self):
        series = [_record("a", "ok", 30), _record("a", "down", 10)]
        self.assertIsNone(analysis.incidents(series)[0]["end"])

    def test_unknown_does_not_start_or_end_an_incident(self):
        series = [_record("a", "ok", 40), _record("a", "unknown", 30), _record("a", "ok", 20)]
        self.assertEqual(analysis.incidents(series), [])

    def test_down_outranks_degraded_as_worst(self):
        series = [_record("a", "degraded", 30), _record("a", "down", 20)]
        self.assertEqual(analysis.incidents(series)[0]["worst"], "down")


class Uptime(unittest.TestCase):
    def test_unknown_is_excluded_from_the_denominator(self):
        series = [_record("a", "ok", 30), _record("a", "unknown", 20), _record("a", "down", 10)]
        pct, count = analysis.uptime(series, store.window_start(1))
        self.assertEqual(count, 2)
        self.assertAlmostEqual(pct, 50.0)

    def test_no_usable_records_yields_none(self):
        pct, count = analysis.uptime([_record("a", "unknown", 5)], store.window_start(1))
        self.assertIsNone(pct)
        self.assertEqual(count, 0)


class Inventory(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "endpoints.toml"
        tmp.write_text(text, encoding="utf-8")
        return tmp

    def test_duplicate_id_is_rejected(self):
        path = self._write(
            '[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org/1"\n'
            '[[endpoint]]\nid="a"\nname="B"\nurl="https://e.org/2"\n'
        )
        with self.assertRaisesRegex(inventory.InventoryError, "duplicate"):
            inventory.load(path)

    def test_missing_required_key_is_rejected(self):
        path = self._write('[[endpoint]]\nid="a"\nname="A"\n')
        with self.assertRaisesRegex(inventory.InventoryError, "url"):
            inventory.load(path)

    def test_unknown_key_is_rejected_so_typos_surface(self):
        path = self._write('[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\nexpct="json"\n')
        with self.assertRaisesRegex(inventory.InventoryError, "unknown keys"):
            inventory.load(path)

    def test_non_http_url_is_rejected(self):
        path = self._write('[[endpoint]]\nid="a"\nname="A"\nurl="ftp://e.org"\n')
        with self.assertRaisesRegex(inventory.InventoryError, "http"):
            inventory.load(path)

    def test_missing_file_explains_how_to_create_one(self):
        with self.assertRaisesRegex(inventory.InventoryError, "discover|by hand"):
            inventory.load(Path(tempfile.mkdtemp()) / "absent.toml")

    def test_save_load_round_trip_preserves_values(self):
        path = Path(tempfile.mkdtemp()) / "endpoints.toml"
        original = [
            {
                "id": "a",
                "name": 'Quote " and \\ backslash',
                "url": "https://e.org/a",
                "expect": "xml",
                "max_age_s": 3600,
                "enabled": True,
                "verified": False,
                "freshness_regex": r'"ts"\s*:\s*"([^"]+)"',
            }
        ]
        inventory.save(original, path)
        loaded = inventory.load(path)
        self.assertEqual(loaded[0]["name"], original[0]["name"])
        self.assertEqual(loaded[0]["freshness_regex"], original[0]["freshness_regex"])
        self.assertEqual(loaded[0]["max_age_s"], 3600)
        self.assertIs(loaded[0]["verified"], False)

    def test_merge_never_overwrites_a_human_correction(self):
        existing = [{"id": "a", "name": "corrected", "url": "https://right.org", "verified": True}]
        found = [{"id": "a", "name": "raw", "url": "https://wrong.org", "verified": False}]
        merged, added, skipped = inventory.merge(existing, found)
        self.assertEqual((added, skipped), (0, 1))
        self.assertEqual(merged[0]["url"], "https://right.org")

    def test_enabled_only_filters(self):
        entries = [{"id": "a", "enabled": False}, {"id": "b"}, {"id": "c", "enabled": True}]
        self.assertEqual([e["id"] for e in inventory.enabled_only(entries)], ["b", "c"])


class ImportUrls(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "urls.txt"
        tmp.write_text(text, encoding="utf-8")
        return tmp

    def test_skips_comments_blanks_and_non_urls(self):
        path = self._write("# comment\n\nhttps://e.org/a\nnot-a-url\n  \nhttps://e.org/b\n")
        self.assertEqual(len(discover.from_urls(path)), 2)

    def test_label_after_url_becomes_the_name(self):
        entries = discover.from_urls(self._write("https://e.org/wfs   EELIS WFS\n"))
        self.assertEqual(entries[0]["name"], "EELIS WFS")

    def test_ids_are_unique_even_for_similar_urls(self):
        path = self._write("https://e.org/a\nhttps://e.org/a\nhttps://e.org/a\n")
        ids = [e["id"] for e in discover.from_urls(path)]
        self.assertEqual(len(set(ids)), 3)

    def test_imported_entries_are_never_pre_verified(self):
        entries = discover.from_urls(self._write("https://e.org/a\n"))
        self.assertIs(entries[0]["verified"], False)

    def test_expect_is_inferred_from_the_url(self):
        entries = discover.from_urls(
            self._write("https://e.org/x?service=WFS\nhttps://e.org/y.json\nhttps://e.org/z\n")
        )
        self.assertEqual([e["expect"] for e in entries], ["xml", "json", "any"])

    def test_estonian_characters_are_transliterated_into_the_id(self):
        entries = discover.from_urls(self._write("https://e.org/a   Õhuseire jääm\n"))
        self.assertRegex(entries[0]["id"], r"^[a-z0-9-]+$")


class ServiceExceptionDetection(unittest.TestCase):
    def test_ows_exception_report_is_detected(self):
        body = (
            b'<?xml version="1.0"?>'
            b'<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">'
            b'<ows:Exception exceptionCode="InvalidParameterValue">'
            b"<ows:ExceptionText>Unknown typeName</ows:ExceptionText>"
            b"</ows:Exception></ows:ExceptionReport>"
        )
        self.assertIn("Unknown typeName", check._find_service_exception(body))

    def test_legacy_service_exception_report_is_detected(self):
        body = (
            b"<ServiceExceptionReport>"
            b"<ServiceException>Boom</ServiceException>"
            b"</ServiceExceptionReport>"
        )
        self.assertIsNotNone(check._find_service_exception(body))

    def test_ordinary_capabilities_document_is_not_an_exception(self):
        self.assertIsNone(check._find_service_exception(b"<WFS_Capabilities/>"))

    def test_json_bodies_are_ignored(self):
        self.assertIsNone(check._find_service_exception(b'{"a":1}'))


class NeverRaises(unittest.TestCase):
    """check_endpoint is mapped over every endpoint; one escape loses the run."""

    def test_non_numeric_timeout_becomes_a_result_not_a_crash(self):
        result = check.check_endpoint(
            {"id": "x", "url": "https://e.invalid/a", "timeout_s": "kohe-kohe"}
        )
        self.assertEqual(result["status"], "down")
        self.assertEqual(result["stage"], "config")
        self.assertIn("check aborted", result["detail"])

    def test_aborted_record_has_the_full_log_schema(self):
        result = check.check_endpoint({"id": "x", "url": "https://e.invalid", "max_bytes": "big"})
        for key in ("ts", "id", "status", "stage", "http", "ms", "bytes", "sha256", "age_s"):
            self.assertIn(key, result)


class CertCacheTest(unittest.TestCase):
    """One TLS-expiry probe per host per run, not one per endpoint."""

    def test_a_host_is_only_probed_once(self):
        cache = check.CertCache()
        with mock.patch("kaur_monitor.check._tls_expiry_days", return_value=42) as probe:
            first = cache.get("example.org", 443, 5.0)
            second = cache.get("example.org", 443, 5.0)
        self.assertEqual((first, second), (42, 42))
        probe.assert_called_once_with("example.org", 443, 5.0)

    def test_different_hosts_are_probed_separately(self):
        cache = check.CertCache()
        with mock.patch("kaur_monitor.check._tls_expiry_days", side_effect=[10, 20]):
            self.assertEqual(cache.get("a.example", 443, 5.0), 10)
            self.assertEqual(cache.get("b.example", 443, 5.0), 20)


class RetryOnFailure(unittest.TestCase):
    """A single blip must not become a logged outage by itself."""

    def test_retry_is_off_by_default(self):
        with mock.patch("kaur_monitor.check.time.sleep") as sleep:
            result = check.check_endpoint({"id": "x", "url": "https://nope.invalid/a"})
        sleep.assert_not_called()
        self.assertEqual(result.get("attempts"), 1)

    def test_a_failure_is_rechecked_once_before_being_returned(self):
        calls = 0

        def fake_safe_check(endpoint, cache):
            nonlocal calls
            calls += 1
            return {"id": "x", "status": check.STATUS_DOWN, "attempts": 1}

        with (
            mock.patch("kaur_monitor.check._safe_check", side_effect=fake_safe_check),
            mock.patch("kaur_monitor.check.time.sleep") as sleep,
        ):
            result = check.check_endpoint(
                {"id": "x", "url": "https://nope.invalid/a"}, retry=True, retry_delay_s=5.0
            )
        self.assertEqual(calls, 2)
        sleep.assert_called_once_with(5.0)
        self.assertEqual(result["attempts"], 2)

    def test_a_success_is_never_rechecked(self):
        calls = 0

        def fake_safe_check(endpoint, cache):
            nonlocal calls
            calls += 1
            return {"id": "x", "status": check.STATUS_OK, "attempts": 1}

        with (
            mock.patch("kaur_monitor.check._safe_check", side_effect=fake_safe_check),
            mock.patch("kaur_monitor.check.time.sleep") as sleep,
        ):
            result = check.check_endpoint({"id": "x", "url": "https://ok.invalid/a"}, retry=True)
        self.assertEqual(calls, 1)
        sleep.assert_not_called()
        self.assertEqual(result["attempts"], 1)


class LocalServer(unittest.TestCase):
    """Exercise the full pipeline against a real socket, offline and deterministic."""

    bodies: ClassVar[dict[str, tuple[int, str, bytes]]] = {}
    last_headers: ClassVar[dict[str, str]] = {}
    last_body: ClassVar[bytes] = b""

    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        outer = cls

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.last_headers = dict(self.headers.items())
                status, ctype, body = outer.bodies.get(self.path, (404, "text/plain", b"not found"))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.last_body = self.rfile.read(length) if length else b""
                self.do_GET()

            def do_HEAD(self):
                status, ctype, _ = outer.bodies.get(self.path, (404, "text/plain", b""))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    @staticmethod
    def _iso(seconds_ago: int) -> str:
        return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_multi_group_freshness_regex_does_not_abort_the_run(self):
        """re.findall returns tuples past one group; that used to raise."""
        self.bodies["/multi"] = (
            200,
            "application/json",
            f'{{"t":"{self._iso(30)}","src":"kese"}}'.encode(),
        )
        result = check.check_endpoint(
            {
                "id": "multi",
                "url": f"{self.base}/multi",
                "expect": "json",
                # Two capture groups: the old code passed re.findall's tuples
                # straight into the timestamp parser and raised AttributeError.
                "freshness_regex": r'"t":"([^"]+)","src":"([^"]+)"',
                "max_age_s": 3600,
            }
        )
        self.assertNotEqual(result["stage"], "config", "the check must not abort")
        self.assertEqual(result["status"], "ok")
        self.assertLess(result["age_s"], 120)

    def test_zero_group_freshness_regex_uses_the_whole_match(self):
        self.bodies["/zero"] = (200, "application/json", f'{{"t":"{self._iso(10)}"}}'.encode())
        result = check.check_endpoint(
            {
                "id": "zero",
                "url": f"{self.base}/zero",
                "expect": "json",
                "freshness_regex": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                "max_age_s": 3600,
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertLess(result["age_s"], 120)

    def test_stale_payload_is_degraded(self):
        self.bodies["/stale"] = (
            200,
            "application/json",
            f'{{"t":"{self._iso(90000)}"}}'.encode(),
        )
        result = check.check_endpoint(
            {
                "id": "stale",
                "url": f"{self.base}/stale",
                "expect": "json",
                "freshness_regex": r'"t":"([^"]+)"',
                "max_age_s": 3600,
            }
        )
        self.assertEqual(result["status"], "degraded")
        self.assertIn("stale", result["detail"])

    def test_exception_report_is_caught_even_when_expect_is_any(self):
        self.bodies["/ows"] = (
            200,
            "text/html",
            b'<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">'
            b"<ows:Exception><ows:ExceptionText>Layer gone</ows:ExceptionText>"
            b"</ows:Exception></ows:ExceptionReport>",
        )
        result = check.check_endpoint({"id": "ows", "url": f"{self.base}/ows"})
        self.assertEqual(result["status"], "down")
        self.assertIn("Layer gone", result["detail"])

    def test_truncated_body_with_freshness_configured_is_degraded(self):
        self.bodies["/big"] = (200, "application/json", b'{"pad":"' + b"x" * 5000 + b'"}')
        result = check.check_endpoint(
            {
                "id": "big",
                "url": f"{self.base}/big",
                "expect": "json",
                "max_bytes": 500,
                "freshness_regex": r'"t":"([^"]+)"',
                "max_age_s": 3600,
            }
        )
        self.assertEqual(result["status"], "degraded")
        self.assertIn("max_bytes", result["detail"])

    def test_truncated_body_without_freshness_stays_ok(self):
        self.bodies["/big2"] = (200, "application/json", b'{"pad":"' + b"x" * 5000 + b'"}')
        result = check.check_endpoint(
            {"id": "big2", "url": f"{self.base}/big2", "expect": "json", "max_bytes": 500}
        )
        self.assertEqual(result["status"], "ok")

    def test_invalid_json_is_degraded_not_down(self):
        self.bodies["/bad"] = (200, "application/json", b"{not json")
        result = check.check_endpoint({"id": "bad", "url": f"{self.base}/bad", "expect": "json"})
        self.assertEqual(result["status"], "degraded")

    def test_head_request_with_empty_body_is_ok(self):
        self.bodies["/head"] = (200, "text/plain", b"")
        result = check.check_endpoint({"id": "head", "url": f"{self.base}/head", "method": "HEAD"})
        self.assertEqual(result["status"], "ok")

    def test_empty_body_on_get_is_degraded(self):
        self.bodies["/empty"] = (200, "text/plain", b"")
        result = check.check_endpoint({"id": "empty", "url": f"{self.base}/empty"})
        self.assertEqual(result["status"], "degraded")

    def test_http_error_body_is_captured_in_the_detail(self):
        """The error body is usually the only thing that says what is wrong."""
        self.bodies["/406"] = (
            406,
            "application/json",
            b'{"message":"The schema must be one of the following: public, api"}',
        )
        result = check.check_endpoint({"id": "e406", "url": f"{self.base}/406"})
        self.assertEqual(result["status"], "down")
        self.assertEqual(result["http"], 406)
        self.assertIn("schema must be one of", result["detail"])

    def test_error_body_snippet_is_bounded_and_single_line(self):
        self.bodies["/big-err"] = (500, "text/plain", b"line one\nline two\n" + b"z" * 5000)
        result = check.check_endpoint({"id": "e500", "url": f"{self.base}/big-err"})
        self.assertNotIn("\n", result["detail"])
        self.assertLess(len(result["detail"]), 400)

    def test_configured_headers_reach_the_server(self):
        """PostgREST needs Accept-Profile to select the right schema."""
        self.bodies["/hdr"] = (200, "application/json", b"[]")
        check.check_endpoint(
            {
                "id": "hdr",
                "url": f"{self.base}/hdr",
                "expect": "json",
                "headers": {"Accept-Profile": "apijahialad", "Accept": "application/json"},
            }
        )
        self.assertEqual(self.last_headers.get("Accept-Profile"), "apijahialad")
        self.assertEqual(self.last_headers.get("Accept"), "application/json")

    def test_configured_headers_override_the_defaults(self):
        self.bodies["/hdr2"] = (200, "application/json", b"[]")
        check.check_endpoint(
            {"id": "hdr2", "url": f"{self.base}/hdr2", "headers": {"Accept": "text/csv"}}
        )
        self.assertEqual(self.last_headers.get("Accept"), "text/csv")

    def test_user_agent_is_sent_when_no_headers_configured(self):
        self.bodies["/ua"] = (200, "application/json", b"[]")
        check.check_endpoint({"id": "ua", "url": f"{self.base}/ua"})
        self.assertIn("KAUR-API-monitor", self.last_headers.get("User-Agent", ""))

    def test_post_body_reaches_the_server(self):
        """KAIA's document search is a read, but only reachable by POST."""
        self.bodies["/query"] = (200, "application/json", b'{"numFound":0}')
        result = check.check_endpoint(
            {
                "id": "q",
                "url": f"{self.base}/query",
                "method": "POST",
                "expect": "json",
                "body": '{"pageSize":1}',
            }
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.last_body, b'{"pageSize":1}')

    def test_body_sets_a_json_content_type_by_default(self):
        self.bodies["/ct"] = (200, "application/json", b"{}")
        check.check_endpoint({"id": "ct", "url": f"{self.base}/ct", "method": "POST", "body": "{}"})
        self.assertEqual(self.last_headers.get("Content-Type"), "application/json")

    def test_an_explicit_content_type_wins_over_the_default(self):
        self.bodies["/ct2"] = (200, "application/json", b"{}")
        check.check_endpoint(
            {
                "id": "ct2",
                "url": f"{self.base}/ct2",
                "method": "POST",
                "body": "a=1",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            }
        )
        self.assertEqual(self.last_headers.get("Content-Type"), "application/x-www-form-urlencoded")

    def test_a_get_without_a_body_sends_none(self):
        self.bodies["/nobody"] = (200, "application/json", b"{}")
        self.last_body = b"sentinel"
        check.check_endpoint({"id": "nb", "url": f"{self.base}/nobody"})
        self.assertEqual(self.last_body, b"sentinel", "GET must not have posted a body")


class SafeMethods(unittest.TestCase):
    """A monitor runs unattended; it must never be configurable to write."""

    def _write(self, method: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "endpoints.toml"
        tmp.write_text(
            f'[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\nmethod="{method}"\n',
            encoding="utf-8",
        )
        return tmp

    def test_write_methods_are_refused(self):
        for method in ("PUT", "PATCH", "DELETE", "put"):
            with self.subTest(method=method):
                with self.assertRaisesRegex(inventory.InventoryError, "can change state"):
                    inventory.load(self._write(method))

    def test_read_methods_are_allowed(self):
        for method in ("GET", "HEAD", "POST", "OPTIONS", "get"):
            with self.subTest(method=method):
                self.assertEqual(len(inventory.load(self._write(method))), 1)


class RequestBodies(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "endpoints.toml"
        tmp.write_text(text, encoding="utf-8")
        return tmp

    def test_malformed_json_body_is_rejected_before_it_ever_runs(self):
        path = self._write(
            '[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\nmethod="POST"\nbody="{not json"\n'
        )
        with self.assertRaisesRegex(inventory.InventoryError, "does not parse"):
            inventory.load(path)

    def test_a_non_json_body_is_left_alone(self):
        path = self._write(
            '[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\nmethod="POST"\nbody="a=1&b=2"\n'
        )
        self.assertEqual(inventory.load(path)[0]["body"], "a=1&b=2")

    def test_non_string_body_is_rejected(self):
        path = self._write('[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\nbody=7\n')
        with self.assertRaisesRegex(inventory.InventoryError, "body must be a string"):
            inventory.load(path)

    def test_body_survives_the_toml_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "endpoints.toml"
        body = '{"pageSize":1,"includeFileMetadata":false}'
        inventory.save(
            [{"id": "a", "name": "A", "url": "https://e.org", "method": "POST", "body": body}],
            path,
        )
        self.assertEqual(inventory.load(path)[0]["body"], body)


class OpenApiDiscovery(unittest.TestCase):
    """PostgREST documents its own tables; discovery must read them, not guess."""

    spec: ClassVar[bytes] = json.dumps(
        {
            "swagger": "2.0",
            "paths": {
                "/": {"get": {}},
                "/f_rahvalad": {"get": {"summary": "Rahvusvahelised alad"}},
                "/f_rahvalad_dok": {"get": {}},
                "/f_kliima_paev": {"get": {}},
                "/f_hydroseire": {"get": {}},
                "/rpc/some_function": {"post": {}},
                "/other_table": {"get": {}},
            },
        }
    ).encode()

    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        outer = cls

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.last_headers = dict(self.headers.items())
                # Anything but the root is a document with no "paths" key at
                # all, which is a different failure from one with no matches.
                body = outer.spec if self.path == "/" else b'{"swagger":"2.0"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    last_headers: ClassVar[dict[str, str]] = {}

    def test_finds_prefixed_tables_only(self):
        ids = [e["id"] for e in discover.from_openapi(self.base)]
        self.assertEqual(ids, ["f-hydroseire", "f-kliima-paev", "f-rahvalad", "f-rahvalad-dok"])

    def test_skips_the_root_and_stored_procedures(self):
        urls = [e["url"] for e in discover.from_openapi(self.base)]
        self.assertFalse(any("rpc/" in u for u in urls))
        self.assertTrue(all(u != self.base for u in urls))

    def test_empty_prefix_includes_unprefixed_tables(self):
        ids = [e["id"] for e in discover.from_openapi(self.base, table_prefix="")]
        self.assertIn("other-table", ids)

    def test_row_limit_is_applied_to_every_url(self):
        for entry in discover.from_openapi(self.base, row_limit=3):
            self.assertTrue(entry["url"].endswith("?limit=3"))

    def test_summary_becomes_the_name_when_present(self):
        by_id = {e["id"]: e for e in discover.from_openapi(self.base)}
        self.assertEqual(by_id["f-rahvalad"]["name"], "Rahvusvahelised alad")
        self.assertEqual(by_id["f-rahvalad-dok"]["name"], "f_rahvalad_dok")

    def test_system_is_inferred_from_the_table_prefix(self):
        by_id = {e["id"]: e for e in discover.from_openapi(self.base)}
        self.assertEqual(by_id["f-kliima-paev"]["system"], "Kliima")
        self.assertEqual(by_id["f-hydroseire"]["system"], "Hüdroloogia")
        self.assertEqual(by_id["f-rahvalad"]["system"], "EELIS")

    def test_headers_are_sent_and_stored_on_each_entry(self):
        entries = discover.from_openapi(self.base, extra_headers={"Accept-Profile": "apijahiala"})
        self.assertEqual(self.last_headers.get("Accept-Profile"), "apijahiala")
        self.assertEqual(entries[0]["headers"]["Accept-Profile"], "apijahiala")

    def test_nothing_is_ever_marked_verified(self):
        self.assertTrue(all(e["verified"] is False for e in discover.from_openapi(self.base)))

    def test_a_document_without_paths_is_rejected_not_guessed(self):
        with self.assertRaisesRegex(discover.DiscoveryError, "not an OpenAPI document"):
            discover.from_openapi(f"{self.base}/not-root")

    def test_a_prefix_matching_nothing_is_reported(self):
        with self.assertRaisesRegex(discover.DiscoveryError, "no table paths"):
            discover.from_openapi(self.base, table_prefix="zzz_")


class LogWindowing(unittest.TestCase):
    """Reading must stay cheap as the log grows, or the 15-minute job will not."""

    def setUp(self):
        self._original = store.LOG_DIR
        store.LOG_DIR = Path(tempfile.mkdtemp())

    def tearDown(self):
        store.LOG_DIR = self._original

    def _write(self, name: str, records: list[dict]) -> None:
        (store.LOG_DIR / name).write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )

    def test_a_month_file_outside_the_window_is_never_opened(self):
        """Proved by content that WOULD match if the file were read at all."""
        recent = _record("a", "ok", 5)
        self._write("2020-01.jsonl", [dict(recent, id="ancient")])
        self._write(f"{datetime.now(UTC):%Y-%m}.jsonl", [recent])
        ids = [r["id"] for r in store.read_all(since=store.window_start(1))]
        self.assertEqual(ids, ["a"], "the 2020 file was read despite being out of window")

    def test_without_a_window_every_month_is_read(self):
        self._write("2020-01.jsonl", [_record("ancient", "ok", 5)])
        self._write(f"{datetime.now(UTC):%Y-%m}.jsonl", [_record("a", "ok", 5)])
        self.assertEqual(len(list(store.read_all())), 2)

    def test_a_file_with_an_unparseable_name_is_still_read(self):
        self._write("backup.jsonl", [_record("a", "ok", 5)])
        self.assertEqual(len(list(store.read_all(since=store.window_start(1)))), 1)

    def test_records_older_than_the_window_inside_a_current_file_are_dropped(self):
        self._write(
            f"{datetime.now(UTC):%Y-%m}.jsonl",
            [_record("a", "ok", 5), _record("b", "ok", 60 * 24 * 40)],
        )
        ids = [r["id"] for r in store.read_all(since=store.window_start(1))]
        self.assertEqual(ids, ["a"])

    def test_corrupt_lines_are_skipped_not_fatal(self):
        path = store.LOG_DIR / f"{datetime.now(UTC):%Y-%m}.jsonl"
        path.write_text(json.dumps(_record("a", "ok", 5)) + "\n{truncated\n\n", encoding="utf-8")
        self.assertEqual(len(list(store.read_all())), 1)

    def test_the_report_only_counts_records_inside_its_window(self):
        self._write(
            f"{datetime.now(UTC):%Y-%m}.jsonl",
            [_record("a", "ok", 5), _record("a", "ok", 60 * 24 * 40)],
        )
        text = report.build([{"id": "a", "name": "A", "url": "https://e.org", "verified": True}])
        self.assertIn("**1**", text)
        self.assertIn("31 päeva jooksul", text)


class GroupCollapsing(unittest.TestCase):
    """261 EELIS tables are one thing to a reader and one line to the log."""

    GROUP: ClassVar[dict[str, str]] = {"a": "g", "b": "g", "c": "g"}

    def test_all_members_ok_makes_the_group_ok(self):
        records = [dict(_record(i, "ok", 1), ms=100) for i in "abc"]
        [row] = analysis.collapse_groups(records, self.GROUP)
        self.assertEqual(row["id"], "g")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["members"], 3)
        self.assertEqual(row["ok"], 3)
        self.assertEqual(row["detail"], "")

    def test_one_member_down_takes_the_whole_group_down(self):
        records = [
            dict(_record("a", "ok", 1), ms=100),
            dict(_record("b", "down", 1), ms=None, detail="http 500 Server Error"),
            dict(_record("c", "ok", 1), ms=200),
        ]
        [row] = analysis.collapse_groups(records, self.GROUP)
        self.assertEqual(row["status"], "down")
        self.assertEqual(row["ok"], 2)
        self.assertIn("1/3 ei vasta", row["detail"])
        self.assertIn("b", row["detail"])
        self.assertIn("http 500", row["detail"])

    def test_degraded_loses_to_down_but_beats_ok(self):
        records = [dict(_record("a", "ok", 1)), dict(_record("b", "degraded", 1))]
        [row] = analysis.collapse_groups(records, {"a": "g", "b": "g"})
        self.assertEqual(row["status"], "degraded")

    def test_a_group_is_unknown_only_when_every_member_is(self):
        allu = [dict(_record(i, "unknown", 1)) for i in "abc"]
        self.assertEqual(analysis.collapse_groups(allu, self.GROUP)[0]["status"], "unknown")
        mixed = [dict(_record("a", "unknown", 1)), dict(_record("b", "ok", 1))]
        self.assertEqual(analysis.collapse_groups(mixed, {"a": "g", "b": "g"})[0]["status"], "ok")

    def test_many_failures_are_summarised_not_dumped(self):
        records = [dict(_record(f"e{i}", "down", 1), detail="boom") for i in range(20)]
        [row] = analysis.collapse_groups(records, {f"e{i}": "g" for i in range(20)})
        self.assertIn("20/20 ei vasta", row["detail"])
        self.assertIn("ja veel 15", row["detail"])
        self.assertLessEqual(len(row["detail"]), 300)

    def test_ungrouped_records_pass_through_untouched(self):
        records = [dict(_record("a", "ok", 1), ms=1), dict(_record("solo", "down", 1))]
        out = analysis.collapse_groups(records, {"a": "g"})
        self.assertEqual({r["id"] for r in out}, {"g", "solo"})

    def test_no_groups_configured_changes_nothing(self):
        records = [dict(_record("a", "ok", 1))]
        self.assertIs(analysis.collapse_groups(records, {}), records)

    def test_the_group_carries_a_typical_latency_and_the_worst_certificate(self):
        records = [
            dict(_record("a", "ok", 1), ms=100, cert_days=90),
            dict(_record("b", "ok", 1), ms=200, cert_days=10),
            dict(_record("c", "ok", 1), ms=300, cert_days=50),
        ]
        [row] = analysis.collapse_groups(records, self.GROUP)
        self.assertEqual(row["ms"], 200)
        self.assertEqual(row["cert_days"], 10)


class Units(unittest.TestCase):
    def _entries(self) -> list[dict]:
        return [
            {"id": "solo", "name": "Solo", "url": "https://e.org/s", "system": "Kliima"},
            {
                "id": "a",
                "name": "A",
                "url": "https://e.org/a?limit=1",
                "system": "EELIS",
                "group": "eelis",
                "verified": False,
            },
            {
                "id": "b",
                "name": "B",
                "url": "https://e.org/b?limit=1",
                "system": "EELIS",
                "group": "eelis",
                "verified": False,
            },
        ]

    def test_a_group_becomes_one_unit_named_by_the_group(self):
        groups = [{"id": "eelis", "name": "EELIS andmestikud", "system": "EELIS", "verified": True}]
        units = inventory.units(self._entries(), groups)
        self.assertEqual(len(units), 2)
        group_unit = next(u for u in units if u["id"] == "eelis")
        self.assertEqual(group_unit["name"], "EELIS andmestikud")
        self.assertEqual(group_unit["members"], 2)

    def test_the_group_decides_its_own_verified_flag_not_its_members(self):
        """Members are unverified queries; the aggregate was confirmed to work."""
        groups = [{"id": "eelis", "name": "EELIS", "verified": True}]
        unit = next(u for u in inventory.units(self._entries(), groups) if u["id"] == "eelis")
        self.assertTrue(unit["verified"])

    def test_a_group_with_no_definition_still_yields_a_usable_unit(self):
        unit = next(u for u in inventory.units(self._entries(), []) if u["id"] == "eelis")
        self.assertEqual(unit["name"], "eelis")
        self.assertEqual(unit["system"], "EELIS")

    def test_endpoints_naming_a_missing_group_are_rejected(self):
        path = Path(tempfile.mkdtemp()) / "endpoints.toml"
        path.write_text(
            '[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\ngroup="nope"\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(inventory.InventoryError, "no \\[\\[group\\]\\] entry"):
            inventory.load(path)


class InventoryRewriting(unittest.TestCase):
    """A discovery run rewrites this file; it must not eat what a human wrote."""

    def test_comments_above_the_first_table_survive_a_rewrite(self):
        path = Path(tempfile.mkdtemp()) / "endpoints.toml"
        path.write_text(
            "# Do not correct the header value back.\n# It is wrong in the docs.\n\n"
            '[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\n',
            encoding="utf-8",
        )
        inventory.save(inventory.load(path), path)
        after = path.read_text(encoding="utf-8")
        self.assertIn("Do not correct the header value back.", after)
        self.assertIn("It is wrong in the docs.", after)

    def test_groups_survive_a_rewrite(self):
        path = Path(tempfile.mkdtemp()) / "endpoints.toml"
        inventory.save(
            [{"id": "a", "name": "A", "url": "https://e.org", "group": "g"}],
            path,
            groups=[{"id": "g", "name": "Group", "verified": True}],
        )
        inventory.save(inventory.load(path), path)
        groups = inventory.load_groups(path)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["name"], "Group")

    def test_a_group_needs_a_name(self):
        path = Path(tempfile.mkdtemp()) / "endpoints.toml"
        path.write_text('[[group]]\nid="g"\n', encoding="utf-8")
        with self.assertRaisesRegex(inventory.InventoryError, "needs both"):
            inventory.load_groups(path)


class DashboardData(unittest.TestCase):
    """The page draws exactly this file, so an error here is an error in public."""

    def setUp(self):
        self._log = store.LOG_DIR
        store.LOG_DIR = Path(tempfile.mkdtemp())

    def tearDown(self):
        store.LOG_DIR = self._log

    def _write(self, records: list[dict]) -> None:
        (store.LOG_DIR / f"{datetime.now(UTC):%Y-%m}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _entry(eid: str, system: str = "Kliima") -> dict:
        return {"id": eid, "name": eid.upper(), "url": "https://e.org/x", "system": system}

    def test_an_endpoint_with_no_checks_reads_as_unchecked_not_broken(self):
        data = dashboard.build([self._entry("a")])
        self.assertEqual(data["endpoints"][0]["status"], "unchecked")
        self.assertIsNone(data["endpoints"][0]["avail_24h"])
        self.assertEqual(data["totals"]["unchecked"], 1)

    def test_no_log_produces_empty_series_rather_than_invented_ones(self):
        data = dashboard.build([self._entry("a")])
        self.assertEqual(data["daily"], [])
        self.assertEqual(data["incidents"], [])
        self.assertEqual(data["outages_by_endpoint"], [])
        self.assertIsNone(data["first_record"])
        self.assertIsNone(data["availability"]["h24"])

    def test_availability_counts_only_real_outcomes(self):
        self._write(
            [
                dict(_record("a", "ok", 10), ms=100),
                dict(_record("a", "down", 20), ms=None),
                _record("a", "unknown", 30),
            ]
        )
        data = dashboard.build([self._entry("a")])
        self.assertAlmostEqual(data["endpoints"][0]["avail_24h"], 50.0)
        self.assertEqual(data["endpoints"][0]["checks_24h"], 2)

    def test_daily_rows_skip_unknown_and_carry_latency_percentiles(self):
        self._write(
            [dict(_record("a", "ok", 5 + i), ms=100 * (i + 1)) for i in range(10)]
            + [_record("a", "unknown", 6)]
        )
        data = dashboard.build([self._entry("a")])
        self.assertEqual(len(data["daily"]), 1)
        row = data["daily"][0]
        self.assertEqual(row["checks"], 10)
        self.assertEqual(row["avail_pct"], 100.0)
        self.assertIsNotNone(row["p50_ms"])
        self.assertGreaterEqual(row["p95_ms"], row["p50_ms"])

    def test_a_day_without_checks_is_absent_rather_than_zero(self):
        """A zero-availability row would read as a total outage that never happened."""
        self._write([dict(_record("a", "ok", 5), ms=100)])
        dates = [r["date"] for r in dashboard.build([self._entry("a")])["daily"]]
        self.assertEqual(len(dates), 1)

    def test_systems_are_grouped_and_described(self):
        self._write([dict(_record("a", "ok", 5), ms=100), dict(_record("b", "down", 5), ms=None)])
        data = dashboard.build([self._entry("a", "Kliima"), self._entry("b", "EELIS")])
        systems = {s["name"]: s for s in data["systems"]}
        self.assertEqual(systems["Kliima"]["ok"], 1)
        self.assertEqual(systems["EELIS"]["problem"], 1)
        self.assertTrue(
            systems["EELIS"]["description"], "config/systems.toml should describe EELIS"
        )

    def test_outages_are_listed_and_counted_per_endpoint(self):
        self._write(
            [
                _record("a", "ok", 60),
                _record("a", "down", 50),
                _record("a", "ok", 40),
                _record("a", "down", 30),
                _record("a", "ok", 20),
            ]
        )
        data = dashboard.build([self._entry("a")])
        self.assertEqual(len(data["incidents"]), 2)
        self.assertEqual(data["outages_by_endpoint"][0]["count"], 2)
        self.assertTrue(all(i["duration_s"] is not None for i in data["incidents"]))

    def test_written_file_is_valid_json_and_utf8(self):
        self._write([dict(_record("a", "ok", 5), ms=100)])
        target = Path(tempfile.mkdtemp()) / "status.json"
        dashboard.write([self._entry("a", "Hüdroloogia")], target)
        parsed = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(parsed["endpoints"][0]["id"], "a")
        self.assertIn("Hüdroloogia", target.read_text(encoding="utf-8"))

    def test_percentiles_of_one_value(self):
        self.assertEqual(dashboard._percentile([7], 0.95), 7)
        self.assertIsNone(dashboard._percentile([], 0.5))

    def test_unverified_endpoints_are_flagged_for_the_page(self):
        """The page must not lend an unconfirmed URL the same authority as a
        verified one — see REPORT.md's own 'Hoiatused' section."""
        verified = {**self._entry("a"), "verified": True}
        unverified = {**self._entry("b"), "verified": False}
        data = dashboard.build([verified, unverified])
        by_id = {e["id"]: e for e in data["endpoints"]}
        self.assertTrue(by_id["a"]["verified"])
        self.assertFalse(by_id["b"]["verified"])
        self.assertEqual(data["totals"]["unverified"], 1)


class IncidentDuration(unittest.TestCase):
    def test_closed_incident_measures_start_to_end(self):
        incident = {"start": "2026-09-01T00:00:00Z", "end": "2026-09-01T01:00:00Z"}
        self.assertEqual(analysis.duration_seconds(incident, datetime.now(UTC)), 3600)

    def test_open_incident_measures_to_now(self):
        start = datetime.now(UTC) - timedelta(minutes=30)
        incident = {"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": None}
        seconds = analysis.duration_seconds(incident, datetime.now(UTC))
        self.assertGreater(seconds, 1700)
        self.assertLess(seconds, 1900)

    def test_unparseable_start_yields_no_duration(self):
        self.assertIsNone(
            analysis.duration_seconds({"start": "eile", "end": None}, datetime.now(UTC))
        )


class NaiveTimestamps(unittest.TestCase):
    def test_parse_ts_always_returns_aware(self):
        self.assertIsNotNone(store.parse_ts("2026-09-14T10:00:00").tzinfo)

    def test_naive_log_entry_does_not_break_uptime(self):
        series = [{"ts": "2026-09-14T10:00:00", "id": "a", "status": "ok"}]
        analysis.uptime(series, store.window_start(365000))

    def test_unparseable_ts_is_excluded_from_the_window(self):
        series = [_record("a", "ok", 5), {"ts": "eile", "id": "a", "status": "down"}]
        pct, count = analysis.uptime(series, store.window_start(1))
        self.assertEqual(count, 1)
        self.assertAlmostEqual(pct, 100.0)


class ConfigValidation(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "endpoints.toml"
        tmp.write_text(text, encoding="utf-8")
        return tmp

    def test_uncompilable_regex_is_rejected(self):
        path = self._write(
            '[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\nfreshness_regex="([unclosed"\n'
        )
        with self.assertRaisesRegex(inventory.InventoryError, "freshness_regex"):
            inventory.load(path)

    def test_non_numeric_timeout_is_rejected(self):
        path = self._write('[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\ntimeout_s="30"\n')
        with self.assertRaisesRegex(inventory.InventoryError, "timeout_s"):
            inventory.load(path)

    def test_missing_file_is_empty_not_an_error_for_the_scheduled_check(self):
        self.assertEqual(inventory.load_or_empty(Path(tempfile.mkdtemp()) / "absent.toml"), [])

    def test_malformed_file_still_raises(self):
        path = self._write('[[endpoint]]\nid="a"\n')
        with self.assertRaises(inventory.InventoryError):
            inventory.load_or_empty(path)

    def test_headers_are_accepted_and_parsed(self):
        path = self._write(
            '[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\n'
            'headers = { "Accept-Profile" = "apijahialad" }\n'
        )
        self.assertEqual(inventory.load(path)[0]["headers"]["Accept-Profile"], "apijahialad")

    def test_non_string_header_value_is_rejected(self):
        path = self._write(
            '[[endpoint]]\nid="a"\nname="A"\nurl="https://e.org"\nheaders = { "X" = 7 }\n'
        )
        with self.assertRaisesRegex(inventory.InventoryError, "must be a string"):
            inventory.load(path)

    def test_headers_survive_the_toml_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "endpoints.toml"
        inventory.save(
            [
                {
                    "id": "a",
                    "name": "A",
                    "url": "https://e.org",
                    "headers": {"Accept-Profile": "apijahialad", "Accept": "application/json"},
                }
            ],
            path,
        )
        loaded = inventory.load(path)[0]
        self.assertEqual(loaded["headers"]["Accept-Profile"], "apijahialad")
        self.assertEqual(loaded["headers"]["Accept"], "application/json")


class ReportRendering(unittest.TestCase):
    def test_empty_inventory_renders_a_dated_report_rather_than_failing(self):
        text = report.build([])
        self.assertIn("Koostatud", text)
        self.assertIn(datetime.now(UTC).astimezone(report._TALLINN).strftime("%Y-%m-%d"), text)

    def test_incidents_sharing_a_start_do_not_crash_the_sort(self):
        series = [_record("a", "down", 10), _record("a", "down", 10)]
        self.assertEqual(len(analysis.incidents(series)), 1)


if __name__ == "__main__":
    unittest.main()
