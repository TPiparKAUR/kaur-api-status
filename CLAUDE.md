# KAUR API monitor — project notes

Availability monitoring for Keskkonnaagentuur public APIs. Records when each
service was down and for how long, and notifies via GitHub issues.

This repository previously held a bulk data downloader. That goal was dropped:
git is the wrong store for bulk environmental data (radar volumes alone run to
roughly 1 TB per radar per year, against a 1 GB free LFS quota), and most of it
is already archived upstream. See the git history for the reasoning.

## Hard rules

**Never write an endpoint URL into source code.** Endpoints live in
`config/endpoints.toml` and arrive via `discover` or `import-urls`. An earlier
revision of this repository hardcoded invented URLs and mislabelled KESE and
EELIS as one system; that is what the `verified` flag and this rule exist to
prevent. If you cannot verify a URL, do not write it — say so instead.

**No runtime dependencies.** Standard library only, Python 3.11+ (`tomllib`).
This keeps CI install-free and the tool runnable anywhere. Do not add
`requests`, `pyyaml`, `typer` or similar. Tests use `unittest`, not pytest.

**Network access from an authoring session is likely blocked.** Estonian
government domains return `403 policy denial` through the agent proxy. Check
before assuming a failure is the service's fault. Real checks run on the GitHub
Actions runner or an operator's machine.

## Layout

```
monitor.py                   entry point, adds src/ to path
src/kaur_monitor/
  check.py                   staged endpoint checks, TLS expiry, OGC exceptions
  inventory.py               endpoints.toml load / validate / save / merge
  store.py                   append-only JSONL log, monthly partitions
  analysis.py                incidents and uptime — one definition, two readers
  report.py                  log -> REPORT.md
  dashboard.py               log -> docs/data/status.json
  discover.py                CKAN + OpenAPI harvest, plain URL import
  cli.py                     argparse
scripts/notify_issues.py     GitHub issues as the notification channel
scripts/commit_and_push.sh   shared by both committing workflows
config/endpoints.toml        the inventory (data, not code)
config/systems.toml          plain-language system descriptions for the page
logs/YYYY-MM.jsonl           append-only check log, committed
REPORT.md                    generated, committed
docs/                        static GitHub Pages status page, Chart.js vendored
docs/data/status.json        generated, committed — the only thing the page reads
```

**The page never invents data.** Too little history means a sentence saying so,
not a line drawn through two points. Keep that property.

## Design decisions worth keeping

**Staged checks, not up/down.** HTTP 200 is not health here: a WFS answers 200
with an `ows:ExceptionReport`, and an observation feed answers 200 with stale
data. The stage a check reached is recorded so a failure says where it broke.

**`unknown` is a distinct state.** When every endpoint fails before a response,
the checker's own network is the likely cause. Those records are excluded from
availability arithmetic and never raise an issue. Without this, one runner
outage reads as every service failing at once.

**JSONL, not Parquet, for the log.** Git delta-compresses text; a repeatedly
committed Parquet file stores a near-full copy every time and the repository
grows without bound. Roughly 35 MB a year at twenty endpoints checked hourly.
`logs/*.jsonl` uses git's union merge driver so concurrent appends combine.

**Merge never overwrites.** A human correcting a discovered URL keeps that
correction on the next discovery run.

**`check` exits 0 on a missing inventory.** Nothing to monitor is a normal
starting state; failing the hourly job until someone populates the file would
train everyone to ignore its alerts. A file that exists but is malformed still
exits non-zero. `check_endpoint` likewise never raises — it is mapped over
every endpoint, so one escaping exception would lose the whole run's log,
report and notifications rather than just that endpoint.

**Report in Estonian local time, log in UTC.** Data and code are UTC ISO 8601;
`REPORT.md` renders EET/EEST and labels it.

## Commands

```bash
python3 monitor.py check [--workers N] [--dry-run] [--fail-on-down]
python3 monitor.py report | list | validate
python3 monitor.py import-urls urls.txt
python3 monitor.py discover --ckan URL [--query Q] [--rows N]
python3 -m unittest discover -s tests
```

## What is monitored

283 endpoints across two services, checked every 30 minutes.

`keskkonnaandmed.envir.ee` is a PostgREST service. Eighteen entries were written
by hand from Keskkonnaagentuur's documentation; the remaining 261 were harvested
from the service's own OpenAPI description (`discover --from-inventory
keskkonnaandmed-root`), which is the only honest way to cover EELIS's several
hundred tables.

`avaandmed.keskkonnaportaal.ee` is KAIA, the file download service: four
entries covering its OpenAPI document, both list hierarchies, and the document
search, which is a read but only reachable by POST with a query body.

Every keskkonnaandmed request sends `Accept-Profile: apijahiala`. Without it
the service answers from an unspecified schema, so the header is not optional.

**The published documentation gets this value wrong.** It gives `apijahialad`,
with a trailing d. The live service rejects that with 406 PGRST106 and names
the value it will accept. Every documented example query, curl invocation
included, fails as written. Do not "correct" the inventory back to the
documented spelling — the monitor found this on its first live run, and the
first run after the fix returned 200 on every endpoint.

Measurement queries must be filtered — the documentation says so, and the
service caps a response at 20 000 rows. Harvested entries carry `?limit=1` and
the hand-written ones use the documented example queries with a small limit,
which keeps a probe cheap and makes the response deterministic enough that a
changed body hash means something.

An endpoint left `verified = false` appears in the report and on the page but
never opens an issue, because a failure there is as likely to be a wrong query
as an outage — keep that property. The 261 harvested entries are unverified.

Two endpoints are capped deliberately. The OpenAPI root returns about 4 MB and
the station metadata table 1.1 MB unfiltered, so the root reads at most 64 KB
and the station query uses `limit=1`.

## Open work

**Log growth is the pressing one.** 283 endpoints every 30 minutes is 13 584
requests a day and about 5 million log records a year — roughly **1 GB of
committed text per year**, against GitHub's 1 GB recommended repository size.
Reading is already bounded (the report and page window to 31 days), so this is
purely a storage question, and it needs a decision rather than a code change:
a slower cadence for the harvested tail, per-endpoint intervals, rolling old
months up into daily aggregates and dropping the raw lines, or accepting it.
Nothing here prunes anything on its own.

Actions minutes are fine by contrast: a measured run is 43 seconds, so 1 440
minutes a month against a 2 000 allowance. The margin is one slow day wide,
though — crossing 60 seconds doubles the bill.

- The 261 harvested endpoints are `verified = false`. Confirming them is a
  human job; until then they are watched but never alert.
- No endpoint sets `freshness_regex`. Doing so needs someone who knows each
  payload's timestamp field; the documented queries are historical and would
  always read as stale.
- `f_hydroseire` response times are erratic — three of six samples over 13 s
  against a 30 s timeout. Worth watching as the log grows.
- `discover.from_ckan` assumes a CKAN-shaped API and has never been exercised
  against a real catalogue.
- GitHub Pages does not serve a private repository on the free plan, so the
  page is built and committed but not published until the repo is public or
  the plan changes.
