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

const TZ = "Europe/Tallinn";
const charts = [];
let snapshot = null;

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

/* ---------- summary tiles ---------- */

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
    {
      label: "Katkestusi logis",
      value: String(data.incident_count ?? 0),
      sub: `Jälgimine algas ${data.first_record ? moment(data.first_record) : "–"}`,
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
      return card;
    }),
  );
}

/* ---------- tables ---------- */

function renderEndpoints(data) {
  const showAll = $("show-all").checked;
  const all = data.endpoints || [];
  const shown = showAll ? all : all.filter((e) => e.status !== "ok");

  $("table-note").textContent = showAll
    ? `Kõik ${all.length} otspunkti.`
    : shown.length
      ? `Näidatakse ${shown.length} otspunkti, mis ei ole korras.`
      : `Kõik ${all.length} otspunkti on korras — probleeme ei ole.`;

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

      const last = document.createElement("td");
      last.className = "num";
      last.textContent = moment(item.ts);

      row.append(name, system, status, response, d1, d7, last);
      return row;
    }),
  );
}

function renderIncidents(data) {
  const rows = data.incidents || [];
  const body = document.querySelector("#incidents tbody");
  const empty = $("empty-incidents");

  empty.hidden = rows.length > 0;
  if (!rows.length) {
    empty.textContent = "Logitud perioodil katkestusi ei ole.";
    body.replaceChildren();
    return;
  }

  body.replaceChildren(
    ...rows.map((item) => {
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

$("show-all").addEventListener("change", () => snapshot && renderEndpoints(snapshot));
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
