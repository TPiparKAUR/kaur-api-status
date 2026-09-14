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
  report.py                  log -> REPORT.md
  discover.py                CKAN harvest + plain URL import
  cli.py                     argparse
scripts/notify_issues.py     GitHub issues as the notification channel
config/endpoints.toml        the inventory (data, not code)
logs/YYYY-MM.jsonl           append-only check log, committed
REPORT.md                    generated, committed
```

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

`keskkonnaandmed.envir.ee`, a PostgREST service, via 14 endpoints taken from
Keskkonnaagentuur's own API documentation: the OpenAPI root, climate metadata
(`f_kliima_element`, `f_kliima_jaam_vaatlus`), climate measurements by month,
day, hour and 10 minutes, `f_hydroseire`, `f_keskkonnaseire`, and four EELIS
`f_rahvalad` queries covering plain reads, PostgREST embedding and nested
filters.

Every request sends `Accept-Profile: apijahialad`. Without it the service
answers from an unspecified schema, so the header is not optional.

Measurement queries must be filtered — the documentation says so, and the
service caps a response at 20 000 rows. The inventory uses the documented
example queries with a small `limit` added, which keeps an hourly probe cheap
and makes the response deterministic enough that a changed body hash is
meaningful.

Ten entries are the documented queries verbatim and are `verified = true`.
Four are `verified = false`: the service is documented but the query (usually
just `?limit=1`) was constructed here rather than copied. Unverified endpoints
appear in the report but never open an issue, because a failure there is as
likely to be a wrong query as an outage.

## Open work

- The four `verified = false` queries need someone to confirm them against the
  real service, then flip the flag.
- No endpoint sets `freshness_regex` yet. Doing so needs someone who knows each
  payload's timestamp field; the documented queries are historical and would
  always read as stale.
- `discover.from_ckan` assumes a CKAN-shaped API. The Estonian open data
  portal's actual API has not been verified. It reports a mismatch rather than
  guessing, but it may simply not apply.
- EELIS has around 250 APIs; four are covered.
