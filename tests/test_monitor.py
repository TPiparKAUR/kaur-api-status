"""Standard library tests: python -m unittest discover -s tests"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kaur_monitor import check, discover, inventory, report, store  # noqa: E402


def _record(endpoint_id: str, status: str, minutes_ago: int, stage: str = "http") -> dict:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
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
        self.assertIn("Unknown typeName", check._find_service_exception(body, "xml"))

    def test_legacy_service_exception_report_is_detected(self):
        body = b"<ServiceExceptionReport><ServiceException>Boom</ServiceException></ServiceExceptionReport>"
        self.assertIsNotNone(check._find_service_exception(body, "xml"))

    def test_ordinary_capabilities_document_is_not_an_exception(self):
        self.assertIsNone(check._find_service_exception(b"<WFS_Capabilities/>", "xml"))

    def test_json_bodies_are_ignored(self):
        self.assertIsNone(check._find_service_exception(b'{"a":1}', "json"))


if __name__ == "__main__":
    unittest.main()
