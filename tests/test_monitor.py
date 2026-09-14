"""Standard library tests: python -m unittest discover -s tests"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kaur_monitor import check, discover, inventory, report, store


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
    def test_all_unreachable_is_our_fault(self):
        records = [_record("a", "down", 0, "dns"), _record("b", "down", 0, "connect")]
        self.assertTrue(check.looks_like_local_network_failure(records))

    def test_one_success_means_network_is_fine(self):
        records = [_record("a", "down", 0, "dns"), _record("b", "ok", 0, "freshness")]
        self.assertFalse(check.looks_like_local_network_failure(records))

    def test_real_http_failure_is_not_a_network_failure(self):
        records = [_record("a", "down", 0, "http"), _record("b", "down", 0, "http")]
        self.assertFalse(check.looks_like_local_network_failure(records))

    def test_single_endpoint_is_never_conclusive(self):
        self.assertFalse(check.looks_like_local_network_failure([_record("a", "down", 0, "dns")]))


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
        incidents = report._incidents(series)
        self.assertEqual(len(incidents), 1)
        self.assertIsNotNone(incidents[0]["end"])
        self.assertEqual(incidents[0]["worst"], "down")
        self.assertEqual(incidents[0]["checks"], 2)

    def test_ongoing_incident_has_no_end(self):
        series = [_record("a", "ok", 30), _record("a", "down", 10)]
        self.assertIsNone(report._incidents(series)[0]["end"])

    def test_unknown_does_not_start_or_end_an_incident(self):
        series = [_record("a", "ok", 40), _record("a", "unknown", 30), _record("a", "ok", 20)]
        self.assertEqual(report._incidents(series), [])

    def test_down_outranks_degraded_as_worst(self):
        series = [_record("a", "degraded", 30), _record("a", "down", 20)]
        self.assertEqual(report._incidents(series)[0]["worst"], "down")


class Uptime(unittest.TestCase):
    def test_unknown_is_excluded_from_the_denominator(self):
        series = [_record("a", "ok", 30), _record("a", "unknown", 20), _record("a", "down", 10)]
        pct, count = report._uptime(series, store.window_start(1))
        self.assertEqual(count, 2)
        self.assertAlmostEqual(pct, 50.0)

    def test_no_usable_records_yields_none(self):
        pct, count = report._uptime([_record("a", "unknown", 5)], store.window_start(1))
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


class LocalServer(unittest.TestCase):
    """Exercise the full pipeline against a real socket, offline and deterministic."""

    bodies: ClassVar[dict[str, tuple[int, str, bytes]]] = {}
    last_headers: ClassVar[dict[str, str]] = {}

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


class NaiveTimestamps(unittest.TestCase):
    def test_parse_ts_always_returns_aware(self):
        self.assertIsNotNone(store.parse_ts("2026-09-14T10:00:00").tzinfo)

    def test_naive_log_entry_does_not_break_uptime(self):
        series = [{"ts": "2026-09-14T10:00:00", "id": "a", "status": "ok"}]
        report._uptime(series, store.window_start(365000))

    def test_unparseable_ts_is_excluded_from_the_window(self):
        series = [_record("a", "ok", 5), {"ts": "eile", "id": "a", "status": "down"}]
        pct, count = report._uptime(series, store.window_start(1))
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
        self.assertEqual(len(report._incidents(series)), 1)


if __name__ == "__main__":
    unittest.main()
