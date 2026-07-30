// Alert evaluation for the push cron. Thresholds MIRROR site/previsao.html and
// build_site_data.py (OMM rain, Beaufort wind, provisional temp bands, NWS heat index).
// Keep these in sync with those files and the cited sources.
const RANK = { ok: 0, warn: 1, alert: 2 };
const worstLevel = (parts) => parts.reduce((m, p) => (RANK[p.level] > RANK[m] ? p.level : m), 'ok');

// NWS Rothfusz (1990) regression of Steadman (1979) apparent temperature. Verified.
export function heatIndexC(tc, rh) {
  const T = tc * 9 / 5 + 32;
  let hi = 0.5 * (T + 61 + (T - 68) * 1.2 + rh * 0.094);   // simple
  if (hi >= 80) {
    hi = -42.379 + 2.04901523 * T + 10.14333127 * rh - 0.22475541 * T * rh
       - 0.00683783 * T * T - 0.05481717 * rh * rh + 0.00122874 * T * T * rh
       + 0.00085282 * T * rh * rh - 0.00000199 * T * T * rh * rh;
    if (rh < 13 && T >= 80 && T <= 112) hi -= ((13 - rh) / 4) * Math.sqrt((17 - Math.abs(T - 95)) / 17);
    else if (rh > 85 && T >= 80 && T <= 87) hi += ((rh - 85) / 10) * ((87 - T) / 5);
  }
  return (hi - 32) * 5 / 9;
}

export function evaluateObserved(snap) {
  const a = snap && snap.alert;
  if (!a) return { level: 'ok', hazards: [], stamp: '' };
  const parts = [];
  const add = (lvl, txt) => { if (lvl && lvl !== 'ok') parts.push({ level: lvl, txt }); };
  if (a.rain) add(a.rain.level, `chuva ${a.rain.class || ''} ${a.rain.value_mmph} mm/h${a.rain.station ? ' · ' + a.rain.station : ''}`);
  if (a.wind) add(a.wind.level, `vento ${a.wind.value_ms} m/s${a.wind.station ? ' · ' + a.wind.station : ''}`);
  if (a.temp) {
    if (a.temp.heat_level) add(a.temp.heat_level, `calor ${a.temp.max}°C${a.temp.hot_station ? ' · ' + a.temp.hot_station : ''}`);
    if (a.temp.cold_level) add(a.temp.cold_level, `frio ${a.temp.min}°C${a.temp.cold_station ? ' · ' + a.temp.cold_station : ''}`);
  }
  if (a.heat) add(a.heat.level, `sensação ${a.heat.app_c}°C${a.heat.station ? ' · ' + a.heat.station : ''}`);
  return { level: worstLevel(parts), hazards: parts, stamp: snap.generated_at || snap.reference_now || '' };
}

export function evaluateForecast(run, nowMs) {
  if (!run || !run.lead_h || !run.has) return { level: 'ok', hazards: [], stamp: (run && run.run_time) || '' };
  const src = (run.bairros && run.bairros.length) ? run.bairros : (run.basins || []);
  const base = run.run_time ? Date.parse(run.run_time.replace(' ', 'T') + 'Z') : NaN;
  let idxs;
  if (isNaN(base)) idxs = run.lead_h.map((_, i) => i);
  else {
    const cut = (nowMs || Date.now()) - 30 * 60000;
    idxs = run.lead_h.map((h, i) => ({ i, t: base + h * 3600e3 })).filter(o => o.t >= cut).map(o => o.i);
    if (!idxs.length) idxs = run.lead_h.map((_, i) => i);
  }
  idxs = idxs.slice(0, 24);   // next 24 h window (matches the Evolução chart / Acumulado)
  const worst = (pick, mode) => {
    let best = null, name = '';
    src.forEach(b => { const arr = pick(b); if (!arr) return;
      idxs.forEach(i => { const v = arr[i]; if (v == null) return;
        if (best == null || (mode === 'max' ? v > best : v < best)) { best = v; name = b.name; } }); });
    return { v: best, name };
  };
  const parts = [];
  const add = (lvl, txt) => { if (lvl && lvl !== 'ok') parts.push({ level: lvl, txt }); };
  if (run.has.rain) { const r = worst(b => b.rain && b.rain.series, 'max'), v = r.v || 0;
    const lvl = v >= 10 ? 'alert' : (v >= 2.5 ? 'warn' : 'ok');
    const cls = v < 2.5 ? 'leve' : (v < 10 ? 'moderada' : (v < 50 ? 'forte' : 'violenta'));
    add(lvl, `chuva ${cls} pico ${v.toFixed(1)} mm/h${r.name ? ' · ' + r.name : ''}`); }
  if (run.has.wind) { const w = worst(b => b.wind && b.wind.series, 'max'), v = w.v || 0;
    const lvl = v >= 17.2 ? 'alert' : (v >= 10.8 ? 'warn' : 'ok');
    add(lvl, `vento ${v.toFixed(1)} m/s${w.name ? ' · ' + w.name : ''}`); }
  if (run.has.temp) {
    const hot = worst(b => b.temp && b.temp.series, 'max'), cold = worst(b => b.temp && b.temp.series, 'min');
    const hotLvl = (hot.v != null && hot.v >= 36) ? 'alert' : (hot.v != null && hot.v >= 32 ? 'warn' : 'ok');
    const coldLvl = (cold.v != null && cold.v <= 3) ? 'alert' : (cold.v != null && cold.v <= 5 ? 'warn' : 'ok');
    if (hotLvl !== 'ok') add(hotLvl, `calor ${Math.round(hot.v)}°C${hot.name ? ' · ' + hot.name : ''}`);
    if (coldLvl !== 'ok') add(coldLvl, `frio ${Math.round(cold.v)}°C${cold.name ? ' · ' + cold.name : ''}`);
  }
  if (run.has.rain && run.has.temp && run.has.humid) {
    let best = null, name = '';
    src.forEach(b => { if (!b.temp || !b.temp.series || !b.humid || !b.humid.series) return;
      idxs.forEach(i => { const t = b.temp.series[i], rh = b.humid.series[i]; if (t == null || rh == null) return;
        const app = heatIndexC(t, rh); if (app != null && (best == null || app > best)) { best = app; name = b.name; } }); });
    if (best != null) { const lvl = best >= 41 ? 'alert' : (best >= 32 ? 'warn' : 'ok');
      if (lvl !== 'ok') add(lvl, `sensação ${Math.round(best)}°C${name ? ' · ' + name : ''}`); }
  }
  return { level: worstLevel(parts), hazards: parts, stamp: run.run_time || '' };
}
