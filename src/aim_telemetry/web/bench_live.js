/* Бенчмарк, загруженный по клику: тот же разбор, что bench.py + bench_payload, только в браузере.
   Правило одно на два языка — правки делать в обоих местах; test_bench_live.py сверяет их до цифры.
   Без DOM: файл гоняется и в node. */
const BENCH = (() => {
  const VOLTAIC_BASE = {Iron: 100, Platinum: 500, Grandmaster: 900};
  const ENERGY_STEP = 100;
  const RECENT_RUNS = 5;     // форма — медиана стольких последних прогонов на текущей сенсе
  const NEAREST_TOP = 6;
  const SENS_TOLERANCE = 0.01;
  const DAY_MS = 86400000;
  const TIER_SUFFIX = / (Novice|Intermediate|Advanced) S\d+$/;

  const med = xs => { const s = [...xs].sort((a, b) => a - b), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const maxOr = (xs, none = null) => xs.length ? Math.max(...xs) : none;
  const energyLevels = names => { const base = VOLTAIC_BASE[names[0]]; return base ? names.map((_, i) => base + ENERGY_STEP * i) : null; };
  const harmonic = vs => vs.length ? vs.length / vs.reduce((a, v) => a + 1 / Math.max(v, 1e-9), 0) : 0;
  const levelName = (v, names) => v == null || v < 1 || !names.length ? "—" : names[Math.min(Math.floor(v), names.length) - 1];

  function sameSens(a, b) {
    const x = Number(a), y = Number(b);
    if (a === "" || b === "" || Number.isNaN(x) || Number.isNaN(y)) return a === b;
    return Math.abs(x - y) <= SENS_TOLERANCE * Math.max(Math.abs(y), 1e-9);
  }

  function energy(score, maxes, levels) {
    if (score <= 0) return 0;
    const n = maxes.length;
    if (score >= maxes[n - 1]) return levels[n - 1] + (score - maxes[n - 1]) / (maxes[n - 1] - maxes[n - 2]) * (levels[n - 1] - levels[n - 2]);
    for (let i = n - 1; i > 0; i--) {
      if (score >= maxes[i - 1]) return levels[i - 1] + (score - maxes[i - 1]) / (maxes[i] - maxes[i - 1]) * (levels[i] - levels[i - 1]);
    }
    return score / maxes[0] * levels[0];
  }

  function level(score, maxes) {
    if (score <= 0 || !maxes.length) return 0;
    const n = maxes.length;
    if (score < maxes[0]) return score / maxes[0];
    if (score >= maxes[n - 1]) return n + (score - maxes[n - 1]) / (n > 1 ? maxes[n - 1] - maxes[n - 2] : maxes[n - 1]);
    const i = maxes.filter(m => score >= m).length;
    return i + (score - maxes[i - 1]) / (maxes[i] - maxes[i - 1]);
  }

  function rows(data, scenarios, sensList, sens, levels) {
    const local = new Map(scenarios.map(s => [s.name, s]));
    const out = [];
    for (const [category, block] of Object.entries(data.categories)) {
      for (const [scenario, info] of Object.entries((block && block.scenarios) || {})) {
        const best = Number(info.score) / 100;   // сайт отдаёт очки ×100
        const maxes = (Array.isArray(info.rank_maxes) ? info.rank_maxes : []).map(Number);
        const s = local.get(scenario);
        const own = s ? s.s.filter((_, i) => sameSens(sensList[s.k[i]], sens)) : [];
        const form = own.length ? med(own.slice(-RECENT_RUNS)) : null;
        out.push({
          category, scenario, best, maxes,
          energy: levels ? energy(best, maxes, levels) : null, form,
          form_energy: levels && form != null ? energy(form, maxes, levels) : null,
          // тренд из обзора сценария — он посчитан на его последней сенсе; совпадает, если это сенса бенчмарка
          trend: own.length && s && sameSens(s.sens, sens) ? s.trend : null,
          last_played: s ? s.last : null,
          level: level(best, maxes), form_level: form != null ? level(form, maxes) : null,
        });
      }
    }
    return out;
  }

  function states(rowList, now, data) {
    return [...new Set(rowList.map(r => r.category))].map(name => {
      const group = rowList.filter(r => r.category === name);
      const last = maxOr(group.filter(r => r.last_played).map(r => r.last_played));
      return {
        name, energy: maxOr(group.filter(r => r.energy != null).map(r => r.energy)),
        form_energy: maxOr(group.filter(r => r.form_energy != null).map(r => r.form_energy)),
        days_idle: last == null ? null : Math.floor((now - last) / DAY_MS),
        level: Math.max(...group.map(r => r.level)),
        form_level: maxOr(group.filter(r => r.form_level != null).map(r => r.form_level)),
        site_rank: Number((data.categories[name] || {}).category_rank) || 0,
      };
    });
  }

  function notes(stateList, names) {
    const out = [];
    for (const s of [...stateList].sort((a, b) => (a.form_level ?? -1) - (b.form_level ?? -1))) {
      const label = s.name.trim();
      if (s.days_idle == null) out.push([label, "never", {}]);
      else if (s.form_level == null) out.push([label, "other_sens", {}]);
      else if (levelName(s.form_level, names) !== levelName(s.level, names)) {
        out.push([label, "form_below", {form: levelName(s.form_level, names), best: levelName(s.level, names)}]);
      } else if (s.days_idle >= 10) out.push([label, "stale", {days: s.days_idle}]);
    }
    return out;
  }

  function nearest(rowList, stateList, names) {
    const catLevel = Object.fromEntries(stateList.map(s => [s.name, s.level]));
    const out = [];
    for (const r of rowList) {
      const idx = r.maxes.findIndex(m => m > r.best);
      if (idx < 0 || idx + 1 <= catLevel[r.category]) continue;
      const need = r.maxes[idx] - r.best;
      out.push({category: r.category.trim(), scenario: r.scenario, need,
                rank: idx < names.length ? names[idx] : "#" + (idx + 1), share: need / r.maxes[idx]});
    }
    return out.sort((a, b) => a.share - b.share).slice(0, NEAREST_TOP);
  }

  /* Ответ сайта → то же, что bench_payload кладёт в дашборд. Пустой или чужой формы — ошибка. */
  function analyze(id, name, data, scenarios, sensList, sens, now) {
    if (!data || typeof data !== "object" || !data.categories || typeof data.categories !== "object" ||
        !Object.keys(data.categories).length) throw new Error("empty benchmark");
    const ranks = (Array.isArray(data.ranks) ? data.ranks : []).filter(r => r && typeof r === "object").slice(1)
      .map(r => ({name: String(r.name ?? "?").trim(), color: String(r.color ?? "").trim()}));
    const names = ranks.map(r => r.name), levels = energyLevels(names);
    const rowList = rows(data, scenarios, sensList, sens, levels);
    const stateList = states(rowList, now, data);
    const overall = levels ? {
      best: harmonic(stateList.map(s => s.energy)),
      form: harmonic(stateList.map(s => s.form_energy != null ? s.form_energy : s.energy)),
      missing: stateList.filter(s => s.form_energy == null).map(s => s.name.trim()),
    } : null;
    return {
      id, name, progress: data.benchmark_progress ?? 0, siteRank: Number(data.overall_rank) || 0, sens,
      ranks, levels, overall,
      categories: stateList.map(s => ({...s, name: s.name.trim(), scenarios: rowList.filter(r => r.category === s.name)
        .map(r => ({...r, short: r.scenario.replace(TIER_SUFFIX, "")}))})),
      notes: notes(stateList, names), nearest: nearest(rowList, stateList, names),
    };
  }

  return {analyze};
})();
