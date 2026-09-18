"""Tests for scripts/notify_issues.py.

This module talks to the GitHub API and to the inventory/log on disk, so every
test here stubs those two boundaries: `_request` never makes a real HTTP call,
and `store.LOG_DIR` points at a throwaway directory. What is under test is the
decision logic — which endpoint gets an Issue opened or closed, and when.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import notify_issues
from kaur_monitor import store


def _record(endpoint_id: str, status: str, minutes_ago: int) -> dict:
    stamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {
        "ts": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "id": endpoint_id,
        "status": status,
        "stage": "http",
        "http": 500 if status != "ok" else 200,
        "ms": 100,
        "detail": "boom" if status != "ok" else "",
    }


class ConsecutiveFailures(unittest.TestCase):
    def test_a_single_failure_does_not_count_as_two(self):
        series = [_record("a", "ok", 60), _record("a", "down", 30)]
        self.assertEqual(notify_issues._consecutive_failures(series), 1)

    def test_two_failures_in_a_row_count_as_two(self):
        series = [_record("a", "down", 60), _record("a", "down", 30)]
        self.assertEqual(notify_issues._consecutive_failures(series), 2)

    def test_unknown_is_skipped_rather_than_breaking_the_streak(self):
        series = [_record("a", "down", 90), _record("a", "unknown", 60), _record("a", "down", 30)]
        self.assertEqual(notify_issues._consecutive_failures(series), 2)

    def test_a_success_resets_the_streak(self):
        series = [_record("a", "down", 90), _record("a", "ok", 60), _record("a", "down", 30)]
        self.assertEqual(notify_issues._consecutive_failures(series), 1)

    def test_empty_series_has_no_streak(self):
        self.assertEqual(notify_issues._consecutive_failures([]), 0)


class BroadOutage(unittest.TestCase):
    """The rule that pages on a wide simultaneous failure without a second check.

    Modelled on run 231 (2026-09-18), where nearly every unit failed inside one
    72-minute run, the next run found everything healthy, and the two-strike
    rule therefore never fired.
    """

    def _latest(self, statuses: list[str]) -> dict[str, dict]:
        return {f"u{i}": _record(f"u{i}", s, 1) for i, s in enumerate(statuses)}

    def test_most_units_failing_at_once_is_broad(self):
        is_broad, failing, checked = notify_issues._broad_outage(
            self._latest(["down"] * 8 + ["ok"] * 2)
        )
        self.assertTrue(is_broad)
        self.assertEqual(len(failing), 8)
        self.assertEqual(checked, 10)

    def test_a_minority_failing_is_not_broad(self):
        is_broad, failing, _ = notify_issues._broad_outage(self._latest(["down"] * 2 + ["ok"] * 8))
        self.assertFalse(is_broad)
        self.assertEqual(len(failing), 2)

    def test_a_handful_of_units_never_counts_as_broad(self):
        """With one unit monitored, 'all of them' is one endpoint, not an event."""
        is_broad, _, _ = notify_issues._broad_outage(self._latest(["down"]))
        self.assertFalse(is_broad)

    def test_unknown_units_are_excluded_from_both_sides(self):
        """'unknown' is our own network. It must neither trip nor mask the rule."""
        is_broad, failing, checked = notify_issues._broad_outage(
            self._latest(["down"] * 6 + ["unknown"] * 20)
        )
        self.assertTrue(is_broad, "20 unknowns must not dilute 6 real failures away")
        self.assertEqual(checked, 6)
        self.assertEqual(len(failing), 6)

    def test_everything_unknown_is_not_an_outage(self):
        is_broad, _, checked = notify_issues._broad_outage(self._latest(["unknown"] * 20))
        self.assertFalse(is_broad)
        self.assertEqual(checked, 0)

    def test_degraded_counts_as_failing(self):
        is_broad, failing, _ = notify_issues._broad_outage(
            self._latest(["degraded"] * 5 + ["down"] * 3 + ["ok"] * 2)
        )
        self.assertTrue(is_broad)
        self.assertEqual(len(failing), 8)


class NotifyMain(unittest.TestCase):
    """Exercise main() end to end with the network and inventory stubbed out."""

    def setUp(self):
        self._log_dir = store.LOG_DIR
        store.LOG_DIR = Path(tempfile.mkdtemp())
        self._env = mock.patch.dict(os.environ, {"GH_TOKEN": "t", "GH_REPO": "o/r"})
        self._env.start()

    def tearDown(self):
        store.LOG_DIR = self._log_dir
        self._env.stop()

    def _write(self, records: list[dict]) -> None:
        path = store.LOG_DIR / f"{datetime.now(UTC):%Y-%m}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    def _units(self, *, group=True):
        """A verified group unit ('eelis') plus one ordinary verified endpoint.

        Mirrors what inventory.units() actually returns, which is the fix for
        the bug where a group's log records could never be found in
        inventory.load()'s flat, ungrouped id list.
        """
        units = [{"id": "solo", "name": "Solo", "url": "https://e.org/s", "verified": True}]
        if group:
            units.append(
                {"id": "eelis", "name": "EELIS", "url": "https://e.org/eelis", "verified": True}
            )
        return units

    def _run(self, *, group=True):
        opened, closed = [], []

        def fake_request(method, path, token, payload=None):
            if method == "POST" and path.endswith("/issues"):
                opened.append(payload)
                return {"number": 1}
            if method == "PATCH":
                closed.append(payload)
            return {}

        with (
            mock.patch("notify_issues.inventory.load", return_value=[]),
            mock.patch("notify_issues.inventory.load_groups", return_value=[]),
            mock.patch("notify_issues.inventory.units", return_value=self._units(group=group)),
            mock.patch("notify_issues._all_open_issues", return_value=[]),
            mock.patch("notify_issues._request", side_effect=fake_request),
        ):
            notify_issues.main()
        return opened, closed

    def test_a_lone_failure_opens_nothing(self):
        self._write([_record("eelis", "down", 10)])
        opened, _ = self._run()
        self.assertEqual(opened, [])

    def _run_units(self, units, open_issues=()):
        """Like _run, but with an arbitrary unit list and pre-existing issues."""
        opened, closed = [], []

        def fake_request(method, path, token, payload=None):
            if method == "POST" and path.endswith("/issues"):
                opened.append(payload)
                return {"number": 1}
            if method == "PATCH":
                closed.append(payload)
            return {}

        with (
            mock.patch("notify_issues.inventory.load", return_value=[]),
            mock.patch("notify_issues.inventory.load_groups", return_value=[]),
            mock.patch("notify_issues.inventory.units", return_value=units),
            mock.patch("notify_issues._all_open_issues", return_value=list(open_issues)),
            mock.patch("notify_issues._request", side_effect=fake_request),
        ):
            notify_issues.main()
        return opened, closed

    def test_one_check_with_everything_down_opens_the_aggregate_issue(self):
        """Regression for run 231, the outage that notified nobody.

        Ten units fail on a single check. None has a second consecutive
        failure, so the per-unit rule stays silent by design — exactly one
        aggregate issue is what pages, not ten.
        """
        ids = [f"u{i}" for i in range(10)]
        self._write([_record(i, "down", 5) for i in ids])
        units = [{"id": i, "name": i, "url": f"https://e.org/{i}", "verified": True} for i in ids]
        opened, _ = self._run_units(units)
        self.assertEqual(len(opened), 1, "one aggregate issue, not one per unit")
        self.assertIn("üldrike", opened[0]["title"])
        self.assertIn(notify_issues.BROAD_ID, opened[0]["body"])
        self.assertIn(notify_issues.LABEL, opened[0]["labels"])

    def test_the_aggregate_issue_covers_unverified_units_too(self):
        """A wrong query explains one unit failing, not ten at once."""
        ids = [f"u{i}" for i in range(10)]
        self._write([_record(i, "down", 5) for i in ids])
        units = [{"id": i, "name": i, "url": f"https://e.org/{i}", "verified": False} for i in ids]
        opened, _ = self._run_units(units)
        self.assertEqual(len(opened), 1)

    def test_the_aggregate_issue_closes_when_the_outage_narrows(self):
        ids = [f"u{i}" for i in range(10)]
        self._write([_record(i, "ok", 5) for i in ids])
        units = [{"id": i, "name": i, "url": f"https://e.org/{i}", "verified": True} for i in ids]
        opened, closed = self._run_units(
            units,
            open_issues=[
                {"number": 3, "body": notify_issues.MARKER.format(id=notify_issues.BROAD_ID)}
            ],
        )
        self.assertEqual(opened, [])
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["state"], "closed")

    def test_the_aggregate_issue_is_not_reopened_while_it_is_open(self):
        ids = [f"u{i}" for i in range(10)]
        self._write([_record(i, "down", 5) for i in ids])
        units = [{"id": i, "name": i, "url": f"https://e.org/{i}", "verified": True} for i in ids]
        opened, closed = self._run_units(
            units,
            open_issues=[
                {"number": 3, "body": notify_issues.MARKER.format(id=notify_issues.BROAD_ID)}
            ],
        )
        self.assertEqual(opened, [])
        self.assertEqual(closed, [])

    def test_a_second_consecutive_failure_opens_an_issue(self):
        self._write([_record("eelis", "down", 40), _record("eelis", "down", 10)])
        opened, _ = self._run()
        self.assertEqual(len(opened), 1)
        self.assertIn("eelis", opened[0]["title"])

    def test_the_group_id_is_resolved_via_units_not_the_flat_endpoint_list(self):
        """Regression test: a group id is not one of inventory.load()'s entries.

        Before the fix, notify_issues looked the group id up in inventory.load()
        directly and found nothing, so it always treated the group as
        unverified and never opened an Issue for it — no matter how long it
        had been failing.
        """
        self._write([_record("eelis", "down", 40), _record("eelis", "down", 10)])
        opened, _ = self._run(group=True)
        self.assertEqual(len(opened), 1, "the group must be able to open an Issue")

    def test_an_open_issue_closes_on_the_first_recovery(self):
        """Recovery is not held to the same two-in-a-row bar as opening.

        A single 'ok' closes an already-open Issue immediately — only opening
        a new one waits for a second consecutive failure.
        """
        self._write([_record("solo", "down", 30), _record("solo", "ok", 1)])
        closed = []

        def fake_request(method, path, token, payload=None):
            if method == "PATCH":
                closed.append(payload)
            return {}

        with (
            mock.patch("notify_issues.inventory.load", return_value=[]),
            mock.patch("notify_issues.inventory.load_groups", return_value=[]),
            mock.patch("notify_issues.inventory.units", return_value=self._units(group=False)),
            mock.patch(
                "notify_issues._all_open_issues",
                return_value=[{"number": 7, "body": notify_issues.MARKER.format(id="solo")}],
            ),
            mock.patch("notify_issues._request", side_effect=fake_request),
        ):
            notify_issues.main()
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["state"], "closed")

    def test_unverified_endpoint_never_opens_an_issue(self):
        self._write([_record("solo", "down", 40), _record("solo", "down", 10)])
        units = [{"id": "solo", "name": "Solo", "url": "https://e.org/s", "verified": False}]
        opened = []

        def fake_request(method, path, token, payload=None):
            if method == "POST":
                opened.append(payload)
            return {}

        with (
            mock.patch("notify_issues.inventory.load", return_value=[]),
            mock.patch("notify_issues.inventory.load_groups", return_value=[]),
            mock.patch("notify_issues.inventory.units", return_value=units),
            mock.patch("notify_issues._all_open_issues", return_value=[]),
            mock.patch("notify_issues._request", side_effect=fake_request),
        ):
            notify_issues.main()
        self.assertEqual(opened, [])

    def test_missing_credentials_skip_notification_without_error(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "", "GH_REPO": ""}):
            self.assertEqual(notify_issues.main(), 0)


if __name__ == "__main__":
    unittest.main()
