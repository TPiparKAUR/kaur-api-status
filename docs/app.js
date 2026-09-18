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
  unknown: "Teadmata",
  unchecked: "Kontrollimata",
};

/* Sorting the status column by name would put "Häire" before "Maas" and bury
 * the thing an operator opened the page for. Ascending is worst-first. */
const SEVERITY = { down: 0, degraded: 1, unknown: 2, unchecked: 3, ok: 4 };

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
  incidents: { key: null, dir: 1 },
};

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

function chip(status) {
  const span = document.createElement("span");
  span.className = `chip ${status}`;
  span.textContent = STATUS_WORD[status] || status;
  return span;
}

const sum = (values) => values.reduce((total, value) => total + (value || 0), 0);
const share = (ok, checks) => (checks ? (100 * ok) / checks : null);

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
 * this log that difference is real. Named, not colour-coded. */
function worstSystemTile(data) {
  const measured = (data.systems || []).filter((s) => s.avail_24h != null);
  if (!measured.length) {
    return { label: "Nõrgim teenus 24 h", value: "–", sub: "Viimase ööpäeva kohta ei ole mõõtmisi." };
  }
  const worst = measured.reduce((a, b) => (b.avail_24h < a.avail_24h ? b : a));
  return {
    label: "Nõrgim teenus 24 h",
    value: pct(worst.avail_24h),
    sub: `${worst.name} · ${worst.problem} / ${worst.endpoints} üksust probleemiga`,
  };
}

function renderTiles(data) {
  const t = data.totals || {};
  const problem = (t.down || 0) + (t.degraded || 0);
  const tiles = [
    {
      label: "Teenused korras",
      value: `${t.ok || 0} / ${t.endpoints || 0}`,
      sub: problem ? `${problem} otspunkti vajab tähelepanu` : "Kõik jälgitavad otspunktid vastavad",
    },
    {
      label: "Kättesaadavus 24 h",
      value: pct(data.availability?.h24),
      sub: `${data.availability?.checks_24h || 0} kontrolli`,
    },
    { label: "Kättesaadavus 7 päeva", value: pct(data.availability?.d7), sub: "Õnnestunud kontrollide osakaal" },
    worstSystemTile(data),
    {
      label: "Katkestusi logis",
      value: String(data.incident_count ?? 0),
      // The count alone does not say whether this was a bad month: 194 blips
      // of a minute and 194 outages of an hour are the same number. The hours
      // are what a budget conversation runs on — but they are summed across
      // endpoints, so two endpoints down for an hour is two hours here and
      // not one. Saying so in four words beats a tile that reads as "the
      // platform was down for ten days".
      sub:
        data.outage_total_s
          ? `Otspunkte maas kokku ${duration(data.outage_total_s)} (liidetud)`
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
        `kättesaadavus 24 h ${pct(system.avail_24h)}`;

      card.append(title, text, meta);

      // Pooled the same way dashboard.py pools a system's availability: sum
      // the members' raw ok and checks per day, never average their
      // percentages, or a member with three checks would weigh as much as one
      // with three hundred.
      const dates = data.chart_dates || [];
      const members = rows.filter((r) => r.system === system.name);
      if (dates.length && members.length) {
        const checks = dates.map((_, i) => sum(members.map((m) => m._checks[i])));
        const ok = dates.map((_, i) => sum(members.map((m) => m._ok[i])));
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

  const dates = data.chart_dates || [];
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

      const name = document.createElement("td");
      name.textContent = item.name;
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
      status.append(chip(item.status));

      const response = document.createElement("td");
      response.className = "num";
      response.textContent = item.http ? `${item.http} · ${millis(item.ms)}` : millis(item.ms);

      const d1 = document.createElement("td");
      d1.className = "num";
      d1.textContent = pct(item.avail_24h);

      const d7 = document.createElement("td");
      d7.className = "num";
      d7.textContent = pct(item.avail_7d);

      const history = document.createElement("td");
      history.className = "viz";
      history.append(uptimeStrip(dates, item._checks, item._ok));

      const latency = document.createElement("td");
      latency.className = "viz";
      const spark = latencySparkline(dates, item._p50);
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

function legendKey(kind, text) {
  const key = document.createElement("span");
  key.className = "legend-key";
  const swatch = document.createElement("span");
  swatch.className = `swatch ${kind}`;
  swatch.setAttribute("aria-hidden", "true");
  key.append(swatch, document.createTextNode(text));
  return key;
}

function renderIncidents(data) {
  const all = data.incidents || [];
  const body = document.querySelector("#incidents tbody");
  const empty = $("empty-incidents");

  empty.hidden = all.length > 0;
  if (!all.length) {
    empty.textContent = "Logitud perioodil katkestusi ei ole.";
    body.replaceChildren();
    return;
  }

  body.replaceChildren(
    ...applySort(all, "incidents", "incidents").map((item) => {
      const row = document.createElement("tr");
      const cells = [
        moment(item.start),
        item.end ? moment(item.end) : "kestab",
        duration(item.duration_s),
        item.name,
      ];
      cells.forEach((text, index) => {
        const cell = document.createElement("td");
        if (index !== 3) cell.className = "num";
        cell.textContent = text;
        row.append(cell);
      });
      const reason = document.createElement("td");
      reason.className = "reason";
      reason.textContent = item.detail || STATUS_WORD[item.worst] || "";
      row.append(reason);
      return row;
    }),
  );
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
  const rows = data.daily || [];
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
  ].map((g) => ({ ...g, rows: data[g.key] || [], byDate: new Map((data[g.key] || []).map((r) => [r.date, r])) }));

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
  setSummary(
    "summary-outages",
    `Kõige rohkem katkestusi: ${top.name} (${top.count}, kokku ${duration(top.total_s)}). ` +
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
              label: (ctx) =>
                `${ctx.parsed.x} katkestust · kokku ${duration(rows[ctx.dataIndex].total_s)}`,
            },
          },
        },
      },
    }),
  );
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
  $("updated").textContent =
    `Viimati uuendatud ${moment(data.generated_at)} · kontroll iga ${data.interval_minutes} minuti järel`;
  const unverified = data.totals?.unverified ?? 0;
  $("provenance").textContent =
    `Näidatud on viimased ${data.window_days} päeva. Ajad on Eesti aja järgi. ` +
    `Jälgitavaid otspunkte ${data.totals?.endpoints ?? 0}` +
    (unverified ? `, neist ${unverified} kinnitamata URL-iga.` : ".");

  renderTiles(data);
  renderSystems(data);
  renderEndpoints(data);
  renderIncidents(data);
  drawAvailability(data);
  drawLatency(data);
  drawOutages(data);
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
const refreshIncidents = () => snapshot && renderIncidents(snapshot);

$("show-all").addEventListener("change", refreshEndpoints);
$("filter-text").addEventListener("input", refreshEndpoints);
$("filter-system").addEventListener("change", refreshEndpoints);
$("filter-reset").addEventListener("click", () => {
  $("filter-text").value = "";
  $("filter-system").value = "";
  refreshEndpoints();
});
attachSorting("endpoints", "endpoints", refreshEndpoints);
attachSorting("incidents", "incidents", refreshIncidents);

/* Only the Chart.js canvases need redrawing on a theme change; the strips and
 * sparklines take their colours from CSS custom properties and follow on
 * their own. */
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawCharts);

fetch(`data/status.json?t=${Date.now()}`)
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    $("updated").textContent = `Andmete laadimine ebaõnnestus: ${error.message}`;
  });
