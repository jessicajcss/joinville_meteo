#!/usr/bin/env python3
"""
build_river.py — quality-controlled river-stage data for the "Chuva & Rio" page.

River STAGE (nível) is a relative measurement tied to each gauge's own datum, and
the raw sensor records for the Joinville network contain three well-defined defects:

  1. Impossible spikes  — isolated readings of 1000+ m (sensor/telemetry glitches),
                          e.g. aguasdejoi 1085 m, divobras 1423 m, iateclube 1751 m.
  2. Datum-fault periods — multi-year stretches of physically impossible values,
                          e.g. divobras reads ~-4 m continuously across 2021-2024.
  3. Non-fluvial gauges  — iateclube ("Joinville Iate Club") sits on the Babitonga
                          Bay estuary; its "level" is the tide, not river stage.

This builder applies a documented, reproducible robust filter and writes clean data
for the dashboard WITHOUT touching the raw download CSVs.

Quality control, per station (level_max/level_min → daily mean stage):
  (a) hard physical bound  |stage| < 50 m           → removes telemetry spikes;
  (b) robust MAD window    median ± 6·1.4826·MAD    → removes residual outliers and
                                                      datum-fault stretches.
The MAD window is computed on the station's own record, so each gauge keeps its own
reference level (a small urban creek near 1 m and the Rio Cubatão staff gauge near
21 m are both valid — they are simply on different datums and are only ever plotted
each on its own axis). Stage below the datum (small negative values during dry
spells) is physically real and is kept when it survives the robust window.

Tidal/estuary gauges are classified out of the fluvial set (kept in a separate list
so the page can note the exclusion) rather than silently dropped.

Writes:
  site/data/river.json            index: station meta + QC report + city rain clim
  site/data/river/<code>.json     columnar QC'd daily series (loaded on demand)
"""
from __future__ import annotations
import calendar, glob, json, os, subprocess
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DAILY = ROOT / "data" / "daily"
HOURLY = ROOT / "data" / "hourly"
REG = pd.read_csv(ROOT / "data" / "geo" / "stations_master.csv").set_index("code")
OUT = ROOT / "site" / "data"
RVDIR = OUT / "river"
RVDIR.mkdir(parents=True, exist_ok=True)

# Domain knowledge: gauges on the Babitonga Bay estuary — the "nível" is dominated by
# tide, not fluvial stage. They are INCLUDED but flagged (estuary) and given their own
# comparison scale, so users can see them while understanding they are a distinct regime.
ESTUARY = {"iateclube"}

# Per-station reference note shown on the page (datum context, not a data change).
DATUM_NOTE = {
    "cubatao": "Régua referenciada a um datum local alto (~21 m); os valores são "
               "coerentes apenas dentro da própria estação.",
    "iateclube": "Estação no estuário da Baía Babitonga — o nível é dominado pela maré, "
                 "não pela vazão fluvial.",
}

HARD_M = 50.0   # |stage| bound in metres — anything beyond is a sensor/telemetry glitch
MAD_K  = 6.0    # robust window half-width in scaled-MAD units
# Physical-plausibility span (metres) below/above the station median. These near-sea-level
# urban rivers/estuaries cannot sit ~3 m below their gauge zero (that removes sustained
# sensor faults such as divobras' multi-year −4 m), but ±3 m easily covers real tides and
# floods — so a station's genuine tidal lows (e.g. flotflux −1.3 m) are NOT clipped even
# where its "quiet-period" MAD is tiny. The window is the WIDER of MAD·K and this span.
LO_SPAN = 2.8
HI_SPAN = 3.5
TIDAL_SCORE = 0.20     # min hour-locked diurnal amplitude (in ≥2 years) to flag a gauge tidal


def _window(valid: pd.Series):
    hard = valid[(valid > -HARD_M) & (valid < HARD_M)]
    med = float(np.median(hard))
    mad = float(np.median(np.abs(hard - med)))
    sig = 1.4826 * mad if mad > 0 else float(hard.std() or 1.0)
    return med, med - max(MAD_K * sig, LO_SPAN), med + max(MAD_K * sig, HI_SPAN)


def qc_level(lmax: pd.Series, lmin: pd.Series):
    """Return (clean_daily_mean_series, report dict, (lo, hi) bounds).
    Bounds are derived from the DAILY series (robust to multi-year faults, which are a
    minority of days) and reused for the hourly QC so both are consistent."""
    lm = (lmax + lmin) / 2.0
    valid = lm.dropna()
    n0 = int(len(valid))
    if n0 == 0:
        return (lm * np.nan,
                dict(n_raw=0, n_kept=0, dropped=0, frac=0.0, med=None, lo=None, hi=None,
                     lo_val=None, hi_val=None),
                (None, None))
    med, lo, hi = _window(valid)
    keep_mask = lm.notna() & (lm > -HARD_M) & (lm < HARD_M) & (lm >= lo) & (lm <= hi)
    clean = lm.where(keep_mask)
    kept = clean.dropna()
    rep = dict(n_raw=n0, n_kept=int(len(kept)), dropped=int(n0 - len(kept)),
               frac=round(len(kept) / n0, 3), med=round(med, 3),
               lo=round(lo, 3), hi=round(hi, 3),
               lo_val=round(float(kept.min()), 3) if len(kept) else None,
               hi_val=round(float(kept.max()), 3) if len(kept) else None)
    return clean, rep, (lo, hi)


def _profile_from(valid: pd.DataFrame):
    """Build the hour-of-day profile dict from a QC'd hourly frame with _lv/_hr/_day."""
    mean = [None] * 24; lo = [None] * 24; hi = [None] * 24; nn = [0] * 24
    for hr, grp in valid.groupby("_hr")["_lv"]:
        hr = int(hr)
        if hr < 0 or hr > 23:
            continue
        mean[hr] = round(float(grp.mean()), 3)
        lo[hr] = round(float(grp.quantile(0.25)), 3)
        hi[hr] = round(float(grp.quantile(0.75)), 3)
        nn[hr] = int(grp.size)
    if not any(v is not None for v in mean):
        return None
    drng = valid.groupby("_day")["_lv"].agg(lambda x: x.max() - x.min())
    drng = drng[drng.notna()]
    intraday = round(float(drng.median()), 3) if len(drng) else None
    return {"mean": mean, "lo": lo, "hi": hi, "n": nn, "n_hours": int(sum(nn)),
            "intraday_range": intraday}


def diurnal_profile(code: str, bounds):
    """Hour-of-day level profile (p25/p75 band) from hourly data, QC'd with the SAME
    bounds as the daily series. Also returns tidal_amp = the peak-year median daily
    oscillation, so a gauge that becomes tidal only in recent years (e.g. flotflux,
    whose gauge started resolving the tide ~2021) is still detected.
    Returns {full, by_year, hm, tidal_amp} or None."""
    hf = HOURLY / f"{code}.parquet"
    if not hf.exists():
        return None
    h = pd.read_parquet(hf)
    if "date" not in h.columns:
        return None
    lv = h["level"] if ("level" in h.columns and h["level"].notna().any()) \
        else (h.get("level_max") + h.get("level_min")) / 2 if "level_max" in h.columns else None
    if lv is None or not lv.notna().any():
        return None
    lo, hi = bounds if bounds else (-HARD_M, HARD_M)
    clean = lv.where(lv.notna() & (lv > -HARD_M) & (lv < HARD_M) & (lv >= lo) & (lv <= hi))
    h = h.assign(_lv=clean)
    ts = pd.to_datetime(h["date"])
    h["_hr"] = ts.dt.hour
    h["_day"] = ts.dt.date
    h["_yr"] = ts.dt.year
    h["_mo"] = ts.dt.month
    valid = h.dropna(subset=["_lv"])
    full = _profile_from(valid)
    if full is None:
        return None
    by_year, yearly_intraday, diurnal_amps = {}, [], []
    for yr, sub in valid.groupby("_yr"):
        if len(sub) >= 500:                 # enough hourly records for a stable daily cycle
            pr = _profile_from(sub)
            if pr:
                by_year[str(int(yr))] = pr
                if pr.get("intraday_range") is not None:
                    yearly_intraday.append(pr["intraday_range"])
                mvals = [v for v in pr["mean"] if v is not None]
                if len(mvals) >= 20:
                    diurnal_amps.append(max(mvals) - min(mvals))
    # physical swing (for the caption) = largest per-year median daily range
    tidal_amp = round(max(yearly_intraday), 3) if yearly_intraday else full.get("intraday_range")
    # tidal detector = a REGULAR hour-locked oscillation present in ≥2 years (robust to a
    # single anomalous year and to flood-driven daily ranges, which are not hour-locked)
    diurnal_amps.sort(reverse=True)
    tidal_score = (diurnal_amps[1] if len(diurnal_amps) >= 2
                   else (diurnal_amps[0] if diurnal_amps else 0.0))
    # hour × month matrix (mean level), climatology and per year — feeds the heatmap
    def month_matrix(frame):
        mm = {}
        for mo, sub in frame.groupby("_mo"):
            if len(sub) >= 60:
                pr = _profile_from(sub)
                if pr:
                    mm[str(int(mo))] = [round(v, 3) if v is not None else None for v in pr["mean"]]
        return mm
    hm = {"all": month_matrix(valid)}
    for yr, sub in valid.groupby("_yr"):
        if len(sub) >= 500:
            mm = month_matrix(sub)
            if mm:
                hm[str(int(yr))] = mm
    return {"full": full, "by_year": by_year, "hm": hm,
            "tidal_amp": tidal_amp, "tidal_score": round(float(tidal_score), 3)}


def rnd(v, n=1):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), n)


fluvial = []
hm_anom_mags, med_anom_mags, est_anom_mags = [], [], []   # fixed anomaly limits (rivers vs estuary)

for f in sorted(glob.glob(str(DAILY / "*.parquet"))):
    code = os.path.basename(f)[:-8]
    if code not in REG.index:
        continue
    d = pd.read_parquet(f)
    if "level_max" not in d.columns or not d["level_max"].notna().any():
        continue
    d["date"] = pd.to_datetime(d["date"]); d = d.sort_values("date").reset_index(drop=True)
    for c in ("temp_mean", "temp_max", "temp_min", "prec"):
        if c not in d.columns:
            d[c] = np.nan

    clean, rep, bounds = qc_level(d["level_max"], d["level_min"])
    if rep["n_kept"] < 30:                      # too little sound level data to plot
        continue

    # period of sound level data
    kept_dates = d.loc[clean.notna(), "date"]
    lvl_period = [str(kept_dates.min().date()), str(kept_dates.max().date())]
    has_temp = bool(d["temp_max"].notna().any())

    is_estuary = code in ESTUARY
    # years actually available (drive the per-plot Ano selectors from real coverage)
    data_years = sorted({int(y) for y in d["date"].dt.year.unique()})
    lv_years = sorted({int(y) for y in d.loc[clean.notna(), "date"].dt.year.unique()})

    dp = diurnal_profile(code, bounds)
    diurnal = dp["full"] if dp else None
    tidal_amp = dp.get("tidal_amp") if dp else None
    tidal_score = dp.get("tidal_score") if dp else None
    hm = dp.get("hm") if dp else None
    hm_years = sorted([k for k in (hm or {}) if k != "all"], key=int)

    # anomaly magnitudes for the fixed heatmap scale — rivers and estuary pooled separately
    if hm and hm.get("all"):
        cells = [v for arr in hm["all"].values() for v in arr if v is not None]
        if cells:
            cmean = sum(cells) / len(cells)
            (est_anom_mags if is_estuary else hm_anom_mags).extend(abs(v - cmean) for v in cells)
    if not is_estuary:
        lvser = clean.dropna()
        if len(lvser):
            smed = float(np.median(lvser))
            tmp = pd.DataFrame({"lv": clean, "mo": d["date"].dt.month}).dropna()
            for _m, gm in tmp.groupby("mo"):
                med_anom_mags.append(abs(float(gm["lv"].median()) - smed))

    series = {
        "d":  [x.strftime("%Y-%m-%d") for x in d["date"]],
        "ta": [rnd(v, 1) for v in d["temp_mean"]] if has_temp else None,
        "tx": [rnd(v, 1) for v in d["temp_max"]] if has_temp else None,
        "tn": [rnd(v, 1) for v in d["temp_min"]] if has_temp else None,
        "p":  [rnd(v, 1) for v in d["prec"]],
        "lv": [rnd(v, 3) for v in clean],
        "diurnal": diurnal,
        "diurnal_hm": hm,
    }
    (RVDIR / f"{code}.json").write_text(
        json.dumps(series, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    r = REG.loc[code]
    meta = {
        "code": code, "name": str(r["name"]), "type": str(r["type"]),
        "lat": float(r["lat"]), "lon": float(r["lon"]),
        "has_temp": has_temp,
        "has_diurnal": bool(diurnal),
        "estuary": is_estuary,
        "intraday_range": (round(tidal_amp, 2) if tidal_amp is not None else None),
        # tidal = regular hour-locked oscillation in ≥2 years, OR an estuary gauge
        "tidal": bool(is_estuary or (tidal_score is not None and tidal_score >= TIDAL_SCORE)),
        "data_years": data_years, "level_years": lv_years, "hm_years": hm_years,
        "level_period": lvl_period,
        "datum_note": DATUM_NOTE.get(code, ""),
        "qc": rep,
    }
    fluvial.append(meta)

# rivers first, estuary last
fluvial.sort(key=lambda s: (s["estuary"], s["name"]))

# city monthly rainfall climatology (for the top bars) — reuse city_history if present
city_rain = None
ch = OUT / "city_history.json"
if ch.exists():
    try:
        cj = json.loads(ch.read_text(encoding="utf-8"))
        city_rain = (cj.get("climatology") or {}).get("rain")
    except Exception:
        city_rain = None

# per-station monthly rainfall climatology → small-multiples panels ("Cwmystwyth" style).
# Monthly total per year requires >=20 valid days; climatology = mean across years;
# only stations with >=5 documented years are shown, ordered wettest → driest.
MIN_YEARS_PANEL = 5
rain_panels = []
year_station_count = {}   # year -> number of stations reporting >=10 months
for f in sorted(glob.glob(str(DAILY / "*.parquet"))):
    code = os.path.basename(f)[:-8]
    if code not in REG.index:
        continue
    d = pd.read_parquet(f)
    if "prec" not in d.columns or not d["prec"].notna().any():
        continue
    d["date"] = pd.to_datetime(d["date"]); d["y"] = d["date"].dt.year; d["mo"] = d["date"].dt.month
    clim, years = [], set()
    by_year = {}                                  # year -> [12 monthly totals]
    by_year_cov = {}                              # year -> [12 coverage % (valid days / days in month)]
    cov_accum = [[] for _ in range(12)]           # per-month coverage across years (for climatology)
    for y, gy in d.groupby("y"):
        arr = [None] * 12; cov = [None] * 12; nmon = 0
        for m, mg in gy.groupby("mo"):
            ndays = calendar.monthrange(int(y), int(m))[1]
            valid = int(mg["prec"].notna().sum())
            cov[int(m) - 1] = round(100.0 * valid / ndays)
            cov_accum[int(m) - 1].append(100.0 * valid / ndays)
            if valid >= 20:
                arr[int(m) - 1] = round(float(mg["prec"].sum()), 1); nmon += 1
        if nmon >= 1:
            by_year[int(y)] = arr
            by_year_cov[int(y)] = cov
        if nmon >= 10:
            year_station_count[int(y)] = year_station_count.get(int(y), 0) + 1
    clim_cov = [round(float(np.mean(c))) if c else None for c in cov_accum]
    for m in range(1, 13):
        mt = []
        for y, g in d[d["mo"] == m].groupby("y"):
            if g["prec"].notna().sum() >= 20:
                mt.append(float(g["prec"].sum())); years.add(int(y))
        clim.append(round(float(np.mean(mt)), 1) if mt else None)
    if len(years) < MIN_YEARS_PANEL or not any(v is not None for v in clim):
        continue
    annual = round(float(np.nansum([v for v in clim if v is not None])))
    r = REG.loc[code]
    rain_panels.append({"code": code, "name": str(r["name"]), "type": str(r["type"]),
                        "lat": float(r["lat"]), "lon": float(r["lon"]),
                        "clim": clim, "clim_cov": clim_cov, "annual": annual, "n_years": len(years),
                        "by_year": {str(k): v for k, v in sorted(by_year.items())},
                        "by_year_cov": {str(k): v for k, v in sorted(by_year_cov.items())}})
rain_panels.sort(key=lambda p: -p["annual"])
for i, p in enumerate(rain_panels):     # stable color index (shared across map, panels, month chart)
    p["ci"] = i
# years worth offering in the selector: >=3 stations reporting a near-complete year
rain_years = sorted([y for y, c in year_station_count.items() if c >= 3])

stamp = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%MZ"],
                       capture_output=True, text=True).stdout.strip()
qc_note = (f"Controle de qualidade do nível: limite físico |h| < {HARD_M:.0f} m e janela robusta "
           f"mediana ± o maior entre {MAD_K:.0f}·MADn (MAD normalizada = 1,4826·MAD ≈ desvio-padrão "
           f"robusto) e a faixa física (−{LO_SPAN:.1f} / +{HI_SPAN:.1f} m) "
           "por estação — remove apenas falhas de sensor. Joinville é "
           "cidade de baía (Babitonga): as estações a jusante sofrem influência de maré, portanto "
           "as oscilações e os níveis abaixo da régua (negativos) são reais e foram preservados.")

(OUT / "river.json").write_text(json.dumps({
    "generated_at": stamp,
    "qc_method": qc_note,
    "hard_bound_m": HARD_M, "mad_k": MAD_K,
    "city_rain_clim": city_rain,
    "rain_panels": rain_panels,
    "rain_years": rain_years,
    # fixed, comparable heatmap-anomaly limits (p98 of |deviation from station centre|);
    # rivers and the estuary use separate scales (the estuary tidal range is far larger).
    "hm_alim": round(float(np.percentile(hm_anom_mags, 98)), 2) if hm_anom_mags else 0.5,
    "hm_alim_estuary": round(float(np.percentile(est_anom_mags, 98)), 2) if est_anom_mags else 1.5,
    "lvl_alim": round(float(max(med_anom_mags)) * 1.05, 2) if med_anom_mags else 0.4,
    "stations": fluvial,
}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

print(f"river/estuary stations: {len(fluvial)} | rain panels: {len(rain_panels)}")
for s in fluvial:
    q = s["qc"]
    print(f"  {s['code']:14s}{'[EST]' if s['estuary'] else '     '} kept {q['n_kept']:>5}/{q['n_raw']:<5} "
          f"({q['frac']*100:3.0f}%) range[{q['lo_val']},{q['hi_val']}] m  "
          f"level_yrs {s['level_years'][0]}..{s['level_years'][-1]} tidal={s['tidal']}")
