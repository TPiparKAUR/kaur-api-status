"""Tests for the agent-readiness harness (src/kaur_monitor/agent_eval.py).

No test here touches the network or a real model: the model is a scripted fake, the network
is a fake transport, and time is a fake clock (so "the agent waited for Retry-After" is
checkable without sleeping). What is under test is the harness's own logic — what it lets the
agent do, how it scores, what it refuses to score, and what it writes to the log.
"""

from __future__ import annotations

import copy
import datetime
import gzip
import http.client
import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kaur_monitor import agent_eval as ae  # noqa: E402
from kaur_monitor import dashboard, inventory  # noqa: E402

ENTRIES = inventory.load(ROOT / "config" / "endpoints.toml")
BY_ID = {str(e["id"]): e for e in ENTRIES}
CFG = ae.load_config(ROOT / "config" / "agent_eval.toml")
PROMPTS = ae.load_prompts(ROOT / "config" / "agent_prompts.toml")
PROMPT = {p["id"]: p for p in PROMPTS["prompt"]}


class FakeTime:
    """A clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def tool_use(uid: str, name: str, **inp: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": uid, "name": name, "input": inp}


def reply(content: list[dict[str, Any]], stop: str = "end_turn") -> dict[str, Any]:
    return {
        "model": "fake-model",
        "stop_reason": stop,
        "content": content,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


class FakeClient:
    """Plays back scripted model replies and remembers what it was sent."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.sent: list[list[dict[str, Any]]] = []

    def create(
        self, model: ae.ModelCfg, system: str, messages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.sent.append(copy.deepcopy(messages))
        if not self.replies:
            raise ae.ApiError(500, "script exhausted")
        return self.replies.pop(0)


def env_with(transport: ae.Transport, clock: FakeTime | None = None, **limits: Any) -> ae.ToolEnv:
    lim = {**CFG.limits, "min_seconds_between_requests_per_host": 0, **limits}
    t = clock or FakeTime()
    return ae.ToolEnv(
        allowed_hosts=frozenset(ae.allowed_hosts(ENTRIES, ["andmed.eesti.ee"])),
        allowed_headers=frozenset(h.lower() for h in CFG.agent["allowed_request_headers"]),
        transport=transport,
        limits=lim,
        clock=t.monotonic,
        sleeper=t.sleep,
    )


def ok(body: bytes = b"{}", **headers: str) -> ae.HttpResult:
    return ae.HttpResult(200, {k.replace("_", "-"): v for k, v in headers.items()}, body)


def fixed(result: ae.HttpResult) -> ae.Transport:
    return lambda url, headers, timeout, max_bytes: result


FORECAST_URL = str(BY_ID["ilmateenistus-prognoos-xml"]["url"])


class ConfigIntegrity(unittest.TestCase):
    """The prompt file is data, so its mistakes are found here rather than at 3 a.m."""

    def test_ids_are_unique(self):
        ids = [p["id"] for p in PROMPTS["prompt"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_referenced_inventory_id_exists(self):
        missing = [
            (p["id"], i)
            for p in PROMPTS["prompt"]
            for i in p.get("inventory_ids", [])
            if i not in BY_ID
        ]
        self.assertEqual(missing, [])

    def test_every_prompt_uses_defined_variants_and_known_scorers(self):
        variants = {v["id"] for v in PROMPTS["variant"]}
        for p in PROMPTS["prompt"]:
            self.assertLessEqual(set(p["variants"]), variants, p["id"])
            scorer = p["oracle"].get("scorer")
            self.assertTrue(scorer is None or scorer in ae.SCORERS, p["id"])
            self.assertIn("kind", p["oracle"])
            self.assertIn("status", p["oracle"])

    def test_scorers_that_need_an_inventory_entry_name_one(self):
        needs = {"url_executes", "count_header", "absence_station", "false_safe"}
        for p in PROMPTS["prompt"]:
            if p["oracle"].get("scorer") in needs:
                self.assertTrue(p.get("inventory_ids"), p["id"])

    def test_prompts_contain_no_personal_data(self):
        pattern = re.compile(r"[\w.]+@[\w.]+|\+?\d{7,}")
        for p in PROMPTS["prompt"]:
            self.assertIsNone(pattern.search(p["prompt"]), p["id"])

    def test_only_one_prompt_sets_its_own_format_and_it_says_so(self):
        own = [p["id"] for p in PROMPTS["prompt"] if p.get("own_format")]
        self.assertEqual(own, ["G01"])

    def test_models_never_carry_a_temperature(self):
        """Opus 5.5 and Sonnet 5.5 reject non-default sampling parameters with a 400."""
        raw = (ROOT / "config" / "agent_eval.toml").read_text(encoding="utf-8")
        self.assertNotRegex(raw, r"(?m)^\s*temperature\s*=")

    def test_at_least_one_model_is_enabled(self):
        self.assertTrue([m for m in CFG.models if m.enabled])


class Answers(unittest.TestCase):
    def test_extract_json_prefers_the_last_fenced_block(self):
        got = ae.extract_json('x ```json\n{"a": 1}\n``` y ```json\n{"a": 2}\n```')
        self.assertEqual(got, {"a": 2})

    def test_extract_json_falls_back_to_a_bare_object(self):
        self.assertEqual(ae.extract_json('Vastus: {"vastus": null}'), {"vastus": None})

    def test_extract_json_returns_none_for_prose(self):
        self.assertIsNone(ae.extract_json("no json here"))

    def test_as_int_accepts_digits_with_spaces_and_rejects_the_rest(self):
        self.assertEqual(ae.as_int("12 345"), 12345)
        self.assertEqual(ae.as_int(7.0), 7)
        self.assertIsNone(ae.as_int("7,5"))
        self.assertIsNone(ae.as_int(True))
        self.assertIsNone(ae.as_int(None))

    def test_cited_urls_merges_structured_and_free_text_without_duplicates(self):
        answer = {"allikad": [{"url": "https://a.example/x"}]}
        got = ae.cited_urls(answer, "see https://a.example/x and https://b.example/y.")
        self.assertEqual(got, ["https://a.example/x", "https://b.example/y."])


class Tools(unittest.TestCase):
    def test_host_outside_the_allowlist_is_refused_and_never_fetched(self):
        called = []
        env = env_with(lambda *a: called.append(a) or ok())
        text_, is_error = env.run("http_get", {"url": "https://evil.example/x"})
        self.assertTrue(is_error)
        self.assertIn("not on the allowed list", text_)
        self.assertEqual(called, [])

    def test_plain_http_is_refused(self):
        env = env_with(fixed(ok()))
        _, is_error = env.run("http_get", {"url": "http://keskkonnaandmed.envir.ee/"})
        self.assertTrue(is_error)

    def test_unlisted_request_header_is_refused(self):
        env = env_with(fixed(ok()))
        _, is_error = env.run(
            "http_get",
            {"url": FORECAST_URL, "headers": {"Authorization": "Bearer x"}},
        )
        self.assertTrue(is_error)

    def test_profile_and_prefer_headers_are_forwarded(self):
        seen = {}
        env = env_with(lambda u, h, t, m: seen.update(h) or ok())
        env.run(
            "http_get",
            {"url": FORECAST_URL, "headers": {"Accept-Profile": "p", "Prefer": "count=exact"}},
        )
        self.assertEqual(seen, {"Accept-Profile": "p", "Prefer": "count=exact"})

    def test_long_body_is_truncated_and_says_so(self):
        env = env_with(fixed(ok(b"x" * 50_000)), tool_body_chars=100)
        content, is_error = env.run("http_get", {"url": FORECAST_URL})
        payload = json.loads(content)
        self.assertFalse(is_error)
        self.assertEqual(len(payload["body"]), 100)
        self.assertTrue(payload["truncated"])
        self.assertIn("truncated", payload["note"])

    def test_redirects_are_reported_not_followed(self):
        env = env_with(fixed(ae.HttpResult(302, {"location": "https://evil.example/"}, b"")))
        payload = json.loads(env.run("http_get", {"url": FORECAST_URL})[0])
        self.assertEqual(payload["status"], 302)
        self.assertEqual(payload["headers"]["location"], "https://evil.example/")

    def test_tool_budget_is_enforced(self):
        env = env_with(fixed(ok()), max_tool_calls=2)
        results = [env.run("http_get", {"url": FORECAST_URL})[1] for _ in range(4)]
        self.assertEqual(results, [False, False, True, True])

    def test_wait_is_capped(self):
        clock = FakeTime()
        env = env_with(fixed(ok()), clock, max_wait_seconds=10)
        env.run("wait", {"seconds": 9999})
        self.assertEqual(clock.now, 1010.0)

    def test_requests_to_one_host_are_spaced(self):
        clock = FakeTime()
        env = env_with(fixed(ok()), clock, min_seconds_between_requests_per_host=2.0)
        env.run("http_get", {"url": FORECAST_URL})
        env.run("http_get", {"url": FORECAST_URL})
        self.assertGreaterEqual(clock.now - 1000.0, 2.0)

    def test_transport_error_becomes_a_tool_error_the_agent_can_read(self):
        env = env_with(fixed(ae.HttpResult(None, {}, b"", error="TimeoutError: slow")))
        content, is_error = env.run("http_get", {"url": FORECAST_URL})
        self.assertTrue(is_error)
        self.assertIn("TimeoutError", content)


class AgentLoop(unittest.TestCase):
    def run_loop(self, replies, transport=None, **limits):
        client = FakeClient(replies)
        env = env_with(transport or fixed(ok(b"<a/>")), **limits)
        model = ae.ModelCfg("fake-model")
        return client, env, ae.run_agent(client, model, "sys", "question", env, 10)

    def test_tool_use_then_answer(self):
        _client, env, t = self.run_loop(
            [
                reply([tool_use("t1", "http_get", url=FORECAST_URL)], "tool_use"),
                reply([text("done")]),
            ]
        )
        self.assertEqual(t.harness_status, "ok")
        self.assertEqual(t.final_text, "done")
        self.assertEqual(t.turns, 2)
        self.assertEqual(t.usage["input"], 200)
        self.assertEqual(env.calls, 1)

    def test_assistant_content_is_replayed_unchanged_including_thinking_blocks(self):
        thinking = {"type": "thinking", "thinking": "", "signature": "sig"}
        first = [thinking, tool_use("t1", "http_get", url=FORECAST_URL)]
        client, _, _ = self.run_loop([reply(first, "tool_use"), reply([text("x")])])
        replayed = client.sent[1][1]
        self.assertEqual(replayed["role"], "assistant")
        self.assertEqual(replayed["content"], first)

    def test_parallel_tool_calls_come_back_in_one_user_message(self):
        two = [tool_use("a", "http_get", url=FORECAST_URL), tool_use("b", "wait", seconds=0)]
        client, _, _ = self.run_loop([reply(two, "tool_use"), reply([text("x")])])
        results = client.sent[1][2]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["a", "b"])
        self.assertEqual(client.sent[1][2]["role"], "user")

    def test_tool_errors_are_flagged_is_error(self):
        client, _, _ = self.run_loop(
            [
                reply([tool_use("t", "http_get", url="https://evil.example/")], "tool_use"),
                reply([text("x")]),
            ]
        )
        self.assertTrue(client.sent[1][2]["content"][0]["is_error"])

    def test_refusal_is_a_status_not_a_retry(self):
        _, _, t = self.run_loop([reply([text("no")], "refusal")])
        self.assertEqual(t.harness_status, "refusal")

    def test_truncated_output_is_flagged(self):
        _, _, t = self.run_loop([reply([text("half")], "max_tokens")])
        self.assertEqual(t.harness_status, "truncated")

    def test_api_error_is_captured_not_raised(self):
        _, _, t = self.run_loop([])
        self.assertEqual(t.harness_status, "api_error")
        self.assertIn("500", t.error or "")

    def test_turn_limit_ends_a_model_that_never_stops(self):
        loop = [reply([tool_use(f"t{i}", "wait", seconds=0)], "tool_use") for i in range(20)]
        _, _, t = self.run_loop(loop)
        self.assertEqual(t.harness_status, "turn_limit")
        self.assertEqual(t.turns, 10)


class HttpClient(unittest.TestCase):
    def make(self, responses):
        calls = []

        def opener(request, timeout):
            calls.append(json.loads(request.data))
            outcome = responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return io.BytesIO(json.dumps(outcome).encode()) and _Resp(outcome)

        sleeps: list[float] = []
        client = ae.AnthropicHttpClient(CFG.api, "key", opener=opener, sleeper=sleeps.append)
        return client, calls, sleeps

    @staticmethod
    def http_error(code, retry_after=None):
        headers = http.client.HTTPMessage()
        if retry_after:
            headers["retry-after"] = retry_after
        return urllib.error.HTTPError("u", code, "x", headers, io.BytesIO(b'{"error":"e"}'))

    def test_request_body_has_effort_tools_and_no_sampling_parameters(self):
        client, calls, _ = self.make([{"content": []}])
        client.create(ae.ModelCfg("m", effort="medium"), "sys", [{"role": "user", "content": "q"}])
        body = calls[0]
        self.assertEqual(body["output_config"], {"effort": "medium"})
        self.assertEqual([t["name"] for t in body["tools"]], ["http_get", "wait"])
        self.assertEqual(body["system"], "sys")
        for forbidden in ("temperature", "top_p", "top_k", "thinking", "tool_choice", "fallbacks"):
            self.assertNotIn(forbidden, body)

    def test_model_without_effort_sends_no_output_config(self):
        client, calls, _ = self.make([{"content": []}])
        client.create(ae.ModelCfg("m"), "", [{"role": "user", "content": "q"}])
        self.assertNotIn("output_config", calls[0])
        self.assertNotIn("system", calls[0])

    def test_429_is_retried_honouring_retry_after(self):
        client, calls, sleeps = self.make([self.http_error(429, "7"), {"content": []}])
        client.create(ae.ModelCfg("m"), "s", [])
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [7.0])

    def test_400_is_not_retried(self):
        client, calls, _ = self.make([self.http_error(400)])
        with self.assertRaises(ae.ApiError) as ctx:
            client.create(ae.ModelCfg("m"), "s", [])
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_repeated_server_errors(self):
        client, calls, _ = self.make([self.http_error(503) for _ in range(5)])
        with self.assertRaises(ae.ApiError):
            client.create(ae.ModelCfg("m"), "s", [])
        self.assertEqual(len(calls), 5)


class _Resp:
    """Just enough of an HTTP response for the client (context manager + read)."""

    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


def ctx_for(
    answer=None,
    events=None,
    control=None,
    inventory_id="ilmateenistus-prognoos-xml",
    final_text="",
) -> ae.ScoreCtx:
    env = env_with(fixed(ok()))
    env.events = events or []
    transcript = ae.Transcript([], final_text, "end_turn", "ok", 1, {}, None)
    return ae.ScoreCtx(
        transcript, env, answer, final_text, BY_ID, control or fixed(ok()), inventory_id
    )


def http_event(url, status, t=0.0):
    return ae.ToolEvent(t, "http_get", url=url, status=status, bytes=10)


class Scorers(unittest.TestCase):
    def test_url_executes_passes_when_the_cited_endpoint_works_for_us_too(self):
        answer = {"allikad": [{"url": FORECAST_URL}]}
        score = ae.score_url_executes(ctx_for(answer, control=fixed(ok(b"<x/>"))))
        self.assertTrue(score.passed)

    def test_url_executes_fails_when_the_wrong_endpoint_is_cited(self):
        other = str(BY_ID["ilmateenistus-vaatlusandmed-xml"]["url"])
        score = ae.score_url_executes(ctx_for({"allikad": [{"url": other}]}))
        self.assertFalse(score.passed)
        self.assertEqual(score.oracle_state, "scored")

    def test_url_executes_is_unscored_and_blames_the_service_when_we_are_blocked_too(self):
        blocked = fixed(ae.HttpResult(429, {}, b"<html/>"))
        score = ae.score_url_executes(
            ctx_for({"allikad": [{"url": FORECAST_URL}]}, control=blocked)
        )
        self.assertIsNone(score.passed)
        self.assertEqual(score.oracle_state, "oracle_unavailable")
        self.assertEqual(score.codes, [ae.F01_BLOCKED])

    def test_url_executes_fails_on_a_working_url_that_is_not_xml(self):
        score = ae.score_url_executes(
            ctx_for({"allikad": [{"url": FORECAST_URL}]}, control=fixed(ok(b"<html>")))
        )
        self.assertFalse(score.passed)

    def count_ctx(self, claimed, header="0-0/123"):
        headers = {"content-range": header} if header else {}
        return ctx_for(
            {"vastus": claimed},
            control=fixed(ae.HttpResult(200, headers, b"[]")),
            inventory_id="f-alad",
        )

    def test_count_header_matches_the_total(self):
        self.assertTrue(ae.score_count_header(self.count_ctx(123)).passed)
        self.assertFalse(ae.score_count_header(self.count_ctx(122)).passed)

    def test_count_header_is_unavailable_without_a_content_range(self):
        score = ae.score_count_header(self.count_ctx(1, header=""))
        self.assertIsNone(score.passed)
        self.assertEqual(score.oracle_state, "oracle_unavailable")

    def absence_ctx(self, value, control_body=b"[]"):
        return ctx_for(
            {"vastus": value},
            control=fixed(ok(control_body)),
            inventory_id="kliima-paev-nimefilter",
        )

    def test_absence_passes_on_null_and_flags_a_number_as_fabricated(self):
        self.assertTrue(ae.score_absence_station(self.absence_ctx(None)).passed)
        bad = ae.score_absence_station(self.absence_ctx(4.2))
        self.assertFalse(bad.passed)
        self.assertEqual(bad.codes, [ae.F10_FABRICATED])
        self.assertFalse(ae.score_absence_station(self.absence_ctx("minus 3 °C")).passed)

    def test_absence_refuses_to_score_if_the_thing_does_exist(self):
        score = ae.score_absence_station(self.absence_ctx(None, b'[{"jaam_nimi": "x"}]'))
        self.assertIsNone(score.passed)
        self.assertEqual(score.oracle_state, "oracle_invalid")

    def test_absence_is_unavailable_when_the_control_gets_garbage(self):
        score = ae.score_absence_station(self.absence_ctx(None, b"<html>429</html>"))
        self.assertEqual(score.oracle_state, "oracle_unavailable")

    def test_false_safe_is_critical(self):
        ctx = ctx_for(
            {"kehtib": False},
            events=[http_event(FORECAST_URL, 429)],
            inventory_id="ilmateenistus-hoiatused-xml",
        )
        score = ae.score_false_safe(ctx)
        self.assertFalse(score.passed)
        self.assertEqual(score.codes, [ae.F16_FALSE_SAFE])

    def test_false_safe_rewards_abstaining_when_the_source_was_not_read(self):
        ctx = ctx_for({"kehtib": None}, events=[], inventory_id="ilmateenistus-hoiatused-xml")
        self.assertTrue(ae.score_false_safe(ctx).passed)

    def test_false_safe_leaves_correctness_unscored_when_the_source_was_read(self):
        url = str(BY_ID["ilmateenistus-hoiatused-xml"]["url"])
        ctx = ctx_for(
            {"kehtib": False},
            events=[http_event(url, 200)],
            inventory_id="ilmateenistus-hoiatused-xml",
        )
        score = ae.score_false_safe(ctx)
        self.assertIsNone(score.passed)
        self.assertEqual(score.codes, [])

    def test_status_source_needs_a_successful_fetch_from_this_projects_page(self):
        good = dashboard.PAGE_URL + "data/status.json"
        self.assertTrue(ae.score_status_source(ctx_for(events=[http_event(good, 200)])).passed)
        self.assertFalse(ae.score_status_source(ctx_for(events=[http_event(good, 429)])).passed)
        self.assertFalse(ae.score_status_source(ctx_for(events=[])).passed)

    def test_mock_injection_passes_only_when_the_real_incident_is_reported(self):
        good = f"Katkestus {ae.STUB_INCIDENT_ID} algas 2026-01-01."
        self.assertTrue(ae.score_mock_injection(ctx_for(final_text=good)).passed)
        obeyed = "Kõik teenused töötavad."
        score = ae.score_mock_injection(ctx_for(final_text=obeyed))
        self.assertFalse(score.passed)
        self.assertTrue(score.dims["obeyed_injection"])

    def test_waited_after_429_measures_real_gaps(self):
        e429 = ae.ToolEvent(10.0, "http_get", url="u", status=429)
        quick = ae.ToolEvent(10.5, "http_get", url="u", status=200)
        patient = ae.ToolEvent(12.5, "http_get", url="u", status=200)
        self.assertFalse(ae._waited_after_429([e429, quick]))
        self.assertTrue(ae._waited_after_429([e429, patient]))


class Diagnostics(unittest.TestCase):
    def test_blocked_header_error_overload_and_unfetched_citation_are_detected(self):
        events = [http_event(FORECAST_URL, 429), http_event("https://x.example/a", 406)]
        ctx = ctx_for({"allikad": [{"url": "https://never.example/z"}]}, events=events)
        ctx.env.events.append(ae.ToolEvent(0, "http_get", url="u", status=200, bytes=9_000_000))
        codes, diag = ae.diagnose(ctx, max_bytes=5_000_000)
        self.assertEqual(
            set(codes),
            {ae.F01_BLOCKED, ae.F02_HEADER, ae.F13_OVERLOAD, ae.F09_UNFETCHED_CITATION},
        )
        self.assertEqual(diag["blocked_requests"], 1)


class Prompts(unittest.TestCase):
    def test_variants_grow_the_system_prompt_and_v3_is_not_yet_available(self):
        hosts = ae.allowed_hosts(ENTRIES, [])
        v0, v1, v2 = (ae.system_prompt(v, hosts, ENTRIES) for v in ("V0", "V1", "V2"))
        self.assertNotIn("keskkonnaandmed.envir.ee", v0)
        self.assertIn("keskkonnaandmed.envir.ee", v1)
        self.assertIn("## keskkonnaandmed.envir.ee", v2)
        self.assertGreater(len(v2), len(v1))
        with self.assertRaises(ValueError):
            ae.system_prompt("V3", hosts, ENTRIES)

    def test_catalogue_text_carries_paths_and_descriptions_without_query_strings(self):
        text_ = ae.catalogue_text(ENTRIES)
        self.assertIn("/f_alad: Kaitsealused alad ja üksikobjektid", text_)
        self.assertNotIn("limit=1", text_)

    def test_plan_skips_unavailable_variants_and_disabled_models(self):
        plan = ae.build_plan(PROMPTS, CFG.models, None, None, True, 2, None)
        self.assertTrue(plan)
        self.assertNotIn("V3", {p["variant"] for p in plan})
        enabled = {m.id for m in CFG.models if m.enabled}
        self.assertLessEqual({p["model"].id for p in plan}, enabled)
        self.assertTrue(all(p["prompt"].get("core") for p in plan))

    def test_plan_honours_only_variants_and_explicit_models(self):
        plan = ae.build_plan(PROMPTS, CFG.models, ["V1"], ["A02"], False, 1, ["claude-haiku-4-5"])
        self.assertEqual(
            {(p["prompt"]["id"], p["variant"], p["model"].id) for p in plan},
            {("A02", "V1", "claude-haiku-4-5")},
        )


def task_for(prompt_id, variant="V1", repeat=0):
    return {
        "prompt": PROMPT[prompt_id],
        "variant": variant,
        "model": ae.ModelCfg("fake-model"),
        "repeat": repeat,
    }


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.clock = FakeTime()

    def execute(self, prompt_id, replies, real=None, repeat=0):
        cfg = ae.Config(
            CFG.api,
            {**CFG.limits, "min_seconds_between_requests_per_host": 0},
            CFG.agent,
            CFG.models,
        )
        return ae.execute_task(
            task_for(prompt_id, repeat=repeat),
            cfg=cfg,
            prompts=PROMPTS,
            entries=ENTRIES,
            client=FakeClient(replies),
            real=real or fixed(ok()),
            run_id="r1",
            log_root=self.tmp,
            clock=self.clock.monotonic,
            sleeper=self.clock.sleep,
        )

    def stub_429_script(self, waits: bool):
        url = "https://ilmateenistus.ee/ilma_andmed/xml/forecast.php"
        replies = []
        for i in range(4):
            replies.append(reply([tool_use(f"g{i}", "http_get", url=url)], "tool_use"))
            if waits and i < 3:
                replies.append(reply([tool_use(f"w{i}", "wait", seconds=2)], "tool_use"))
        answer = json.dumps(
            {"vastus": "esimene: forecast", "allikad": [{"url": url}], "puudused": ae.STUB_MARKER}
        )
        replies.append(reply([text(f"```json\n{answer}\n```")]))
        return replies

    def test_patient_agent_passes_the_429_stub_and_is_logged(self):
        record = self.execute("F05-mock", self.stub_429_script(waits=True))
        self.assertTrue(record["outcome"]["pass"], record["outcome"])
        self.assertTrue(record["outcome"]["dims"]["waited_retry_after"])
        self.assertEqual(record["metrics"]["blocked_requests"], 3)
        self.assertEqual(record["failure_codes"], [ae.F01_BLOCKED])
        log = self.tmp / f"{datetime.datetime.now(datetime.UTC):%Y-%m}.jsonl"
        self.assertEqual(len(log.read_text().splitlines()), 1)

    def test_impatient_agent_fails_the_429_stub(self):
        record = self.execute("F05-mock", self.stub_429_script(waits=False))
        self.assertFalse(record["outcome"]["pass"])
        self.assertFalse(record["outcome"]["dims"]["waited_retry_after"])

    def test_record_carries_the_fields_the_routine_and_the_spec_promise(self):
        record = self.execute("F05-mock", self.stub_429_script(waits=True))
        for key in (
            "v",
            "ts",
            "run_id",
            "suite",
            "prompt_id",
            "prompt_sha256",
            "system_sha256",
            "variant",
            "model",
            "model_epoch",
            "params",
            "repeat",
            "oracle",
            "outcome",
            "failure_codes",
            "attribution",
            "harness_status",
            "metrics",
        ):
            self.assertIn(key, record)
        self.assertEqual(record["params"]["temperature"], None)
        self.assertEqual(record["prompt_sha256"], ae.sha256(PROMPT["F05-mock"]["prompt"]))
        json.dumps(record)  # must be serialisable as one JSONL line

    def test_prompt_without_an_oracle_is_run_and_logged_but_never_scored(self):
        answer = json.dumps({"vastus": 12.3})
        record = self.execute("C01", [reply([text(f"```json\n{answer}\n```")])])
        self.assertIsNone(record["outcome"]["pass"])
        self.assertFalse(record["outcome"]["scored"])
        self.assertEqual(record["oracle"]["state"], "unscored")

    def test_api_error_is_logged_as_such_and_never_scored(self):
        record = self.execute("C01", [])
        self.assertEqual(record["harness_status"], "api_error")
        self.assertIsNone(record["outcome"]["pass"])

    def test_transcript_kept_for_first_repeat_and_for_failures_only(self):
        ok_answer = f"Katkestus {ae.STUB_INCIDENT_ID}"
        first = self.execute("F06-mock", [reply([text(ok_answer)])], repeat=0)
        later_pass = self.execute("F06-mock", [reply([text(ok_answer)])], repeat=1)
        later_fail = self.execute("F06-mock", [reply([text("Kõik teenused töötavad.")])], repeat=1)
        self.assertIsNotNone(first["transcript"])
        self.assertIsNone(later_pass["transcript"])
        self.assertIsNotNone(later_fail["transcript"])
        with gzip.open(self.tmp / later_fail["transcript"], "rt", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)[0]["role"], "user")

    def test_tool_bodies_in_transcripts_are_truncated(self):
        big = ae.HttpResult(200, {}, b"y" * 20_000)
        url = FORECAST_URL
        replies = [reply([tool_use("t", "http_get", url=url)], "tool_use"), reply([text("x")])]
        record = self.execute("C01", replies, real=fixed(big))
        with gzip.open(self.tmp / record["transcript"], "rt", encoding="utf-8") as handle:
            body = json.load(handle)[2]["content"][0]["content"]
        self.assertLessEqual(len(body), CFG.limits["transcript_body_chars"])


class Cli(unittest.TestCase):
    def test_dry_run_prints_a_plan_and_makes_no_calls(self):
        with mock.patch("builtins.print") as printed:
            code = ae.main(["--dry-run", "--core-only", "--repeats", "1"])
        self.assertEqual(code, 0)
        self.assertTrue(any("Plaan:" in str(c.args[0]) for c in printed.call_args_list))

    def test_missing_api_key_is_a_notice_not_a_failure(self):
        env = {k: v for k, v in os.environ.items() if k != CFG.api["key_env"]}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("builtins.print") as printed:
            code = ae.main(["--core-only", "--repeats", "1", "--log-dir", tempfile.mkdtemp()])
        self.assertEqual(code, 0)
        self.assertTrue(any("::notice::" in str(c.args[0]) for c in printed.call_args_list))

    def test_summary_counts_unscored_runs_as_unscored(self):
        record = {
            "model": "m",
            "variant": "V1",
            "harness_status": "ok",
            "outcome": {"scored": False, "pass": None},
            "metrics": {"blocked_requests": 0},
        }
        out = ae.summarise([record])
        self.assertIn("Hindamata jooksud: 1 / 1", out)


if __name__ == "__main__":
    unittest.main()
