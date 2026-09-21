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

**...but "two checks in a row" is not "two of anything in particular".** That
bar counts checks and quietly assumes a check is cheap and the next one is
along in half an hour. Measured 2026-09-18 (run 231): keskkonnaandmed.envir.ee
stopped answering, 303 of 308 endpoints timed out at 30 s each, and because
`HostLimiter` admits four at a time the run *itself* took 72 minutes. The next
run found everything healthy, so a second consecutive failure never arrived and
a 72-minute outage of nearly every monitored service notified nobody —
`Teavitused: 0 avatud, 0 suletud`. `notify_issues._broad_outage()` is the second
way in: if at least a third of the non-`unknown` units are failing in one check
(`BROAD_SHARE`, `BROAD_MIN_UNITS`), it opens **one aggregate issue** immediately,
without waiting. One, not forty — run 231 would have opened fifteen per-unit
issues, which is the same noise the group mechanism exists to avoid. The
per-unit rule is untouched, so a single service still has to fail twice.
Unverified units count towards the share, unlike in the per-unit rule: a wrong
query explains one unit failing, not forty at once. `unknown` units are
excluded from both sides of the ratio, so an all-`unknown` run — the checker's
own network — cannot trip it.

**`commit_and_push.sh` must never leave a half-finished rebase behind.**
Measured 2026-09-18 (run 233): the run was queued 12.5 minutes behind run 231,
so `actions/checkout` took the SHA the run was *created* with and the push lost
the race. The retry's `git pull --rebase` then hit a content conflict in
`REPORT.md` and `docs/data/status.json`, `|| true` swallowed it, and attempts
2–5 all failed on the wreckage instead — `fatal: You are not currently on a
branch`, `fatal: ... already a rebase-merge directory` — so the cycle's 308
checks were computed, logged locally and thrown away. Three things keep the
retries independent now: `git rebase --abort` before each one, `-X theirs` so a
generated-file conflict resolves instead of stopping (safe because `REGEN_CMD`
overwrites both files immediately after, and the `merge=union` driver in
`.gitattributes` outranks a strategy option, so the log still combines), and
`git push origin HEAD:$ref` so a detached HEAD cannot break the push. Verified
by replaying the same race against both the old and the new script.

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

**From the workflow-run analysis of 2026-09-18 (runs 219–238).** Two findings
from that analysis are fixed and written up under "Design decisions" above; the
rest are tracked here rather than done, because each is a judgement call or a
change to what the published numbers mean. All figures below are measured.

- **A single-host outage costs 72 minutes of runtime, not 42 seconds.** 279 of
  308 enabled endpoints sit on `keskkonnaandmed.envir.ee`; `_DEFAULT_TIMEOUT_S`
  30 s plus `_RETRY_DELAY_S` 5 s plus the retry is 65 s per failing endpoint,
  and `DEFAULT_MAX_PER_HOST` 4 serialises them: 279/4 × 65 s ≈ 4 550 s against
  the 4 313 s actually measured, agreement within 5 %. This is exactly the cost
  the "Actions minutes" note above said had not been measured during a real,
  widespread outage. It has now. The proposed fix is a per-host circuit
  breaker — after N consecutive *connection-level* failures on a host (timeout
  or refused, never an HTTP status) mark the rest of that host's endpoints
  without dialling, which also stops hammering a service that is already
  struggling. Not done: N is a guess until the pattern recurs, and the
  alternative (a whole-run `--deadline-s`, writing partial results and
  `unknown` for the rest) needs `analysis.py` to not read a short run as good
  news.
- **A run longer than ~30 minutes silently loses a cycle.** Run 232 was
  cancelled at 16:35:10, one second after run 233 was created, while run 231
  held the `api-monitor` lock until 16:47:35. A concurrency group holds one
  running plus one pending job; a third arrival cancels the pending one, and
  `cancel-in-progress: false` governs only the running one. `list_workflow_jobs`
  on 232 returns zero jobs, so nothing was logged and the page just has a hole
  with no marker. Fixing the item above removes the cause; a `timeout-minutes`
  backstop on the job is the cheap half-measure, but killing the job writes
  nothing at all.
- **429 was recorded as `down`, which was wrong on the public page — the word
  is fixed (2026-09-20), the arithmetic is not.** Nine endpoints answered `429
  Too Many Requests` with a Cloudflare HTML body across runs 231 and 233:
  five on `ilmateenistus.ee`/`www.ilmateenistus.ee`, two of three on
  `kytus.envir.ee`, plus `pakis.envir.ee` and `proto.envir.ee`. **Correction,
  measured over the six days since (2026-09-20, 11 181 records):**
  `kytus-source-of-pollution` is not the exception it looked like from two
  runs — it now shows 429 on 46 % of its checks (87/188), the highest share of
  any endpoint, and answers normally in between. The limit is intermittent
  per-path, not per-host and not permanent for any one path. `docs/app.js`'s
  `displayStatus()` now shows "Piiratud (429)" instead of "Maas" whenever the
  latest record is `status: down, http: 429` — a working service is no longer
  labelled dead. This is deliberately **display-only**: the stored `status`
  field, and every availability percentage computed from it, is untouched, so
  a 429 still counts as a failed check exactly as before. Taking it out of the
  availability arithmetic is a separate, larger decision — it would *raise*
  the published figures and break comparability with existing history, needing
  the same kind of transition note in `REPORT.md` as the `v: 2` schema change
  — and stays undone. Logging `Retry-After`, `Server` and `cf-ray` on 4xx/5xx
  also stays undone; see below.
- **Measured 2026-09-21: it is very unlikely to be our own request volume,
  and the exact mechanism is still unknown.** Three things rule out "we
  triggered a volume threshold": our observed cadence to the affected hosts
  is one check per ~33 minutes per endpoint (at most 3 concurrent, on
  `kytus.envir.ee`) — far below any ordinary rate limit; the host that gets
  by far our heaviest traffic, `keskkonnaandmed.envir.ee` (279 endpoints,
  7 266 checks in this log), has **never** returned a 429, while the five
  affected hosts (`proto.envir.ee` 57.7 %, `pakis.envir.ee` 56.9 %,
  `kytus.envir.ee` 55.1 %, `ilmateenistus.ee` 43.1 %,
  `www.ilmateenistus.ee` 13.7 % of checks) all carry a handful of endpoints
  each; and each endpoint logs 24–44 separate 429 *episodes* a week, flipping
  on and off every check or two rather than one sustained block — inconsistent
  with a fixed-window counter reacting to our own unchanging traffic.
  Cross-host correlation points at something shared behind those five
  properties rather than each one reacting independently: `kytus-monitoring`
  and `kytus-bunkering-company` (same host) both ran 429 2026-09-21T00:05–
  02:37; `proto-opendata` (a *different* host) ran 429 21:35–02:37 the same
  night, ending within a second of the other two. Best-supported hypothesis,
  not confirmed: Cloudflare bot-detection on these five ordinary-website
  properties reacting to the client fingerprint (User-Agent, no JS challenge,
  TLS fingerprint), not to request count — consistent with
  `keskkonnaandmed.envir.ee` being a PostgREST API with no such layer at all.
  Still unconfirmed and unconfirmable from this log: whether the actual
  trigger is the User-Agent, the TLS/JA3 fingerprint, or the GitHub Actions
  runner's shared IP reputation. Logging `Retry-After`, `Server` and `cf-ray`
  on 4xx/5xx remains the cheapest way to narrow it further; until that is
  done, do not assert which of the three it is.
- **`monitor.yml`'s billing header and the Pages note below it are stale.**
  Lines 15–25 of the workflow say "This repository is private" and compute
  1 440 min against a 2 000-minute allowance. The repository is public now,
  Actions is unmetered and Pages serves the status page from `main/docs`. Worth
  keeping in the rewrite: five of the eighteen normal runs in that window
  crossed 60 s (48–83 s, median 54 s), so if the repository ever goes private
  again the real bill is 2 880 minutes, not 1 440.
- **Both pinned actions target Node 20**, which every run now warns is
  deprecated and force-runs on Node 24. Harmless today. When the SHAs are
  raised, verify the new SHA rather than deriving it from a tag.
- **Do not "fix" the cron.** `*/30` delivered 23.7–35.2 minute intervals
  (median 29.1) across those twenty runs. That is GitHub queueing scheduled
  workflows, not a defect, and no cron spelling changes it. It does mean the
  log's cadence is nominal: anything interval-weighted must use the records'
  own timestamps, which `analysis.py` already does.

**Status-page comprehensibility round (2026-09-20).** The 2026-09-18 rewrite
(sortable tables, per-row history strips, sparklines) left seven further
ideas as "recommended, not built". Each was actually prototyped against real
data — headless Chromium, the live log, no invented numbers — rather than
argued for or against on paper, on the request to test whether it genuinely
helps before shipping it. Shipped, in `dashboard.py` and `docs/`:

- **A range control (7 / 14 / 30 päeva / Kõik)** now governs both trend charts
  and every per-row/per-card history cell at once (`rangeDays` in `app.js`;
  purely client-side, no new backend field — it slices the arrays
  `chart_dates` already carries). **Honest finding:** the log is currently 7
  days old, so "7 päeva" and "Kõik" render identically today — measured, not
  guessed, by comparing the rendered strip width at both settings. The control
  is real infrastructure for when the log is actually 30 days deep; today it
  is mostly inert, and that is stated on the page itself rather than left for
  a reader to notice.
- **`outages_by_system`**, the same incident tally as `outages_by_endpoint`
  but summed by service. EELIS's 261 members and `keskkonnaandmed-root`'s
  group never individually crack the top-10-by-endpoint chart, so their
  downtime was invisible to a reader thinking in services rather than tables
  — this is the same incidents, cut the other way, not new data.
- **`docs/data/incidents.xml`**, an RSS 2.0 feed of the 50 most recent
  incidents, regenerated by `dashboard.write()` alongside `status.json`. A
  429's error body is Cloudflare's own HTML page, truncated verbatim into
  `detail` — CDATA is used for the description, with the standard
  `]]>`-splitting escape, because that literal sequence closing a CDATA
  section early is a real failure mode this data could hit, not a
  hypothetical one; there is a test for it (`IncidentsFeed` in
  `tests/test_monitor.py`). `PAGE_URL` hardcodes the same GitHub Pages address
  already hardcoded in the footer's Issues link — the "never write an
  endpoint URL into source" rule is about invented targets for the checker to
  call, not this project's own published identity. **Known limitation, not
  fixable from here:** GitHub Pages serves static files by extension with no
  way to set a custom `Content-Type` header, so `.xml` will not necessarily
  arrive as `application/rss+xml`; feed readers are conventionally lenient
  about this, but it has not been verified against a real one.
- **Row permalinks** (`#row-<id>`, matching the feed's own item links). Tested
  the case that actually matters: opening the page with a hash pointing at a
  currently-healthy endpoint that the default filter hides. It works —
  filters clear, the row scrolls into view and gets a three-second highlight —
  and the page says in the table note that it widened the view, rather than
  silently changing what a reader had set.

Tested and **not** shipped, with the reasoning that survived contact with
real data:

- **A trend arrow.** Computed for real over the available week: splitting
  `daily` into first-half/second-half average gives 99.9 % → 86.8 %, which
  *looks* like a damning downward trend. It is not one — it is a single step
  change starting 2026-09-17 when the 429 pattern above intensified, not
  gradual decay, and seven days containing exactly one such event cannot
  distinguish "trend" from "one thing happened." An arrow would have been
  true and misleading in the same breath. Revisit once the log holds enough
  history to tell a step from a slope.
- **An SLA-compliance indicator.** Building the disabled/placeholder state
  was considered and rejected: a permanently-off control is maintenance
  surface with no reader value, and the real blocker — no agreed threshold —
  is unchanged from the 2026-09-15 decision below. Nothing to prototype until
  that conversation happens.
- **Usage data** (which clients call which endpoints). Confirmed again: this
  page monitors reachability, not traffic, and answering "which endpoints do
  people actually use" needs the service owners' own request logs — a
  different data source and a different project, not a rendering choice.

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
