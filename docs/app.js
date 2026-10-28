/* Reads docs/data/status.json and draws the page.
 *
 * Nothing here invents data. Where the log has too little history to plot, the
 * chart is replaced by a sentence saying so — a status page that draws a
 * confident line over two points is worse than one that admits it is new.
 */

const STATUS_WORD = {
  ok: "Korras",
  degraded: "Häire",
  down: "Maas",
  limited: "Piiratud (429)",
  unknown: "Teadmata",
  unchecked: "Kontrollimata",
};

/* Sorting the status column by name would put "Häire" before "Maas" and bury
 * the thing an operator opened the page for. Ascending is worst-first.
 * "limited" sits with "down" (same tier, not a lesser problem — it still
 * fails every request a client makes) rather than getting its own rank. */
const SEVERITY = { down: 0, limited: 0, degraded: 1, unknown: 2, unchecked: 3, ok: 4 };

/* A record logged as "down" with HTTP 429 is not the service being unreachable
 * — it is the service answering and refusing this client, which nine
 * endpoints do routinely (measured 2026-09-18/19/20: 773 of 11 181 records,
 * 6.9 %, spread across ilmateenistus.ee, kytus.envir.ee, pakis.envir.ee and
 * proto.envir.ee). "Maas" on those rows told a reader a working service was
 * dead. This is a display relabelling only: the underlying status, and every
 * availability number computed from it, is unchanged — a 429 still counts as
 * a failed check, same as before. Only the word a human reads is corrected.
 * See CLAUDE.md's "Open work" for why the arithmetic itself is a separate,
 * versioned decision and not this one. */
function displayStatus(status, http) {
  return status === "down" && http === 429 ? "limited" : status;
}

/* Day-cell colour bands for the history strip. These are a presentation
 * choice, not a service level: no SLA has been agreed with the service
 * owners, so the page says so in "Kuidas seda mõõdetakse" rather than
 * implying 95 % is a permitted floor. */
const BAND_OK = 100;
const BAND_WARN = 95;

const SVG_NS = "http://www.w3.org/2000/svg";
// 30 days at this pitch is 149 px, which is what lets both the strip and the
// sparkline sit in the table without pushing it into horizontal scrolling on
// an ordinary laptop. A cell this thin is a poor mouse target, so each one is
// overlaid with a transparent full-pitch rect that carries the tooltip.
const CELL_W = 4;
const CELL_GAP = 1;
const CELL_H = 22;

const TZ = "Europe/Tallinn";
const charts = [];
let snapshot = null;
let rows = [];
const sortState = {
  endpoints: { key: null, dir: 1 },
  events: { key: null, dir: 1 },
  systemOutages: { key: null, dir: 1 },
};

/* The trend charts and every per-row strip/sparkline share one selected
 * window, in days; null means "everything the log has". Kept as page state
 * rather than per-chart so the range control affects the whole "Ajatrendid"
 * section and the table's history cells consistently — a reader comparing
 * the pooled chart against one row's strip should be looking at the same
 * days in both. */
let rangeDays = null;

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function moment(iso) {
  if (!iso) return "–";
  const when = new Date(iso);
  if (Number.isNaN(when.valueOf())) return "–";
  return when.toLocaleString("et-EE", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function day(iso) {
  const when = new Date(`${iso}T12:00:00Z`);
  return when.toLocaleDateString("et-EE", { timeZone: TZ, day: "2-digit", month: "2-digit" });
}

function duration(seconds) {
  if (seconds == null) return "–";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} p ${hours % 24} h`;
}

const pct = (value) => (value == null ? "–" : `${value.toFixed(1)} %`);
const millis = (value) => (value == null ? "–" : `${value} ms`);

/* The shortest and longest an outage can have lasted, given when we looked
 * (dashboard.py computes both). With checks hours apart a single figure
 * claims a precision the log does not have. A lower bound under a minute is
 * one failed check: all we know is "up to" the upper bound. */
function durationRange(low, high) {
  if (low == null) return "–";
  if (high == null) return `vähemalt ${duration(low)}`;
  if (low < 60) return `kuni ${duration(high)}`;
  const a = duration(low);
  const b = duration(high);
  return a === b ? a : `${a} – ${b}`;
}

/* Wilson score interval for ok/n, in percent. Brown, Cai & DasGupta (2001,
 * Statistical Science 16(2)) show the textbook Wald interval behaves
 * erratically at small n — exactly the case here, where one unit has six
 * checks a day — and recommend Wilson's. It assumes independent checks; ours
 * are not quite (same host, same run), which the page says in words. */
function wilson(ok, n, z = 1.96) {
  if (!n) return null;
  const p = ok / n;
  const z2 = z * z;
  const denominator = 1 + z2 / n;
  const centre = (p + z2 / (2 * n)) / denominator;
  const half = (z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / denominator;
  return [100 * Math.max(0, centre - half), 100 * Math.min(1, centre + half)];
}

function intervalText(interval) {
  if (!interval) return "–";
  const [low, high] = interval;
  // Whole percents once the interval is wide: "10.3–69.6 %" implies a
  // precision the interval itself says is not there.
  const digits = high - low < 10 ? 1 : 0;
  return `${low.toFixed(digits)}–${high.toFixed(digits)} %`;
}

/* "232/252 kontrolli, 95 % vahemik 88.1–94.8 %". status.json written before
 * the counts were added carries only the percentage and n; the success count
 * is recovered from those rather than shown as missing. */
function countsText(avail, ok, n) {
  if (!n) return "kontrolle ei ole";
  const k = ok ?? Math.round(((avail ?? 0) * n) / 100);
  return `${k}/${n} kontrolli, 95 % vahemik ${intervalText(wilson(k, n))}`;
}
const okCount = (avail, ok, n) => ok ?? (n ? Math.round(((avail ?? 0) * n) / 100) : 0);

/* Plain words for dashboard.classify_cause's keys. The raw detail — for a 429,
 * Cloudflare's own HTML page — stays one click away in each event's details,
 * but it is not what a reader deciding "is this real" should parse first. */
const CAUSE_WORD = {
  rate_limited: "Päring piirati (HTTP 429)",
  not_dialled: "Jäeti kontrollimata — host ei vastanud",
  dns: "Nime ei leitud (DNS)",
  no_response: "Ei vastanud",
  server_error: "Serveri viga (HTTP 5xx)",
  client_error: "Päring lükati tagasi (HTTP 4xx)",
  service_exception: "Teenus vastas veateatega",
  stale: "Andmed vananenud",
  unreadable: "Vastus ei olnud loetav",
  check_error: "Kontrolli enda viga",
  other: "Muu",
};

function chip(status) {
  const span = document.createElement("span");
  span.className = `chip ${status}`;
  span.textContent = STATUS_WORD[status] || status;
  return span;
}

const sum = (values) => values.reduce((total, value) => total + (value || 0), 0);
const share = (ok, checks) => (checks ? (100 * ok) / checks : null);

/* Where a date array should start for the current `rangeDays` window. Cutting
 * by count of trailing entries, not by calendar days back from today: the
 * arrays already contain only days that had checks (a day with none is
 * simply absent), so "last 7 entries" is "last 7 days that actually have
 * data" — consistent with the rest of the page never drawing a confident
 * line over a gap. Asking for a wider window than exists is not an error;
 * it just returns everything, the same way "30 päeva" and "Kõik" render
 * identically until the log is actually that old. */
function rangeStart(length) {
  if (rangeDays == null) return 0;
  return Math.max(0, length - rangeDays);
}

function band(avail) {
  if (avail == null) return "none";
  if (avail >= BAND_OK) return "ok";
  if (avail >= BAND_WARN) return "warn";
  return "bad";
}

function svgEl(name, attrs) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function titled(node, text) {
  const title = document.createElementNS(SVG_NS, "title");
  title.textContent = text;
  node.append(title);
  return node;
}

/* ---------- per-unit history, drawn in the row itself ---------- */

/* One cell per day, aligned column-for-column down the table so a bad day
 * reads as a vertical stripe across every unit it touched — the pattern
 * Atlassian Statuspage and Grafana's status-history panel both use. Colour is
 * never the only carrier: every cell has its exact numbers on hover, the
 * strip as a whole has an aria-label, and the same figures are in the
 * adjacent 24 h / 7 päeva columns as text. */
function uptimeStrip(dates, checks, ok) {
  const width = Math.max(1, dates.length * (CELL_W + CELL_GAP) - CELL_GAP);
  const svg = svgEl("svg", {
    class: "strip",
    width,
    height: CELL_H,
    viewBox: `0 0 ${width} ${CELL_H}`,
    role: "img",
  });
  const windowAvail = share(sum(ok), sum(checks));
  const measured = dates.filter((_, i) => (checks[i] || 0) > 0).length;
  svg.setAttribute(
    "aria-label",
    windowAvail == null
      ? "Selle otspunkti kohta ei ole perioodil kontrolle."
      : `Kättesaadavus ${measured} mõõdetud päeval kokku ${windowAvail.toFixed(1)} %.`,
  );
  dates.forEach((date, index) => {
    const dayChecks = checks[index] || 0;
    const dayOk = ok[index] || 0;
    const avail = share(dayOk, dayChecks);
    const left = index * (CELL_W + CELL_GAP);
    svg.append(
      svgEl("rect", {
        x: left,
        y: 0,
        width: CELL_W,
        height: CELL_H,
        rx: 1.5,
        class: `cell ${band(avail)}`,
      }),
    );
    svg.append(
      titled(
        svgEl("rect", {
          x: left,
          y: 0,
          width: CELL_W + CELL_GAP,
          height: CELL_H,
          class: "hit",
        }),
        avail == null
          ? `${day(date)}: ei kontrollitud`
          : `${day(date)}: ${avail.toFixed(1)} % (${dayOk}/${dayChecks} kontrolli)`,
      ),
    );
  });
  return svg;
}

/* A response-time sparkline per row. The pooled chart above answers "is the
 * platform slow today"; it cannot answer "is this endpoint slower than it
 * was", which is the question an owner of one endpoint actually has, and
 * answering it used to require hovering. Deliberately unlike the big charts:
 * no axes, no markers on every point, and the current value printed beside
 * the line — at 22 px tall a legible number carries the reading, not the
 * pixels. */
function latencySparkline(dates, p50) {
  const width = Math.max(1, dates.length * (CELL_W + CELL_GAP) - CELL_GAP);
  const points = p50.map((value, index) => ({ value, index })).filter((p) => p.value != null);
  if (points.length < 2) return null;

  const values = points.map((p) => p.value);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const x = (index) => (dates.length < 2 ? 0 : (index / (dates.length - 1)) * width);
  const y = (value) => CELL_H - 3 - ((value - low) / span) * (CELL_H - 6);

  const svg = svgEl("svg", {
    class: "spark",
    width,
    height: CELL_H,
    viewBox: `0 0 ${width} ${CELL_H}`,
    role: "img",
    "aria-label": `Ööpäeva mediaanvastuseaeg ${low}–${high} ms, viimati ${values[values.length - 1]} ms.`,
  });
  svg.append(
    svgEl("polyline", {
      class: "spark-line",
      points: points.map((p) => `${x(p.index).toFixed(1)},${y(p.value).toFixed(1)}`).join(" "),
    }),
  );
  const last = points[points.length - 1];
  svg.append(
    svgEl("circle", { class: "spark-dot", cx: x(last.index).toFixed(1), cy: y(last.value).toFixed(1), r: 3 }),
  );
  return svg;
}

/* ---------- summary tiles ---------- */

/* Which service is currently costing the most trust. A management reader
 * scanning four averages cannot tell whether 97 % overall is "everything is
 * fine" or "one service is on the floor and the rest carry the mean" — and in
 * this log that difference is real. Named, not colour-coded.
 *
 * Ranked by the upper end of the Wilson interval, not the point value: with
 * six checks a day one unlucky check moves a single-unit service by 17
 * points, and "weakest" should mean "even at best, lowest". When the winner's
 * interval overlaps the runner-up's, the tile says the order is not settled
 * rather than leaving a confident-looking ranking. */
function worstSystemTile(data) {
  const measured = (data.systems || [])
    .filter((s) => s.avail_24h != null && s.checks_24h)
    .map((s) => {
      const ok = okCount(s.avail_24h, s.ok_24h, s.checks_24h);
      return { ...s, ok_24h: ok, interval: wilson(ok, s.checks_24h) };
    })
    .sort((a, b) => a.interval[1] - b.interval[1] || a.avail_24h - b.avail_24h);
  if (!measured.length) {
    return { label: "Nõrgim teenus 24 h", value: "–", sub: "Viimase ööpäeva kohta ei ole mõõtmisi." };
  }
  const [worst, next] = measured;
  const overlaps = next && next.interval[0] <= worst.interval[1];
  return {
    label: "Nõrgim teenus 24 h",
    value: pct(worst.avail_24h),
    sub:
      `${worst.name} · ${countsText(worst.avail_24h, worst.ok_24h, worst.checks_24h)}` +
      (overlaps ? ` · järjestus pole kindel: vahemik kattub teenuse ${next.name} omaga` : ""),
  };
}

function renderTiles(data) {
  const t = data.totals || {};
  const a = data.availability || {};
  const problem = (t.down || 0) + (t.degraded || 0);
  const tiles = [
    {
      label: "Teenused korras",
      value: `${t.ok || 0} / ${t.endpoints || 0}`,
      sub: problem ? `${problem} otspunkti vajab tähelepanu` : "Kõik jälgitavad otspunktid vastavad",
    },
    {
      label: "Kättesaadavus 24 h",
      value: pct(a.h24),
      sub: countsText(a.h24, a.ok_24h, a.checks_24h),
    },
    {
      label: "Kättesaadavus 7 päeva",
      value: pct(a.d7),
      // Older status.json has no 7-day count; the tile then says only what it
      // is, instead of an interval built from a guessed n.
      sub: a.checks_7d ? countsText(a.d7, a.ok_7d, a.checks_7d) : "Õnnestunud kontrollide osakaal",
    },
    worstSystemTile(data),
    {
      // Events, not per-endpoint incidents: one rate limit switching on
      // across five endpoints is one thing that happened. The summed
      // "endpoints down in total" figure this tile used to carry is gone on
      // purpose — it added overlapping outages together and, with checks
      // hours apart, read 56 days for a 31-day window.
      label: "Sündmusi logis",
      value: String(data.event_count ?? data.incident_count ?? 0),
      sub:
        data.event_count != null
          ? `${data.event_count_verified} puudutab kinnitatud otspunkte · ` +
            `${data.incident_count} otspunkti katkestust`
          : `Jälgimine algas ${data.first_record ? moment(data.first_record) : "–"}`,
    },
  ];

  $("tiles").replaceChildren(
    ...tiles.map((item) => {
      const box = document.createElement("div");
      box.className = "tile";
      box.innerHTML = `<p class="label"></p><p class="value"></p><p class="sub"></p>`;
      box.querySelector(".label").textContent = item.label;
      box.querySelector(".value").textContent = item.value;
      box.querySelector(".sub").textContent = item.sub;
      return box;
    }),
  );
}

/* ---------- system cards ---------- */

function renderSystems(data) {
  $("systems").replaceChildren(
    ...(data.systems || []).map((system) => {
      const card = document.createElement("div");
      card.className = "card";

      const title = document.createElement("h3");
      title.textContent = system.name;
      title.append(chip(system.problem ? "down" : system.ok ? "ok" : "unchecked"));

      const text = document.createElement("p");
      text.textContent = system.description || "Kirjeldus puudub.";

      const meta = document.createElement("p");
      meta.className = "meta";
      meta.textContent =
        `${system.ok} / ${system.endpoints} jälgitavat üksust korras · ` +
        `kättesaadavus 24 h ${pct(system.avail_24h)}` +
        (system.checks_24h ? ` (${countsText(system.avail_24h, system.ok_24h, system.checks_24h)})` : "");

      card.append(title, text, meta);

      // Pooled the same way dashboard.py pools a system's availability: sum
      // the members' raw ok and checks per day, never average their
      // percentages, or a member with three checks would weigh as much as one
      // with three hundred.
      const allDates = data.chart_dates || [];
      const start = rangeStart(allDates.length);
      const dates = allDates.slice(start);
      const members = rows.filter((r) => r.system === system.name);
      if (dates.length && members.length) {
        const checks = dates.map((_, i) => sum(members.map((m) => m._checks[start + i])));
        const ok = dates.map((_, i) => sum(members.map((m) => m._ok[start + i])));
        const strip = document.createElement("p");
        strip.className = "card-strip";
        strip.append(uptimeStrip(dates, checks, ok));
        const range = document.createElement("span");
        range.className = "strip-range";
        range.textContent = `${day(dates[0])} → ${day(dates[dates.length - 1])}`;
        strip.append(range);
        card.append(strip);
      }
      return card;
    }),
  );
}

/* ---------- sorting ---------- */

/* Turning each header into a real <button> rather than a click handler on the
 * <th>: it lands in the tab order, fires on Enter and Space for free, and
 * aria-sort tells a screen reader which column is active and which way. */
function attachSorting(tableId, stateKey, rerender) {
  document.querySelectorAll(`#${tableId} th[data-sort]`).forEach((th) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sort";
    button.textContent = th.textContent.trim();
    button.append(svgArrow());
    th.textContent = "";
    th.setAttribute("aria-sort", "none");
    th.append(button);
    button.addEventListener("click", () => {
      const state = sortState[stateKey];
      if (state.key === th.dataset.sort) state.dir = -state.dir;
      else {
        state.key = th.dataset.sort;
        state.dir = 1;
      }
      rerender();
    });
  });
}

function svgArrow() {
  const span = document.createElement("span");
  span.className = "arrow";
  span.setAttribute("aria-hidden", "true");
  return span;
}

function applySort(items, tableId, stateKey) {
  const state = sortState[stateKey];
  const heads = [...document.querySelectorAll(`#${tableId} th[data-sort]`)];
  heads.forEach((th) => {
    const active = th.dataset.sort === state.key;
    th.setAttribute("aria-sort", active ? (state.dir === 1 ? "ascending" : "descending") : "none");
    th.querySelector(".arrow").textContent = active ? (state.dir === 1 ? "▲" : "▼") : "";
  });
  if (!state.key) return items;

  const type = heads.find((th) => th.dataset.sort === state.key)?.dataset.type || "text";
  const missing = (value) => value == null || value === "";
  return [...items].sort((a, b) => {
    const left = a[state.key];
    const right = b[state.key];
    // Rows with no value sink to the bottom whichever way the column is
    // sorted — otherwise "sort by response time" fills the top of the table
    // with endpoints that have never answered at all.
    if (missing(left) && missing(right)) return 0;
    if (missing(left)) return 1;
    if (missing(right)) return -1;
    const order =
      type === "number" ? left - right : String(left).localeCompare(String(right), "et");
    return order * state.dir;
  });
}

/* ---------- tables ---------- */

/* Everything the table needs that status.json does not carry directly: a
 * sortable severity rank, the whole-window availability behind the strip, and
 * the latest daily median behind the sparkline. Computed once per load rather
 * than per render, and kept beside the raw arrays the two SVGs read. */
function decorate(data) {
  const dates = data.chart_dates || [];
  return (data.endpoints || []).map((endpoint) => {
    const days = endpoint.days || {};
    const checks = days.checks || dates.map(() => 0);
    const ok = days.ok || dates.map(() => 0);
    const p50 = days.p50_ms || dates.map(() => null);
    const recent = [...p50].reverse().find((value) => value != null);
    return {
      ...endpoint,
      severity: SEVERITY[endpoint.status] ?? 9,
      avail_window: share(sum(ok), sum(checks)),
      p50_last: recent == null ? null : recent,
      _checks: checks,
      _ok: ok,
      _p50: p50,
    };
  });
}

function filtered(data) {
  const showAll = $("show-all").checked;
  const needle = $("filter-text").value.trim().toLowerCase();
  const system = $("filter-system").value;
  return rows.filter((item) => {
    if (!showAll && item.status === "ok") return false;
    if (system && item.system !== system) return false;
    if (needle && !`${item.name} ${item.id}`.toLowerCase().includes(needle)) return false;
    return true;
  });
}

function renderEndpoints(data) {
  const showAll = $("show-all").checked;
  const all = rows;
  const narrowed = filtered(data);
  const shown = applySort(narrowed, "endpoints", "endpoints");
  const narrowing = $("filter-text").value.trim() !== "" || $("filter-system").value !== "";
  $("filter-reset").hidden = !narrowing;

  $("table-note").textContent = narrowing
    ? `Näidatakse ${shown.length} otspunkti ${all.length}-st.`
    : showAll
      ? `Kõik ${all.length} otspunkti.`
      : shown.length
        ? `Näidatakse ${shown.length} otspunkti, mis ei ole korras.`
        : `Kõik ${all.length} otspunkti on korras — probleeme ei ole.`;

  const allDates = data.chart_dates || [];
  const start = rangeStart(allDates.length);
  const dates = allDates.slice(start);
  $("strip-legend").replaceChildren(
    ...(dates.length
      ? [
          legendKey("ok", "kõik kontrollid õnnestusid"),
          legendKey("warn", `vähemalt ${BAND_WARN} %`),
          legendKey("bad", `alla ${BAND_WARN} %`),
          legendKey("none", "ei kontrollitud"),
          Object.assign(document.createElement("span"), {
            className: "legend-range",
            textContent: `Ajalugu: ${day(dates[0])} → ${day(dates[dates.length - 1])}, üks ruut on üks ööpäev.`,
          }),
        ]
      : []),
  );

  document.querySelector("#endpoints").hidden = shown.length === 0;
  const body = document.querySelector("#endpoints tbody");
  body.replaceChildren(
    ...shown.map((item) => {
      const row = document.createElement("tr");
      // The anchor a permalink and the RSS feed's <link> both point at
      // (dashboard.py's render_incidents_feed uses the same "row-<id>"
      // shape), so a link from either source lands on this exact row.
      row.id = `row-${item.id}`;

      const name = document.createElement("td");
      const link = document.createElement("a");
      link.className = "row-link";
      link.href = `#row-${item.id}`;
      link.title = "Püsilink sellele reale";
      link.setAttribute("aria-label", `Püsilink: ${item.name}`);
      link.textContent = item.name;
      name.append(link);
      if (!item.verified) {
        const flag = document.createElement("span");
        flag.className = "unverified-flag";
        flag.textContent = "kinnitamata";
        flag.title = "URL-i pole inimene üle vaadanud — vt jaotist “Kuidas seda mõõdetakse”.";
        name.append(" ", flag);
      }
      const id = document.createElement("span");
      id.className = "id";
      id.textContent = item.members ? `${item.id} · ${item.members} otspunkti` : item.id;
      name.append(id);

      const system = document.createElement("td");
      system.textContent = item.system;

      const status = document.createElement("td");
      status.append(chip(displayStatus(item.status, item.http)));

      const response = document.createElement("td");
      response.className = "num";
      response.textContent = item.http ? `${item.http} · ${millis(item.ms)}` : millis(item.ms);

      const d1 = availCell(item.avail_24h, item.ok_24h, item.checks_24h);
      const d7 = availCell(item.avail_7d, item.ok_7d, item.checks_7d);

      const history = document.createElement("td");
      history.className = "viz";
      history.append(
        uptimeStrip(dates, item._checks.slice(start), item._ok.slice(start)),
      );

      const latency = document.createElement("td");
      latency.className = "viz";
      const spark = latencySparkline(dates, item._p50.slice(start));
      if (spark) latency.append(spark);
      const sparkValue = document.createElement("span");
      sparkValue.className = "spark-value";
      // The number, not the line, is what makes this cell readable at 22 px —
      // and it is what a screen reader and a printout get.
      sparkValue.textContent = item.p50_last == null ? "–" : `${item.p50_last} ms`;
      latency.append(sparkValue);

      const last = document.createElement("td");
      last.className = "num";
      last.textContent = moment(item.ts);

      row.append(name, system, status, response, d1, d7, history, latency, last);
      return row;
    }),
  );
}

/* A percentage with the counts it came from underneath, and the interval on
 * hover: "50.0 %" over "3/6" says at a glance how little that 50 rests on. */
function availCell(avail, ok, n) {
  const cell = document.createElement("td");
  cell.className = "num";
  cell.textContent = pct(avail);
  if (n) {
    const k = okCount(avail, ok, n);
    const counts = document.createElement("span");
    counts.className = "counts";
    counts.textContent = `${k}/${n}`;
    cell.append(counts);
    cell.title = `${k}/${n} kontrolli õnnestus, 95 % vahemik ${intervalText(wilson(k, n))}`;
  }
  return cell;
}

function legendKey(kind, text) {
  const key = document.createElement("span");
  key.className = "legend-key";
  const swatch = document.createElement("span");
  swatch.className = `swatch ${kind}`;
  swatch.setAttribute("aria-hidden", "true");
  key.append(swatch, document.createTextNode(text));
  return key;
}

function cellWith(main, sub, className = "num") {
  const cell = document.createElement("td");
  cell.className = className;
  cell.append(main);
  if (sub) {
    const line = document.createElement("span");
    line.className = "subline";
    line.textContent = sub;
    cell.append(line);
  }
  return cell;
}

function memberName(id) {
  return rows.find((r) => r.id === id)?.name || id;
}

function memberLink(id) {
  const link = document.createElement("a");
  link.href = `#row-${id}`;
  link.textContent = memberName(id);
  return link;
}

/* One row per event: what happened, to how many, for how long at least and
 * at most. dashboard.py does the grouping (same cause, same check run); this
 * only words it. Events that touch no verified endpoint can be hidden — they
 * are as likely a wrong query as an outage, which is why they never open an
 * Issue either — but are shown by default, since hiding them silently would
 * hide most of today's log. */
function renderEvents(data) {
  const all = (data.events || []).map((event) => ({
    ...event,
    cause_word: CAUSE_WORD[event.cause] || CAUSE_WORD.other,
  }));
  const verifiedOnly = $("events-verified-only").checked;
  const shown = verifiedOnly ? all.filter((e) => e.verified > 0) : all;
  const body = document.querySelector("#events tbody");
  const empty = $("empty-events");

  const total = data.event_count ?? all.length;
  $("events-note").textContent =
    `${total} sündmust (${data.incident_count ?? 0} otspunkti katkestust), neist ` +
    `${data.event_count_verified ?? 0} puudutab vähemalt üht kinnitatud otspunkti. ` +
    (all.length < total ? `Tabelis on ${all.length} uuemat.` : "");

  empty.hidden = shown.length > 0;
  document.querySelector("#events").hidden = shown.length === 0;
  if (!shown.length) {
    empty.textContent = all.length
      ? "Kinnitatud otspunkte puudutavaid sündmusi tabelis ei ole."
      : "Logitud perioodil katkestusi ei ole.";
    body.replaceChildren();
    return;
  }

  body.replaceChildren(
    ...applySort(shown, "events", "events").map((event) => {
      const row = document.createElement("tr");
      const began = cellWith(
        moment(event.start),
        event.after ? `pärast ${moment(event.after)}` : "logi algusest",
      );
      began.title =
        "Esimene ebaõnnestunud kontroll; all viimane õnnestunud kontroll enne seda. " +
        "Tegelik algus jääb nende vahele.";
      const ended = cellWith(
        event.end ? moment(event.end) : "kestab",
        event.last_ts && event.last_ts !== event.start ? `viimati maas ${moment(event.last_ts)}` : "",
      );
      const lasted = cellWith(durationRange(event.min_s, event.max_s), "");
      lasted.title = `Esimesest ebaõnnestunud kontrollist esimese õnnestununi: ${duration(event.duration_s)}`;

      const reason = cellWith(event.cause_word, "", "reason");
      if (!event.verified) {
        const flag = document.createElement("span");
        flag.className = "unverified-flag";
        flag.textContent = "kinnitamata";
        flag.title = "Ükski selle sündmuse otspunkt ei ole kinnitatud — vt “Kuidas seda mõõdetakse”.";
        reason.append(" ", flag);
      }

      const affected = document.createElement("td");
      affected.className = "affected";
      const members = event.members || [];
      if (members.length === 1) affected.append(memberLink(members[0].id));
      else affected.append(`${event.count} otspunkti`);
      const systems = document.createElement("span");
      systems.className = "subline";
      systems.textContent = (event.systems || []).join(", ");
      affected.append(systems);

      const more = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Detailid";
      more.append(summary);
      if (members.length > 1) {
        const list = document.createElement("ul");
        members.forEach((member) => {
          const item = document.createElement("li");
          item.append(
            memberLink(member.id),
            ` — ${durationRange(member.min_s, member.max_s)}${member.end ? "" : ", kestab"}`,
          );
          list.append(item);
        });
        more.append(list);
      }
      if (event.detail) {
        const raw = document.createElement("code");
        raw.className = "raw";
        raw.textContent = event.detail;
        more.append(raw);
      }
      affected.append(more);

      row.append(began, ended, lasted, reason, affected);
      return row;
    }),
  );
}

/* A cut by service rather than by endpoint. The endpoint chart above never
 * surfaces EELIS or keskkonnaandmed-root, because no single one of their many
 * members individually cracks a top-10-by-endpoint ranking — the group's own
 * downtime is real but stays invisible sliced that way. A manager or product
 * owner thinks in services, not in which of 261 EELIS tables happened to
 * fail this week, so this is the same incidents, summed the other way. */
function renderSystemOutages(data) {
  const rows = applySort(data.outages_by_system || [], "system-outages", "systemOutages");
  const section = $("system-outages-section");
  const body = document.querySelector("#system-outages tbody");
  if (!rows.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  body.replaceChildren(
    ...rows.map((r) => {
      const row = document.createElement("tr");
      const name = document.createElement("td");
      name.textContent = r.name;
      const count = document.createElement("td");
      count.className = "num";
      count.textContent = String(r.count);
      // Calendar time with at least one endpoint failing, as a range — the
      // union across endpoints, never their sum (dashboard.py).
      const affected = document.createElement("td");
      affected.className = "num";
      affected.textContent = durationRange(r.affected_min_s, r.affected_max_s);
      affected.title = `Esimesest ebaõnnestunud kontrollist esimese õnnestununi: ${duration(r.affected_s)}`;
      row.append(name, count, affected);
      return row;
    }),
  );
}

/* ---------- deep links ---------- */

/* A row's permalink (#row-<id>) is only useful if the row is actually in the
 * DOM when the page opens with that hash in the URL — sharing a link to a
 * currently-healthy endpoint, or one filtered out by a service filter,
 * would otherwise land on a page that looks like the row does not exist.
 * Widening the view to guarantee the target is visible is the point; doing
 * it silently, without saying so, would be its own kind of confusing, so a
 * short note explains why filters just changed. */
function openDeepLink() {
  const hash = location.hash;
  if (!hash.startsWith("#row-")) return;
  const id = hash.slice(5);
  const exists = rows.some((r) => r.id === id);
  if (!exists) return;

  let widened = false;
  if (!$("show-all").checked) {
    $("show-all").checked = true;
    widened = true;
  }
  if ($("filter-system").value) {
    $("filter-system").value = "";
    widened = true;
  }
  if ($("filter-text").value) {
    $("filter-text").value = "";
    widened = true;
  }
  if (widened) renderEndpoints(snapshot);

  const target = document.getElementById(`row-${id}`);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("row-linked");
  if (widened) {
    $("table-note").textContent += " (filtrid tühistati, et püsilingiga rida oleks näha.)";
  }
  setTimeout(() => target.classList.remove("row-linked"), 3000);
}

/* ---------- charts ---------- */

function axisStyle() {
  return {
    grid: { color: css("--grid"), drawTicks: false, drawBorder: false },
    border: { display: false },
    ticks: {
      color: css("--muted"),
      font: { family: css("--font"), size: 11 },
      padding: 8,
      autoSkip: true,
      maxTicksLimit: 10,
      maxRotation: 0,
    },
  };
}

function baseOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: css("--ink"),
        titleColor: css("--surface"),
        bodyColor: css("--surface"),
        padding: 10,
        displayColors: true,
        boxWidth: 8,
        boxHeight: 8,
        usePointStyle: true,
      },
    },
  };
}

function showEmpty(id, message) {
  const note = $(id);
  note.textContent = message;
  note.hidden = false;
  note.previousElementSibling.hidden = true;
}

/* A short sentence standing in for each chart — read by screen readers via
 * aria-describedby, and visible to everyone else, so the data does not exist
 * only as pixels. Cleared (not left stale) whenever a chart is redrawn empty. */
function setSummary(id, text) {
  $(id).textContent = text;
}

function drawAvailability(data) {
  const all = data.daily || [];
  const rows = all.slice(rangeStart(all.length));
  if (rows.length < 2) {
    showEmpty(
      "empty-avail",
      rows.length === 1
        ? "Andmeid on ühe päeva kohta — ajajoone joonistamiseks on vaja vähemalt kahte päeva."
        : "Andmeid ei ole veel kogutud.",
    );
    setSummary("summary-avail", "");
    return;
  }
  const values = rows.map((r) => r.avail_pct);
  const lowest = Math.min(...values);
  // A fixed floor (e.g. always 90%) can make an ordinary blip look dramatic
  // when the real range is tiny, or hide real variation when it's wide. The
  // floor is derived from the data instead — 2 points of headroom below the
  // lowest value, rounded down to a multiple of 5 — and, since the axis is
  // truncated either way whenever the lowest value is above 0, the caption
  // states the actual floor in words rather than leaving the reader to
  // notice the axis doesn't start at 0%.
  const floor = Math.max(0, Math.floor((lowest - 2) / 5) * 5);
  setSummary(
    "summary-avail",
    `Kättesaadavus jäi ${day(rows[0].date)}–${day(rows[rows.length - 1].date)} vahemikku ` +
      `${lowest.toFixed(1)}–${Math.max(...values).toFixed(1)} %; ` +
      `viimane päev ${values[values.length - 1].toFixed(1)} %. ` +
      (floor > 0 ? `Graafiku Y-telg algab ${floor}%-st, mitte 0%-st.` : ""),
  );
  charts.push(
    new Chart($("chart-avail"), {
      type: "line",
      data: {
        labels: rows.map((r) => day(r.date)),
        datasets: [
          {
            label: "Kättesaadavus",
            data: rows.map((r) => r.avail_pct),
            borderColor: css("--series-1"),
            backgroundColor: css("--series-1"),
            borderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 6,
            tension: 0.2,
          },
        ],
      },
      options: {
        ...baseOptions(),
        scales: {
          x: axisStyle(),
          y: {
            ...axisStyle(),
            suggestedMin: floor,
            max: 100,
            ticks: { ...axisStyle().ticks, callback: (v) => `${v} %` },
          },
        },
        plugins: {
          ...baseOptions().plugins,
          tooltip: {
            ...baseOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) =>
                `${ctx.parsed.y.toFixed(1)} % (${rows[ctx.dataIndex].ok}/${rows[ctx.dataIndex].checks} kontrolli)`,
            },
          },
        },
      },
    }),
  );
}

/* PostgREST queries and KAIA file downloads have genuinely different natural
 * response times, so one pooled median compares two different things. Two
 * lines instead — not one per system (6 today), which would need a whole new
 * validated colour palette for a management audience that mainly needs "the
 * data service" vs "the file service". A day with no checks for a group is a
 * gap in that group's line, not an interpolated value. */
function drawLatency(data) {
  const groups = [
    { key: "daily_postgrest", label: "PostgREST teenused", color: "--series-1" },
    { key: "daily_kaia", label: "KAIA", color: "--series-2" },
  ].map((g) => {
    // daily_postgrest/daily_kaia are independently built in dashboard.py and
    // can have fewer rows than chart_dates (a day with no KAIA checks simply
    // has no KAIA row), so the window is applied per group by its own length
    // rather than by borrowing chart_dates' offset.
    const all = data[g.key] || [];
    const windowed = all.slice(rangeStart(all.length));
    return { ...g, rows: windowed, byDate: new Map(windowed.map((r) => [r.date, r])) };
  });

  const dates = Array.from(new Set(groups.flatMap((g) => g.rows.map((r) => r.date)))).sort();
  const present = groups.filter((g) => g.rows.some((r) => r.p50_ms != null));
  if (dates.length < 2 || present.length === 0) {
    showEmpty("empty-latency", "Vastuseaja trendi näitamiseks on vaja vähemalt kahe päeva andmeid.");
    setSummary("summary-latency", "");
    return;
  }

  setSummary(
    "summary-latency",
    present
      .map((g) => {
        const p50 = g.rows.map((r) => r.p50_ms).filter((v) => v != null);
        return p50.length
          ? `${g.label}: mediaan ${Math.min(...p50)}–${Math.max(...p50)} ms`
          : `${g.label}: andmeid ei ole veel piisavalt`;
      })
      .join("; ") + ".",
  );

  charts.push(
    new Chart($("chart-latency"), {
      type: "line",
      data: {
        labels: dates.map((d) => day(d)),
        datasets: groups.map((g) => ({
          label: g.label,
          data: dates.map((d) => g.byDate.get(d)?.p50_ms ?? null),
          borderColor: css(g.color),
          backgroundColor: css(g.color),
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: 0.2,
          spanGaps: false,
        })),
      },
      options: {
        ...baseOptions(),
        scales: {
          x: axisStyle(),
          y: {
            ...axisStyle(),
            beginAtZero: true,
            ticks: { ...axisStyle().ticks, callback: (v) => `${v} ms` },
          },
        },
        plugins: {
          ...baseOptions().plugins,
          legend: {
            display: true,
            position: "bottom",
            labels: {
              color: css("--ink-2"),
              usePointStyle: true,
              pointStyle: "circle",
              boxWidth: 8,
              font: { family: css("--font"), size: 12 },
            },
          },
          tooltip: {
            ...baseOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => {
                const g = groups[ctx.datasetIndex];
                const row = g.byDate.get(dates[ctx.dataIndex]);
                if (!row || row.p50_ms == null) return `${g.label}: andmed puuduvad`;
                return `${g.label}: ${row.p50_ms} ms (p95 ${row.p95_ms} ms)`;
              },
            },
          },
        },
      },
    }),
  );
}

function drawOutages(data) {
  const rows = data.outages_by_endpoint || [];
  if (!rows.length) {
    showEmpty("empty-outages", "Katkestusi ei ole logitud, seega graafikul pole midagi näidata.");
    setSummary("summary-outages", "");
    return;
  }
  const top = rows[0];
  const total = (r) => (r.total_min_s == null ? duration(r.total_s) : durationRange(r.total_min_s, r.total_max_s));
  setSummary(
    "summary-outages",
    `Kõige rohkem katkestusi: ${top.name} (${top.count}, kokku ${total(top)}). ` +
      `Näidatud on kuni 10 kõige sagedamini katkenud otspunkti.`,
  );
  charts.push(
    new Chart($("chart-outages"), {
      type: "bar",
      data: {
        labels: rows.map((r) => r.name.length > 42 ? `${r.name.slice(0, 40)}…` : r.name),
        datasets: [
          {
            label: "Katkestusi",
            data: rows.map((r) => r.count),
            backgroundColor: css("--series-1"),
            borderRadius: 4,
            borderSkipped: "start",
            barThickness: 14,
          },
        ],
      },
      options: {
        ...baseOptions(),
        indexAxis: "y",
        interaction: { mode: "nearest", intersect: true },
        scales: {
          x: { ...axisStyle(), beginAtZero: true, ticks: { ...axisStyle().ticks, precision: 0 } },
          y: {
            ...axisStyle(),
            grid: { display: false },
            ticks: { ...axisStyle().ticks, autoSkip: false },
          },
        },
        plugins: {
          ...baseOptions().plugins,
          tooltip: {
            ...baseOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => `${ctx.parsed.x} katkestust · kokku ${total(rows[ctx.dataIndex])}`,
            },
          },
        },
      },
    }),
  );
}

/* ---------- the monitor's own health ---------- */

/* Every other number on the page is only as fresh and as fine-grained as the
 * checks behind it, so how often they actually ran comes first, not in small
 * print. Reported as received against expected — the way WMO's WDQMS reports
 * observation availability — plus the age of the newest check measured
 * against the reader's own clock, which the generator cannot know. */
function renderHealth(data) {
  const box = $("monitor-health");
  const nominal = data.interval_minutes || 30;
  const cadence = data.cadence;
  const newest = data.last_check || data.generated_at;
  const ageMin = newest ? (Date.now() - Date.parse(newest)) / 60000 : null;
  const sparse = cadence && cadence.median_gap_minutes > 2 * nominal;
  const stale = ageMin != null && ageMin > 2 * Math.max(nominal, cadence?.median_gap_minutes || 0);

  const lines = [];
  if (sparse) {
    const share = cadence.expected_runs ? Math.round((100 * cadence.runs) / cadence.expected_runs) : null;
    lines.push(
      [
        "strong",
        "Seire töötab kavandatust harvemini.",
        ` Viimase ${cadence.days} päeva jooksul toimus ${cadence.runs} kontrollimiskorda` +
          (cadence.expected_runs ? ` ${cadence.expected_runs} kavandatust (${share} %)` : "") +
          `; kahe korra vahe mediaan oli ${cadence.median_gap_minutes} min, pikim ${cadence.max_gap_minutes} min. ` +
          "Uus katkestus võib lehele jõuda tunde hiljem ning katkestuste algus ja lõpp on teada ainult " +
          "selle täpsusega — seepärast on kestused allpool vahemikena.",
      ],
    );
  } else if (cadence) {
    lines.push([
      "",
      "",
      `Seire töötab plaanipäraselt: viimase ${cadence.days} päeva jooksul ${cadence.runs} ` +
        `kontrollimiskorda ${cadence.expected_runs ?? ""} kavandatust, vahe mediaan ${cadence.median_gap_minutes} min.`,
    ]);
  }
  if (ageMin != null) {
    lines.push([
      stale ? "strong" : "",
      stale ? "Andmed võivad olla vananenud. " : "",
      `Viimane kontroll ${moment(newest)}, ${ageMin < 1 ? "alla minuti" : duration(ageMin * 60)} tagasi.`,
    ]);
  }
  box.replaceChildren(
    ...lines.map(([tag, lead, text]) => {
      const para = document.createElement("p");
      if (tag) para.append(Object.assign(document.createElement(tag), { textContent: lead }));
      para.append(text);
      return para;
    }),
  );
  box.classList.toggle("warn", Boolean(sparse || stale));
  box.hidden = lines.length === 0;
}

/* ---------- boot ---------- */

function render(data) {
  snapshot = data;
  rows = decorate(data);
  const systems = [...new Set(rows.map((r) => r.system))].sort((a, b) => a.localeCompare(b, "et"));
  $("filter-system").replaceChildren(
    Object.assign(document.createElement("option"), { value: "", textContent: "kõik" }),
    ...systems.map((name) =>
      Object.assign(document.createElement("option"), { value: name, textContent: name }),
    ),
  );
  $("updated").textContent = `Leht koostati ${moment(data.generated_at)}.`;
  renderHealth(data);
  const unverified = data.totals?.unverified ?? 0;
  $("provenance").textContent =
    `Näidatud on viimased ${data.window_days} päeva. Ajad on Eesti aja järgi. ` +
    `Jälgitavaid otspunkte ${data.totals?.endpoints ?? 0}` +
    (unverified ? `, neist ${unverified} kinnitamata URL-iga.` : ".");

  renderTiles(data);
  renderSystems(data);
  renderEndpoints(data);
  renderEvents(data);
  renderSystemOutages(data);
  drawAvailability(data);
  drawLatency(data);
  drawOutages(data);
}

/* Applies to the pooled charts and every per-row/per-card history cell at
 * once — see the `rangeDays` declaration for why one control governs all of
 * them. Chart.js instances are destroyed and rebuilt (redrawCharts already
 * does this for a theme change); the SVG cells are cheap enough to just
 * re-render from scratch. */
function setRange(days) {
  rangeDays = days;
  document.querySelectorAll("#range-control button").forEach((btn) => {
    const active = String(btn.dataset.days) === String(days);
    btn.setAttribute("aria-pressed", String(active));
  });
  if (!snapshot) return;
  renderSystems(snapshot);
  renderEndpoints(snapshot);
  redrawCharts();
}

function redrawCharts() {
  while (charts.length) charts.pop().destroy();
  document.querySelectorAll(".empty").forEach((note) => {
    note.hidden = true;
    note.previousElementSibling.hidden = false;
  });
  if (snapshot) {
    drawAvailability(snapshot);
    drawLatency(snapshot);
    drawOutages(snapshot);
  }
}

const refreshEndpoints = () => snapshot && renderEndpoints(snapshot);
const refreshEvents = () => snapshot && renderEvents(snapshot);

$("show-all").addEventListener("change", refreshEndpoints);
$("filter-text").addEventListener("input", refreshEndpoints);
$("filter-system").addEventListener("change", refreshEndpoints);
$("filter-reset").addEventListener("click", () => {
  $("filter-text").value = "";
  $("filter-system").value = "";
  refreshEndpoints();
});
attachSorting("endpoints", "endpoints", refreshEndpoints);
attachSorting("events", "events", refreshEvents);
$("events-verified-only").addEventListener("change", refreshEvents);
attachSorting("system-outages", "systemOutages", () => snapshot && renderSystemOutages(snapshot));

document.querySelectorAll("#range-control button").forEach((btn) => {
  btn.addEventListener("click", () => setRange(btn.dataset.days === "all" ? null : Number(btn.dataset.days)));
});

/* Only the Chart.js canvases need redrawing on a theme change; the strips and
 * sparklines take their colours from CSS custom properties and follow on
 * their own. */
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawCharts);

window.addEventListener("hashchange", openDeepLink);

fetch(`data/status.json?t=${Date.now()}`)
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    render(data);
    openDeepLink();
    // The data's age is against the reader's clock, so it keeps moving while
    // the page is open even though the data does not.
    setInterval(() => renderHealth(data), 60000);
  })
  .catch((error) => {
    $("updated").textContent = `Andmete laadimine ebaõnnestus: ${error.message}`;
  });
