const $ = (sel, root = document) => root.querySelector(sel);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const DAY = 86400000;

/* ── язык: тот же каталог и те же правила подстановки, что в i18n.py ── */
const I18N = DATA ? DATA.i18n : {messages: {}, words: {}, default: "ru"};
let LANG = I18N.default;
try { LANG = localStorage.getItem("aim-lang") || LANG; } catch (e) { /* без хранилища — язык из настроек */ }
const LOCALE = () => (LANG === "ru" ? "ru-RU" : "en-US");

function pluralIndex(n, lang) {
  n = Math.abs(Math.trunc(n));
  if (lang === "ru") {
    if (n % 10 === 1 && n % 100 !== 11) return 0;
    if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return 1;
    return 2;
  }
  return n === 1 ? 0 : 1;
}
function word(key, n) {
  const forms = (I18N.words[key] || {})[LANG] || [key];
  return forms[Math.min(pluralIndex(n, LANG), forms.length - 1)];
}
/* Текст по ключу. Параметры вставляются как есть — экранировать до вызова, если это данные. */
function T(key, params = {}) {
  const entry = I18N.messages[key];
  if (!entry) return key;
  return (entry[LANG] || entry.ru).replace(/\{(\w+)(?::(\w+))?\}/g, (m, name, w) =>
    params[name] === undefined ? m : w ? word(w, params[name]) : String(params[name]));
}

const pad = n => String(n).padStart(2, "0");
const dm = t => { const d = new Date(t); return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}`; };
const dmy = t => { const d = new Date(t); return `${dm(t)}.${String(d.getFullYear()).slice(2)}`; };
const hm = t => { const d = new Date(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const n1 = v => v == null ? "—" : Number(v).toLocaleString(LOCALE(), {maximumFractionDigits: 1, minimumFractionDigits: 1});
const n0 = v => v == null ? "—" : Math.round(v).toLocaleString(LOCALE());
// energy не округляем, а отбрасываем дробь: 699,6 — ещё не Jade, как и в консоли
const e0 = v => v == null ? "—" : String(Math.floor(v));
const pct = (v, digits = 1) => v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
const daysAgo = t => Math.floor((Date.now() - t) / DAY);
const median = xs => { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const trendClass = v => v > 0 ? "trend-up" : v < 0 ? "trend-down" : "";

// цвета рангов Voltaic — свои, у сайта они перепутаны; у остальных бенчмарков — цвета с сайта
const VOLTAIC_VAR = {
  Iron: "--iron", Bronze: "--bronze", Silver: "--silver", Gold: "--gold",
  Platinum: "--platinum", Diamond: "--diamond", Jade: "--jade", Master: "--master",
  Grandmaster: "--grandmaster", Nova: "--nova", Astra: "--astra", Celestial: "--celestial",
};
const LABEL_CLASS = {
  above: "l-good", below: "l-bad", unstable: "l-warn", ceiling: "l-cap", plateau: "l-cap",
  even: "l-flat", noise: "l-na", few: "l-na", no_base: "l-na",
};
const labelChip = code => `<span class="label ${LABEL_CLASS[code] || "l-flat"}">${esc(T("label." + code))}</span>`;
const hintText = hints => hints.map(([code, params]) => T("hint." + code, params)).join("; ");

/* Шкала выбранного бенчмарка: energy у Voltaic, уровень (ранг + доля до следующего) у остальных. */
function makeScale(bench) {
  const names = bench.ranks.map(r => r.name);
  const energyMode = !!bench.levels;
  const marks = energyMode ? bench.levels : names.map((_, i) => i + 1);
  const step = marks.length > 1 ? marks[1] - marks[0] : 1;
  const min = marks[0] - step, max = marks[marks.length - 1] + step;
  const usable = c => /^#[0-9a-f]{6}$/i.test(c) && !/^#(ffffff|000000|333333)$/i.test(c);
  const color = i => {
    if (VOLTAIC_VAR[names[i]]) return css(VOLTAIC_VAR[names[i]]);
    const c = bench.ranks[i].color;
    return usable(c) ? c : `hsl(${30 + i * 290 / Math.max(names.length - 1, 1)} 70% 62%)`;
  };
  const index = v => v == null ? 0 : marks.filter(m => v >= m).length;
  return {
    names, marks, energyMode, min, max, color,
    value: (o, form) => energyMode ? (form ? o.form_energy : o.energy) : (form ? o.form_level : o.level),
    name: v => index(v) ? names[index(v) - 1] : "—",
    colorOf: v => index(v) ? color(index(v) - 1) : css("--faint"),
    colorByName: n => names.includes(n) ? color(names.indexOf(n)) : css("--faint"),
    fmt: v => v == null ? "—" : energyMode ? e0(v) : v.toFixed(2),
    unit: energyMode ? T("bench.energy") : T("bench.level"),
    x: v => Math.max(0, Math.min(100, (v - min) / (max - min) * 100)),
  };
}

const state = {source: null, scenario: null, bench: 0};
try { state.bench = Number(localStorage.getItem("aim-bench")) || 0; } catch (e) { /* без хранилища — первый бенчмарк */ }
const charts = {};

function chart(id) {
  if (!window.echarts) return null;
  if (charts[id]) charts[id].dispose();
  charts[id] = echarts.init(document.getElementById(id), null, {renderer: "canvas"});
  return charts[id];
}

function baseChart() {
  return {
    backgroundColor: "transparent",
    textStyle: {fontFamily: css("--font-mono"), color: css("--muted")},
    grid: {left: 52, right: 18, top: 18, bottom: 36},
    tooltip: {
      backgroundColor: css("--panel-2"), borderColor: css("--line-2"), borderWidth: 1,
      textStyle: {color: css("--text"), fontFamily: css("--font-mono"), fontSize: 12},
    },
  };
}
const axisStyle = () => ({
  axisLine: {lineStyle: {color: css("--line-2")}},
  axisTick: {show: false},
  axisLabel: {color: css("--faint"), fontSize: 11},
  splitLine: {lineStyle: {color: css("--line"), type: [2, 4]}},
});
const zoomSlider = start => ({type: "slider", startValue: start, height: 18, bottom: 8,
  borderColor: css("--line"), fillerColor: css("--signal-dim"), handleStyle: {color: css("--signal")},
  textStyle: {color: css("--faint")}, dataBackground: {lineStyle: {color: css("--line-2")}, areaStyle: {color: css("--panel-2")}}});
const changeLines = () => ({
  symbol: "none", silent: false,
  lineStyle: {color: css("--signal"), type: "dashed", width: 1, opacity: .55},
  label: {show: true, position: "insideEndTop", color: css("--signal"), fontSize: 10, formatter: p => dm(p.value)},
  data: (DATA.changes || []).map(c => ({xAxis: c.t, name: c.text})),
  tooltip: {formatter: p => `${dmy(p.value)}<br>${esc(p.name)}`},
});

/* ── шапка, вкладки, статичные тексты ── */
function applyStatic() {
  document.documentElement.lang = LANG;
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = T(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => { el.placeholder = T(el.dataset.i18nPh); });
  document.querySelectorAll("[data-i18n-aria]").forEach(el => { el.setAttribute("aria-label", T(el.dataset.i18nAria)); });
  $("#lang").textContent = LANG === "ru" ? "EN" : "RU";
  $("#lang").setAttribute("aria-label", T("ui.lang_switch"));
}

function renderTabs() {
  const keys = Object.keys(DATA.sources);
  $("#tabs").innerHTML = keys.map(k =>
    `<button class="tab" role="tab" data-src="${esc(k)}" aria-selected="${k === state.source}">${esc(DATA.sources[k].label)}</button>`).join("");
  $("#tabs").querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => selectSource(b.dataset.src)));
  $("#stamp").textContent = T("ui.built", {date: dmy(DATA.generated), time: hm(DATA.generated), version: DATA.version || ""});
}

/* ── бенчмарк: выбор ── */
function benchesOf(src) { return src.benches || []; }
function currentBench(src) {
  const list = benchesOf(src), b = list[state.bench] || list[0];
  return b && !b.error ? b : null;
}

function renderBenchPick(src) {
  const list = benchesOf(src);
  if (state.bench >= list.length) state.bench = 0;
  $("#bench-pick").innerHTML = list.map((b, i) => `<button class="pick" data-i="${i}" aria-pressed="${i === state.bench}"
      ${b.error ? `disabled title="${esc(b.error)}"` : ""}>${esc(b.name)}</button>`).join("");
  $("#bench-pick").querySelectorAll(".pick").forEach(p => p.addEventListener("click", () => {
    state.bench = Number(p.dataset.i);
    try { localStorage.setItem("aim-bench", String(state.bench)); } catch (e) { /* хранилище недоступно — не страшно */ }
    renderHero(src);
    renderCategories(src);
  }));
}

/* ── герой ── */
function energyCard(bench) {
  const sc = makeScale(bench), o = bench.overall;
  const d = Math.floor(o.form) - Math.floor(o.best);
  return `
    <div class="panel energy" style="--rank:${sc.colorOf(o.form)}">
      <div class="energy-grid">
        <div><div class="cap">${T("ui.energy_form")}</div><div class="big num" style="color:${sc.colorOf(o.form)}">${e0(o.form)}</div><span class="rank-tag" style="color:${sc.colorOf(o.form)}">${esc(sc.name(o.form))}</span></div>
        <div><div class="cap">${T("ui.by_best")}</div><div class="big best num">${e0(o.best)}</div><span class="rank-tag" style="color:${sc.colorOf(o.best)}">${esc(sc.name(o.best))}</span></div>
        <div class="delta"><div class="cap">${T("ui.diff")}</div><b class="num" style="color:${d < 0 ? css("--bad") : css("--good")}">${d > 0 ? "+" : d < 0 ? "−" : ""}${Math.abs(d)}</b></div>
      </div>
      <p class="explain">${T("ui.energy_explain", {name: esc(bench.name), sens: n1(Number(bench.sens))})}
      ${o.missing.length ? `<br><span style="color:${css("--warn")}">${T("ui.no_form", {names: o.missing.map(esc).join(", ")})}</span>` : ""}</p>
    </div>`;
}

function rankCard(bench) {
  const sc = makeScale(bench);
  const site = bench.siteRank ? sc.names[bench.siteRank - 1] : "—";
  const played = bench.categories.filter(c => c.level > 0);
  const holding = played.filter(c => c.form_level != null && sc.name(c.form_level) === sc.name(c.level)).length;
  const col = bench.siteRank ? sc.color(bench.siteRank - 1) : css("--faint");
  return `
    <div class="panel energy" style="--rank:${col}">
      <div class="energy-grid">
        <div><div class="cap">${T("ui.site_rank")}</div><div class="big num" style="color:${col};font-size:clamp(40px,5vw,72px)">${esc(site)}</div></div>
        <div></div>
        <div class="delta"><div class="cap">${T("ui.in_form")}</div><b class="num">${holding}/${played.length}</b>
          <div class="cap" style="margin-top:6px">${T("ui.played_cats")}</div></div>
      </div>
      <p class="explain">${T("ui.rank_explain", {name: esc(bench.name), sens: n1(Number(bench.sens))})}</p>
    </div>`;
}

function summaryCard(src) {
  const failed = benchesOf(src).find(b => b.error);
  const why = src.benches === undefined ? T("ui.no_bench_aimbeast")
    : failed ? T("ui.bench_failed", {error: esc(failed.error)}) : T("ui.no_benches");
  const total = src.scenarios.reduce((a, s) => a + s.n, 0);
  return `
    <div class="panel energy">
      <div class="cap">${T("ui.total", {label: esc(src.label)})}</div>
      <div class="big num">${n0(total)}</div>
      <span class="rank-tag" style="color:${css("--muted")}">${T("ui.total_sub", {total, n: src.scenarios.length})}</span>
      <p class="explain">${why}.${src.note ? " " + T("ui." + src.note) : ""}</p>
    </div>`;
}

function setupTiles(src) {
  const ses = src.session;
  if (src.config) {
    const c = src.config;
    return [`${esc(c.SensivityXMainValue || "?")} ${esc((c.SensitivityScale || "").toLowerCase())}`,
            `${esc(c.DPI || "?")} DPI · FOV ${esc(c.FOV || "?")} · ${T("ui.from_cfg")}`];
  }
  return [`${n1(Number(ses.setup.sens))} cm/360`,
          `${esc(ses.setup.dpi)} DPI · FOV ${esc(ses.setup.fov)} · ${esc(ses.setup.res)}`];
}

function renderHero(src) {
  const last = (DATA.changes || []).filter(c => c.t <= Date.now()).slice(-1)[0];
  const bench = currentBench(src);
  const week = src.days.filter(d => Date.parse(d.d) >= Date.now() - 7 * DAY);
  const weekRuns = week.reduce((a, d) => a + d.runs, 0);
  const test = DATA.testDate ? Math.ceil((Date.parse(DATA.testDate) - Date.now()) / DAY) : null;
  const [setup, setupSub] = setupTiles(src);
  const lead = !bench ? summaryCard(src) : bench.overall ? energyCard(bench) : rankCard(bench);

  $("#hero").innerHTML = lead + `
    <div class="stack">
      <div class="panel tile"><div class="cap">${T("ui.to_test")}</div>
        <div class="val">${test == null ? "—" : `<span class="count num">${test}</span> ${word("day", test)}`}</div>
        <div class="sub">${DATA.testDate ? T("ui.test_on", {date: dmy(Date.parse(DATA.testDate))}) : T("ui.no_test")}</div></div>
      <div class="panel tile"><div class="cap">${T("ui.last7")}</div>
        <div class="val num">${T("ui.minutes", {n: n0(week.reduce((a, d) => a + d.minutes, 0))})}</div>
        <div class="sub">${T("ui.week_sub", {runs: weekRuns, days: week.length})}</div></div>
    </div>
    <div class="stack">
      <div class="panel tile"><div class="cap">${T("ui.sens")}</div><div class="val num">${setup}</div><div class="sub">${setupSub}</div></div>
      <div class="panel tile"><div class="cap">${T("ui.last_change")}</div>
        <div class="val">${last ? dm(last.t) : "—"}${last ? ` <span class="sub">${T("ui.days_ago", {n: daysAgo(last.t)})}</span>` : ""}</div>
        <div class="sub">${last ? esc(last.text) : T("ui.no_changes")}</div></div>
    </div>`;
}

/* ── категории бенчмарка ── */
function scenarioTable(c, sc) {
  const rows = c.scenarios.map(s => {
    const next = s.maxes.find(m => m > s.best);
    const v = sc.value(s, false), f = sc.value(s, true);
    return `<tr><td>${esc(s.short)}</td>
      <td class="num">${n1(s.best)}</td><td class="num" style="color:${sc.colorOf(v)}">${sc.fmt(v)}</td>
      <td class="num">${n1(s.form)}</td><td class="num" style="color:${f == null ? "inherit" : sc.colorOf(f)}">${sc.fmt(f)}</td>
      <td class="num">${next ? "+" + n0(next - s.best) : T("bench.max_plus")}</td>
      <td class="num ${trendClass(s.trend)}">${pct(s.trend)}</td>
      <td>${s.last_played ? dm(s.last_played) : "—"}</td></tr>`;
  }).join("");
  const heads = [T("col.scenario"), T("col.best"), sc.unit, T("col.form"), T("ui.by_form"),
                 T("col.to_next"), T("col.trend"), T("col.last")];
  return `<div class="inner"><table class="mini"><tr>${heads.map(h => `<th>${h}</th>`).join("")}</tr>${rows}</table></div>`;
}

function gaugeRow(c, idx, sc, bands) {
  const v = sc.value(c, false), f = sc.value(c, true);
  const stale = c.days_idle == null || c.days_idle >= 10;
  const idle = c.days_idle == null ? T("ui.never") : c.days_idle === 0 ? T("ui.today") : T("ui.days_short", {n: c.days_idle});
  return `<details class="gauge">
    <summary>
      <span class="name">${esc(c.name)}</span>
      <span class="track" aria-hidden="true">${bands}
        <span class="fill" style="width:${sc.x(v)}%;background:${sc.colorOf(v)};animation-delay:${idx * 45}ms"></span>
        ${f == null ? "" : `<span class="tick" style="left:${sc.x(f)}%" title="${T("col.form")}"></span>`}
      </span>
      <span class="pb num">${T("ui.pb_short")} <b style="color:${sc.colorOf(v)}">${sc.fmt(v)}</b> ${esc(sc.name(v))}</span>
      <span class="fm num">${f == null ? `<span class="none">${T("col.form")} —</span>` : `${T("col.form")} <b style="color:${sc.colorOf(f)}">${sc.fmt(f)}</b> ${esc(sc.name(f))}`}</span>
      <span class="idle ${stale ? "stale" : ""}">${idle}</span>
    </summary>${scenarioTable(c, sc)}</details>`;
}

function renderAdvice(bench, sc) {
  const notes = bench.notes.length
    ? bench.notes.map(([name, code, params]) => `<div class="note"><b>${esc(name)}</b><span>${esc(T("note." + code, params))}</span></div>`).join("")
    : `<div class="note"><span></span><span>${T("bench.all_in_form")}</span></div>`;
  const near = bench.nearest.length ? bench.nearest.map(o => `
      <div class="near"><span>${esc(o.scenario.replace(/ (Novice|Intermediate|Advanced) S\d+$/, ""))}</span>
        <span class="need num" style="color:${sc.colorByName(o.rank)}">+${n0(o.need)}</span>
        <span class="what">${esc(o.category)} → ${esc(o.rank)} · ${(o.share * 100).toFixed(1)}%</span></div>`).join("")
    : `<div class="near"><span class="what">${T("ui.nearest_none")}</span></div>`;
  $("#advice").innerHTML = `<div><h3>${T("ui.before_test")}</h3>${notes}</div><div><h3>${T("ui.nearest")}</h3>${near}</div>`;
}

function renderCategories(src) {
  const list = benchesOf(src), bench = currentBench(src);
  $("#cats-section").classList.toggle("hidden", !list.length);
  if (!list.length) return;
  renderBenchPick(src);
  if (!bench) {
    $("#gauges").innerHTML = `<div class="empty">${T("ui.bench_failed", {error: esc((list[state.bench] || {}).error || "")})}</div>`;
    $("#advice").innerHTML = "";
    return;
  }
  const sc = makeScale(bench);
  $("#cats-aside").textContent = T("ui.cats_aside", {id: bench.id});
  const bands = sc.names.map((n, i) => {
    const from = sc.marks[i], to = sc.marks[i + 1] ?? sc.max;
    return `<span class="band" style="left:${sc.x(from)}%;width:${sc.x(to) - sc.x(from)}%;background:${sc.color(i)}"></span>` +
           `<span class="threshold" style="left:${sc.x(from)}%"></span>`;
  }).join("");
  $("#gauges").innerHTML = bench.categories.map((c, i) => gaugeRow(c, i, sc, bands)).join("") +
    `<div class="gauge-legend">${sc.names.map((n, i) => `<span><i style="background:${sc.color(i)}"></i>${esc(n)}${sc.energyMode ? " " + sc.marks[i] + "+" : ""}</span>`).join("")}
     <span><i style="background:${css("--text")};width:3px;height:10px"></i>${T("col.form")}</span></div>`;
  renderAdvice(bench, sc);
}

/* ── объём по дням ── */
function renderVolume(src) {
  const c = chart("volume");
  if (!c) return;
  const data = src.days.map(d => [Date.parse(d.d + "T12:00:00"), d.runs, d.minutes]);
  const start = Math.max(data[0][0], Date.now() - 60 * DAY);
  c.setOption({
    ...baseChart(),
    grid: {left: 44, right: 18, top: 24, bottom: 56},
    tooltip: {...baseChart().tooltip, trigger: "axis", formatter: ps => {
      const p = ps.find(x => x.seriesType === "bar"); if (!p) return "";
      return `${dmy(p.value[0])}<br>${T("ui.vol_tip", {n: p.value[1], m: n0(p.value[2])})}`; }},
    xAxis: {type: "time", ...axisStyle(), splitLine: {show: false}, axisLabel: {color: css("--faint"), fontSize: 11, hideOverlap: true, formatter: t => dm(t)}},
    yAxis: {type: "value", ...axisStyle(), minInterval: 1},
    dataZoom: [{type: "inside", startValue: start}, zoomSlider(start)],
    series: [{type: "bar", data, barMaxWidth: 14, itemStyle: {color: css("--line-2"), borderRadius: [2, 2, 0, 0]},
      emphasis: {itemStyle: {color: css("--signal")}}, markLine: changeLines()}],
  });
}

/* ── обозреватель ── */
function renderList(src) {
  const q = $("#search").value.trim().toLowerCase();
  const recentOnly = $("#recent").checked;
  const labels = Object.fromEntries(src.session.rows.map(r => [r.scenario, r.label]));
  const items = src.scenarios.filter(s =>
    (!q || s.name.toLowerCase().includes(q)) && (!recentOnly || q || Date.now() - s.last < 30 * DAY));
  $("#list").innerHTML = items.length ? items.map(s => {
    const tr = s.trend == null ? "" : `<span class="${trendClass(s.trend)}">${pct(s.trend)}${T("ui.per_week")}</span>`;
    return `<button class="scn" role="listitem" data-name="${esc(s.name)}" aria-current="${s.name === state.scenario}">
      <span class="nm" title="${esc(s.name)}">${esc(s.name)}${s.tag ? `<span class="tag">${esc(s.tag)}</span>` : ""}</span>${labels[s.name] ? labelChip(labels[s.name]) : `<span></span>`}
      <span class="meta">${T("common.runs", {n: s.n})} · ${dm(s.last)}${s.plateau ? " · " + T("label.plateau") : ""} ${tr}</span></button>`;
  }).join("") : `<div class="empty">${T("ui.nothing_found")}</div>`;
  $("#list").querySelectorAll(".scn").forEach(b => b.addEventListener("click", () => selectScenario(b.dataset.name)));
}

function rolling(values, size) {
  return values.map((_, i) => median(values.slice(Math.max(0, i - size + 1), i + 1)));
}

function scenarioChips(s, cur, other) {
  const last5 = cur.slice(-5).map(p => p[1]);
  return [
    `<span class="chip">${T("common.runs", {n: s.n})}${other.length ? T("ui.chip_other", {n: other.length}) : ""}</span>`,
    `<span class="chip">${T("col.best")} <b>${n1(s.best)}</b></span>`,
    `<span class="chip">${T("col.form")} <b>${n1(median(last5))}</b></span>`,
    `<span class="chip">${T("col.trend")} <b class="${trendClass(s.trend)}">${s.trend == null ? "—" : pct(s.trend) + T("ui.per_week")}</b></span>`,
    `<span class="chip">${T("ui.chip_since", {n: `<b>${s.sinceBest}</b>`})}${s.plateau ? ` · <b style="color:${css("--cap")}">${T("label.plateau")}</b>` : ""}</span>`,
    `<span class="chip">${s.sens === "?" ? T("ui.sens_none") : T("ui.sens_value", {sens: n1(Number(s.sens))})}</span>`,
  ].join("");
}

function renderScenario(src) {
  const s = src.scenarios.find(x => x.name === state.scenario);
  if (!s) return;
  const curIdx = src.sensList.indexOf(s.sens);
  const cur = [], other = [];
  s.t.forEach((t, i) => (s.k[i] === curIdx ? cur : other).push([t, s.s[i], s.a[i], src.sensList[s.k[i]]]));
  const med = rolling(cur.map(p => p[1]), 7).map((v, i) => [cur[i][0], v]);
  let best = -Infinity;
  const pb = cur.map(p => [p[0], best = Math.max(best, p[1])]);

  $("#scn-title").textContent = s.name;
  $("#scn-chips").innerHTML = scenarioChips(s, cur, other);

  const c = chart("scn-chart");
  if (!c) return;
  // по умолчанию — от первого прогона на текущей сенсе (не дальше 45 дней), иначе старая
  // история на другой сенсе сжимает текущую в правый край
  const all = s.t, lastT = all[all.length - 1];
  const edge = Math.max((lastT - all[0]) * 0.01, 20 * 60000);   // запас по краям: крайние точки не срезаются рамкой
  let start = Math.max(all[0], cur.length ? cur[0][0] - 2 * DAY : -Infinity);
  // окно в 45 дней — только если в нём достаточно прогонов, иначе видна кучка точек у края
  if (all.filter(t => t >= lastT - 45 * DAY).length >= 15) start = Math.max(start, lastT - 45 * DAY);
  const tip = p => `${dmy(p.value[0])} ${hm(p.value[0])}<br><b>${n1(p.value[1])}</b>` +
    (p.value[2] != null ? ` · ${T("col.acc")} ${n1(p.value[2])}%` : "") + (p.value[3] && p.value[3] !== "?" ? `<br>${T("ui.sens")} ${esc(p.value[3])}` : "");
  c.setOption({
    ...baseChart(),
    grid: {left: 64, right: 18, top: 30, bottom: 60},
    legend: {top: 0, right: 8, textStyle: {color: css("--muted"), fontSize: 11}, itemWidth: 14, itemHeight: 8},
    tooltip: {...baseChart().tooltip, trigger: "item", formatter: p => p.seriesId === "median" || p.seriesId === "pb"
      ? `${p.seriesName}: <b>${n1(p.value[1])}</b><br>${dmy(p.value[0])}` : tip(p)},
    // внутри суток — часы, на полуночи — дата: после увеличения видно, где кончается день
    xAxis: {type: "time", ...axisStyle(), splitLine: {show: false},
      axisLabel: {color: css("--faint"), fontSize: 11, hideOverlap: true,
        formatter: t => { const d = new Date(t); return d.getHours() || d.getMinutes() ? hm(t) : dm(t); }},
      min: v => v.min - edge, max: v => v.max + edge},
    yAxis: {type: "value", scale: true, ...axisStyle()},
    // filterMode none: линии не рвутся на краю окна, ось Y подгоняет fitY
    dataZoom: [{type: "inside", startValue: start, filterMode: "none"}, {...zoomSlider(start), filterMode: "none"}],
    series: [
      {id: "other", name: T("ui.s_other"), type: "scatter", data: other, symbolSize: 6, z: 4,
        itemStyle: {color: css("--faint"), opacity: .7, borderColor: css("--panel"), borderWidth: 1}},
      {id: "run", name: T("ui.s_run"), type: "scatter", data: cur, symbolSize: 8, z: 6,
        itemStyle: {color: css("--text"), borderColor: css("--panel"), borderWidth: 1.5},
        emphasis: {scale: 1.6, itemStyle: {color: css("--signal")}},
        markArea: {silent: true, itemStyle: {color: css("--signal-dim")},
          data: [[{xAxis: src.session.start}, {xAxis: src.session.end}]]}},
      {id: "median", name: T("ui.s_median"), type: "line", data: med, showSymbol: false, z: 3,
        lineStyle: {color: css("--signal"), width: 2, opacity: .85}, markLine: changeLines()},
      {id: "pb", name: T("col.best"), type: "line", step: "end", data: pb, showSymbol: false,
        z: 2, lineStyle: {color: css("--cap"), width: 1.2, type: [4, 3]}},
    ],
  });
  fitY(c, [...cur, ...other]);
}

/* Ось Y — по прогонам в видимом окне, а не по всей истории и линии рекорда:
   иначе после увеличения точки сжимаются в полоску и сливаются с медианой. */
function fitY(c, points) {
  const apply = () => {
    const zoom = c.getOption().dataZoom[0];
    const visible = points.filter(p => p[0] >= zoom.startValue && p[0] <= zoom.endValue).map(p => p[1]);
    if (!visible.length) return;
    const lo = Math.min(...visible), hi = Math.max(...visible);
    const pad = Math.max((hi - lo) * 0.12, Math.abs(hi) * 0.01, 1);
    c.setOption({yAxis: {min: Math.floor(lo - pad), max: Math.ceil(hi + pad)}}, false, true);
  };
  c.on("datazoom", apply);
  apply();
}

function selectScenario(name, scroll = false) {
  state.scenario = name;
  const src = DATA.sources[state.source];
  renderList(src);
  renderScenario(src);
  if (scroll) $("#exp-h").scrollIntoView({behavior: "smooth", block: "start"});
}

/* ── сессия ── */
function sessionRow(r) {
  const plateau = r.plateau && r.label !== "plateau" ? " " + labelChip("plateau") : "";
  return `<tr>
    <td><button class="row-link" data-name="${esc(r.scenario)}" title="${esc(r.scenario)}">${esc(r.scenario)}</button></td>
    <td class="num">${r.n}</td><td class="num">${n1(r.avg)}</td>
    <td class="num">${n1(r.norm)}${r.norm != null && r.crosses ? `<span class="cross" title="${T("ui.cross_title")}">*</span>` : ""}</td>
    <td class="num">${n1(r.best)}</td>
    <td class="num">${r.best ? `${r.deficit > 0 ? "+" : ""}${r.deficit.toFixed(1)}%` : "—"}</td>
    <td class="num">${r.cv.toFixed(1)}%</td>
    <td class="num ${trendClass(r.trend)}">${pct(r.trend)}</td>
    <td class="num">${r.since_best}</td>
    <td>${labelChip(r.label)}${plateau}</td></tr>`;
}

function renderSession(src) {
  const ses = src.session, mins = Math.round((ses.end - ses.start) / 60000);
  $("#ses-aside").textContent = T("ui.ses_aside", {date: dm(ses.start), start: hm(ses.start), end: hm(ses.end), n: ses.n, m: mins});
  const heads = ["scenario", "runs", "avg", "norm", "max", "deficit", "spread", "trend", "since_best", "verdict"];
  $("#diag").innerHTML = `<thead><tr>${heads.map(h => `<th>${T("col." + h)}</th>`).join("")}</tr></thead>` +
    `<tbody>${ses.rows.map(sessionRow).join("")}</tbody>`;
  $("#diag").querySelectorAll(".row-link").forEach(b => b.addEventListener("click", () => {
    $("#search").value = ""; selectScenario(b.dataset.name, true); }));
  const hinted = ses.rows.filter(r => r.hints.length && r.label !== "no_base");
  $("#hints").innerHTML = hinted.length
    ? hinted.map(r => `<li><b>${esc(r.scenario)}</b> — ${esc(hintText(r.hints))}</li>`).join("")
    : `<li>${T("ui.no_hints")}</li>`;
  $("#todo").innerHTML = ses.todo.length
    ? ses.todo.map(t => `<li><span>${esc(t.scenario)} ${labelChip(t.label)}</span><span class="act">${esc(T("todo." + t.label))}</span></li>`).join("")
    : `<li><span>—</span><span class="act">${T("todo.none")}</span></li>`;
  renderShape(src);
}

function shapeNote(src) {
  const note = [];
  if (src.session.shape.warmup) note.push(T("ui.shape_warmup", {n: src.session.shape.warmup}));
  if (src.session.shape.fatigue) note.push(T("ui.shape_fatigue", {n: src.session.shape.fatigue + 1}));
  const aw = src.shape14.warmup, af = src.shape14.fatigue;
  note.push(src.shape14.points.length
    ? T("ui.shape14", {w: aw ? T("ui.shape14_warmup", {n: aw}) : T("ui.shape14_no_warmup"),
                       f: af ? T("ui.shape14_fatigue", {n: af + 1}) : T("ui.shape14_no_fatigue")})
    : T("ui.shape_few"));
  return note.join(" · ");
}

function renderShape(src) {
  const pts = src.session.shape.points, avg = src.shape14.points;
  $("#shape-note").textContent = shapeNote(src);
  const c = chart("shape");
  if (!c) return;
  const good = css("--good"), bad = css("--bad");
  c.setOption({
    ...baseChart(),
    grid: {left: 40, right: 14, top: 26, bottom: 30},
    legend: {top: 0, right: 8, textStyle: {color: css("--muted"), fontSize: 11}, itemWidth: 14, itemHeight: 8},
    tooltip: {...baseChart().tooltip, trigger: "item", formatter: p => p.seriesId === "session"
      ? `#${p.dataIndex + 1} ${esc(pts[p.dataIndex].scenario)}<br><b>${n1(pts[p.dataIndex].score)}</b> · ${T("shape.level")} ${p.value.toFixed(1)}`
      : `${T("ui.tip_avg14")}<br>#${p.dataIndex + 1}: ${p.value.toFixed(2)} · ${avg[p.dataIndex].sessions} ${word("session", avg[p.dataIndex].sessions)}`},
    xAxis: {type: "category", data: pts.map(p => p.index), ...axisStyle(), splitLine: {show: false}},
    yAxis: {type: "value", ...axisStyle(), min: v => Math.min(-2, Math.floor(v.min)), max: v => Math.max(2, Math.ceil(v.max))},
    series: [
      {id: "session", name: T("ui.s_session"), type: "bar", barMaxWidth: 16,
        data: pts.map(p => ({value: +p.level.toFixed(2), itemStyle: {color: p.level >= 0 ? good : bad, opacity: .85, borderRadius: 2}}))},
      {id: "avg14", name: T("ui.s_14days"), type: "line", data: avg.slice(0, pts.length).map(p => +p.level.toFixed(2)), showSymbol: false,
        lineStyle: {color: css("--signal"), width: 2}, z: 5},
    ],
  });
}

/* ── изменения ── */
function shiftBar(v, cls) {
  if (v == null) return "";
  const w = Math.min(Math.abs(v) / 0.2, 1) * 50;   // шкала ±20%
  const col = v >= 0 ? css("--good") : css("--bad");
  return `<span class="bar ${cls}" style="${v >= 0 ? "left:50%" : `left:${50 - w}%`};width:${Math.max(w, .6)}%;background:${col};border-color:${col}"></span>`;
}

function changeCard(c) {
  const sh = [...c.shifts].sort((a, b) => a.start - b.start);
  const ends = sh.filter(s => s.end != null).map(s => s.end);
  const sum = sh.length
    ? T("ui.changes_sum", {n: sh.length, start: `<b>${pct(median(sh.map(s => s.start)))}</b>`,
                           end: `<b>${ends.length ? pct(median(ends)) : "—"}</b>`, over: ends.length ? T("ui.over_n", {n: ends.length}) : ""})
    : T("changes.none", {n: 3});
  return `<div class="panel change">
    <div><div class="when">${dmy(c.t)}</div><div class="ago">${T("ui.days_ago", {n: daysAgo(c.t)})}</div></div>
    <div><div class="what">${esc(c.text)}</div><div class="sum">${sum}</div>
      ${sh.slice(0, 14).map(s => `<div class="shift"><span class="nm" title="${esc(s.scenario)}">${esc(s.scenario)}</span>
        <span class="axis">${shiftBar(s.start, "start")}${shiftBar(s.end, "end")}</span>
        <span class="num" style="color:${s.start >= 0 ? css("--good") : css("--bad")}">${pct(s.start)}</span>
        <span class="num" style="color:${css("--muted")}">${pct(s.end)}</span></div>`).join("")}
    </div></div>`;
}

function renderChanges(src) {
  const list = [...src.changes].reverse();
  $("#changes").innerHTML = list.length ? list.map(changeCard).join("")
    : `<div class="panel empty">${T("ui.changes_empty")} <b>2026-10-05  ${T("ui.changes_example")}</b></div>`;
}

/* ── сборка ── */
function selectSource(key) {
  state.source = key;
  history.replaceState(null, "", "#" + key);
  const src = DATA.sources[key];
  applyStatic();
  renderTabs();
  renderHero(src);
  renderCategories(src);
  renderVolume(src);
  renderSession(src);
  renderChanges(src);
  const first = src.session.rows.find(r => r.norm != null) || src.session.rows[0];
  selectScenario(state.scenario && src.scenarios.some(s => s.name === state.scenario)
    ? state.scenario : first ? first.scenario : src.scenarios[0].name);
}

function switchLang() {
  LANG = LANG === "ru" ? "en" : "ru";
  try { localStorage.setItem("aim-lang", LANG); } catch (e) { /* не запомнится — не страшно */ }
  selectSource(state.source);
}

function init() {
  if (!DATA) { document.body.innerHTML = "<p style='padding:40px'>No data: build the dashboard with aim-telemetry --dashboard.</p>"; return; }
  if (!I18N.messages["ui.built"]) LANG = "ru";
  if (!window.echarts) document.querySelector(".wrap").insertAdjacentHTML("afterbegin",
    `<div class="warn-line">${T("ui.no_echarts")}</div>`);
  $("#search").addEventListener("input", () => renderList(DATA.sources[state.source]));
  $("#recent").addEventListener("change", () => renderList(DATA.sources[state.source]));
  $("#lang").addEventListener("click", switchLang);
  let pending;
  window.addEventListener("resize", () => { clearTimeout(pending); pending = setTimeout(() => Object.values(charts).forEach(c => c.resize()), 120); });
  const fromHash = location.hash.slice(1);
  selectSource(DATA.sources[fromHash] ? fromHash : Object.keys(DATA.sources)[0]);
}
init();
