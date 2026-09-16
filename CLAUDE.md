# KAUR API monitor — project notes

Availability monitoring for Keskkonnaagentuur public APIs. Records when each
service was down and for how long, and notifies via GitHub issues.

This repository previously held a bulk data downloader. That goal was dropped:
git is the wrong store for bulk environmental data (radar volumes alone run to
roughly 1 TB per radar per year, against a 1 GB free LFS quota), and most of it
is already archived upstream. See the git history for the reasoning.

## Working practice

**Work on `main`.** Changes go straight to the default branch: this is a
single-maintainer operational repository, the automated monitoring job commits
to `main` every half hour anyway, and the public status page is served from
`main/docs`, so anything sitting on a side branch is invisible where it
matters. Do not open feature branches unless the project owner asks for one.
Conflicts in the two generated files (`REPORT.md`, `docs/data/status.json`)
are resolved by regenerating them with `python3 monitor.py report`, never by
hand-merging.

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
  retention.py               roll old raw months into logs/daily/, then delete them
  cli.py                     argparse
scripts/notify_issues.py     GitHub issues as the notification channel
scripts/commit_and_push.sh   shared by both committing workflows
config/endpoints.toml        the inventory (data, not code)
config/systems.toml          plain-language system descriptions for the page
logs/YYYY-MM.jsonl           append-only check log, committed
logs/daily/YYYY-MM.jsonl     one row per (unit, day) for months past retention.py's
                             cutoff; archival only — nothing in report.py, dashboard.py
                             or analysis.py reads it, see retention.py
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

**Groups collapse many endpoints into one recorded unit.** EELIS publishes 261
tables behind one service. All are checked every run; one record is written.
A single failing member takes the group down and the record names which
members failed, so the aggregate never hides the cause. Without this the log
would grow by a gigabyte a year to repeat "all 261 fine" every half hour, and
a reader would scan 261 rows to learn one thing. `[[group]]` in the inventory
defines them; `inventory.units()` is what the report and page actually iterate.

**`inventory.save()` preserves the file preamble.** A discovery run rewrites
the inventory wholesale and once deleted the notes explaining the wrong
documented header value and the deliberately excluded KAIA endpoints. Comments
above the first table now survive; comments between tables still do not,
because the tables are regenerated.

**Report in Estonian local time, log in UTC.** Data and code are UTC ISO 8601;
`REPORT.md` renders EET/EEST and labels it.

**A single failed check is not an outage.** One dropped packet or a service
mid-restart used to become a logged `down` and an Issue on its own. Two
independent layers now guard against that: `check.py` retries a non-ok result
once, `retry_delay_s` (default 5 s) later, before it is ever logged — a `cli.py`
choice (`retry=True`), not the default, so existing callers and tests are
unaffected. `notify_issues.py` adds a second, separate bar: an Issue only
*opens* on the second consecutive failing check in the log (`unknown` records
are skipped, not counted as a break, matching `analysis.incidents()`);
*recovery* still closes on the first `ok`, because paging late costs nothing
but staying down looks worse the longer it goes unacknowledged.

**Log schema is versioned from 2026-09-14 (`v: 2`).** That date is also when
EELIS started being collapsed into one `eelis` group record — the two changes
shipped together. `v` and `attempts` (1, or 2 if the retry above fired) are
new fields; records written before that date lack both and must be read as
`attempts = 1`. `REPORT.md` carries a permanent note about the transition
because old individual `eelis-f-*` records remain in the 31-day window for a
while after this file is read — nothing enforces this at read time, so do not
assume `v` is present.

**Certificate checks are cached per host, per run.** `check.CertCache` was
added because `_tls_expiry_days` opens a full second TLS handshake purely to
read an expiry date — fine once, wasteful 283 times against two hosts. It also
used to run *inside* the timed section, inflating every published response
time by that extra handshake; timing now starts only after the certificate
check, right before the request being measured. `cli.py` shares one
`CertCache` across the whole `ThreadPoolExecutor` run.

**`REPORT.md`'s "Hetkeseis" only speaks for currently-monitored units.** It
used to tally the latest record of every id the 31-day log window had ever
seen, which after the EELIS grouping change meant it counted 284 — the 23
current units plus every superseded individual `eelis-f-*` id still inside
the window — while the header line said "jälgitavaid otspunkte: 23" a few
words earlier. "Käideldavus" and "Katkestused" still show the full history on
purpose (those old ids genuinely ran during the window); only the *current
state* summary and table, and the certificate-expiry warnings, are filtered
to ids present in the unit list passed in.

**System-level availability is computed from pooled records, not averaged
percentages.** `dashboard.py` used to average each member endpoint's already
-rounded `avail_24h`, which weighs a member with one check the same as one
with a thousand and a 261-endpoint group the same as a single endpoint.
It now pools every member's raw records for the system and runs
`analysis.uptime` over the pool, so the result is weighted by actual checks.

**The availability chart's Y-axis floor is derived from the data, not fixed.**
A fixed `suggestedMin: 90` either exaggerates an ordinary blip when the real
range is a fraction of a percent, or hides real variation when it's wider.
`app.js` now floors 2 points below the lowest plotted value, rounded down to
a multiple of 5, and states the actual floor in the chart's text summary —
never leaving a truncated axis for the reader to notice unlabelled.

**GitHub Actions steps are pinned to a commit SHA, not a floating major tag.**
`actions/checkout@v4` and `actions/setup-python@v5` both had that tag
re-pointed at a new minor release during this project's own history — not
maliciously, but a tag is not immutable, and a workflow with `contents: write`
and `issues: write` running on every push is not somewhere to trust that only
benign changes ever land there. Pinned SHAs carry the tagged version as a
trailing comment so the intent stays readable.

## Commands

```bash
python3 monitor.py check [--workers N] [--dry-run] [--fail-on-down]
python3 monitor.py report | list | validate
python3 monitor.py import-urls urls.txt
python3 monitor.py discover --ckan URL [--query Q] [--rows N]
python3 -m unittest discover -s tests
```

## What is monitored

309 endpoints (308 enabled) across nine hosts, 42 units, every 30 minutes.

**Where the newer entries came from (2026-09-15).** The Teabevärav catalogue
(andmed.eesti.ee) lists Keskkonnaagentuur's 9 data services and 24 datasets.
Its pages are a client-side Angular app — a server-side fetch returns the same
75 KB shell for every one of them — but `/api/data-services/{uuid}` and
`/api/datasets/{uuid}` serve the real records, and those carry
`serviceEndpoints[].endpointUrl`, `serviceEndpointDescriptions[]` and
`distributions[].accessUrls[]`. That is where every endpoint added that day
came from, plus the pages those records point at (`keskkonnaportaal.ee`'s
avaandmed pages and ilmateenistus.ee's two XML documentation pages). No
organisation filter on `/api/datasets` is accepted — `organizationId`,
`organizationIds`, `informationHolderId`, `publisherId` are all rejected by
name and the holder sub-resource 404s — so enumeration goes through free-text
`?search=`, and the holder is read back off each record.

**That last sentence was too broad, and the correction is worth more than the
original finding (measured 2026-09-16).** The crawl never tried `/oai`.
andmed.eesti.ee does serve OAI-PMH there — `repositoryName` "Estonian
OpenData", protocol 2.0, `adminEmail opendatasupport@ria.ee`, gzip — and
`?verb=ListRecords&metadataPrefix=dcat_ap` returns the whole catalogue as
DCAT-AP in one unpaginated response. `ListIdentifiers` counted 8 053 records.
`/oai/hvd` and `/oai/dga` exist as separate base URLs and accept only
`ListRecords`. So a machine-readable export does exist; free-text search is
not the only way in.

Two defects in that interface, both measured, both making it undiscoverable
rather than absent: `ListMetadataFormats` answers `badArgument: No identifier
provided` when called bare, though OAI-PMH requires it to list every format,
so `dcat_ap` cannot be discovered through the protocol (`oai_dcat` and
`dcatap` are both rejected with `cannotDisseminateFormat`); and `ListSets`
answers `noSetHierarchy`, so the hvd and dga subsets are not reachable as
sets either. A client has to be told both out of band.

What the export says about this agency, filtered to publisher
"Keskkonnaagentuur": 36 dataset records — against the 24 the catalogue's own
web page lists — 23 `dcat:DataService` nodes and 96 distinct distribution
URLs. Fifteen of the 23 services carry a `dcat:endpointDescription`, and all
fifteen are INSPIRE or Maa-amet WMS/WFS `GetCapabilities` nodes attached to
spatial datasets. The eight *named* agency services — six identical
"Ilmateenistus" records, KESE, and "Keskkonna ja ilma valdkonna
andmeteenused" — carry none, and two of the six put a Creative Commons
licence URL in `foaf:page`/documentation. **EstModel appears nowhere in the
export**: scanning all 8 053 records for the string, whatever the publisher,
returned zero, although both its service and its dataset are on the
catalogue's web pages under this agency's name. The one service with a real
OpenAPI description is the one missing from the machine-readable channel.

That last point is worth stating precisely, because the web record is not
half-filled — it is the only *complete* one we have. `andmed.eesti.ee`'s page
for "EstModeli veebiteenus" names Keskkonnaagentuur as teabevaldaja, gives
"Viide otspunktile" as `https://estmodel.envir.ee`, gives "Otspunkti
kirjeldus" as the SwaggerHub OpenAPI document, links the related dataset,
states CC BY 4.0, and carries a named contact point with an address and a
phone number. Every field an agent would want is there, filled in correctly,
on the one record that the DCAT-AP export does not carry. So the failure is
not that nobody filled the form in; it is that filling it in did not reach
the machine-readable channel.

Worth knowing before re-running that exercise: everything the catalogue lists
under `keskkonnaandmed.envir.ee` was already in the inventory. The crawl
confirmed the existing entries rather than adding to them.

What it did add: EstModel's seven parameter-free collections (every other path
in its OpenAPI document needs a code this project cannot know), five
Ilmateenistus feeds (observations, forecast, warnings XML, warnings RSS, and
the service root the catalogue gives as `endpointUrl` for five of its
services), seven KAIA per-dataset file views as one group, and the published
access URLs of KESE, PAKIS, PROTO, Kütuseseire and KOTKAS.

`kotkas-aastaaruanded` is `enabled = false`: its first real check answered 403
Forbidden, so it is access-controlled rather than down, and a permanently red
row would misrepresent that. The entry stays in the inventory with the
measured reason, because deleting it would invite someone to rediscover the
same URL and wonder.

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

Log growth is handled by grouping (see below): 23 units rather than 283
endpoints is about 400 000 records and 84 MB a year, down from a projected
1 GB. Nothing prunes anything automatically; if it ever needs to, the reading
side is already windowed to 31 days.

Actions minutes: re-measured 2026-09-15 (run 62, commit 3525595) after adding
the once-only retry and the per-host concurrency cap (`HostLimiter`, default
4 — one host carries 279 of 283 endpoints, so that cap governs almost the
whole run): the "Run checks" step took 42 s, job total 47 s, essentially
unchanged from the original 43 s figure. So 1 440 minutes a month against a
2 000 allowance still holds, with margin.

That run had nothing to retry, though — every endpoint answered cleanly, so
it does not measure either change's cost during a real, widespread outage: a
run where many endpoints are down now costs an extra `retry_delay_s` (5 s)
per failing endpoint (serialised per worker) on top of whatever queueing the
concurrency cap adds for a host with more in-flight requests than its cap
allows. Worth re-measuring against a run with real failures rather than
assuming the healthy-run figure holds under load.

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

Decided (2026-09-15) — each had a real trade-off or needed a fact only a
human here could supply, so each was put to the project owner rather than
assumed:

- **Retention: roll up, don't keep raw forever.** `retention.py` collapses
  a raw month into one `logs/daily/YYYY-MM.jsonl` row per (unit, day) —
  checks, ok, avail_pct, p50_ms, p95_ms — then deletes the raw file. Nothing
  runs this automatically from `check`; `monitor.py rollup` is invoked by
  hand or by `.github/workflows/rollup.yml` (monthly, 1st of the month,
  `workflow_dispatch` also available with `--dry-run`). Default cutoff is
  365 days — comfortably past the 31-day window everything else reads, so
  this is about capping raw growth, not shrinking what report.py/dashboard.py
  see. Re-running is always safe: a month with an existing daily file is
  skipped, never redone. The daily archive is not read by anything today;
  a future multi-year-trend feature reads `logs/daily/*.jsonl` directly.
- **Per-host concurrency cap: yes, default 4.** The service owner has not
  confirmed the monitor's load is fine, so `check.HostLimiter` now bounds
  concurrent in-flight requests per host independent of `--workers`
  (`cli.py`'s `--max-per-host`, default `check.DEFAULT_MAX_PER_HOST`). Timing
  starts only once a slot is actually held, for the same reason `CertCache`'s
  timing starts after the certificate probe — a queueing wait is not the
  service's response time. Expected this to noticeably lengthen the run,
  since keskkonnaandmed.envir.ee carries 279 of 283 endpoints and the cap
  drops available concurrency there from up to 12 to 4 — measured instead of
  assumed (see "Actions minutes" below), and it turned out not to matter: 42 s
  for the check step, against 43 s before. That one measurement had nothing
  to retry, though, so it says nothing about a run during a real outage.
- **SLO targets: not decided here.** Still an agreement to make with the
  monitored systems' owners, not a code change — genuinely out of scope for
  this file.
- **`discover.from_ckan`: kept, documented as untested, now unit-tested
  against a synthetic payload.** No real CKAN catalogue was available to this
  project to verify it against. `cli.py` prints a warning whenever `--ckan` is
  used; the module and function docstrings say so plainly. Unit tests
  (`CkanDiscovery` in `tests/test_monitor.py`) exercise the parsing logic
  against a payload shaped like CKAN's own `package_search` documentation —
  that is not the same claim as "tested against a real catalogue", and the
  docstring is careful to say so.
- **Per-system latency: two groups, not six.** The response-time chart used
  to pool everything into one line, comparing KAIA (file downloads) against
  every PostgREST system. Splitting into all six systems was rejected as more
  chart complexity than the management audience needs and would have needed
  a new 6-colour validated palette; splitting into exactly two groups
  (PostgREST-backed systems vs. KAIA) reuses the two series colours already
  validated. `dashboard.py` partitions raw records by `system_of[id] ==
  "KAIA"` (a record naming an id outside the current unit list goes to
  neither side, same reasoning as Hetkeseis) and pools each side through
  `_daily` separately into `daily_postgrest`/`daily_kaia`; `app.js` draws one
  line per group with a real gap (not an interpolated value) on any day a
  group had no checks, and states each group's median range in the chart's
  text summary.
