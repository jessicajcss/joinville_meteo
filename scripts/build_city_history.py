#!/usr/bin/env python3
"""
build_city_history.py — city-wide monthly climatology for the "Histórico · cidade"
page. Reads the daily masters and produces site/data/city_history.json.

City aggregation (documented, strictly from the data):
  * Daily network temperature = mean, across all stations reporting that day, of
    the station daily-mean temperature (temp_mean, or (temp_max+temp_min)/2 where
    the mean is absent). Monthly value = mean of those daily values (months with
    < 10 valid days are left null).
  * Monthly rainfall = the across-station MEAN of each station's monthly total,
    counting only station-months with >= 20 valid days (spatial average; rainfall
    is highly local, so this is a city estimate, not a point value).
  * Annual temp = mean of that year's monthly means; annual rain = sum of that
    year's monthly city totals (years with < 6 months are left null).
  * Climatology = the long-term mean for each calendar month across all years.
"""
from __future__ import annotations
import glob, json, os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import masters

ROOT = Path(__file__).resolve().parent.parent
DAILY = ROOT / "data" / "daily"
OUT = ROOT / "site" / "data"
MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

rows = []
for code, d in masters.iter_masters(DAILY):
    tmean = d["temp_mean"] if "temp_mean" in d else pd.Series(np.nan, index=d.index)
    if "temp_max" in d and "temp_min" in d:
        tmean = tmean.fillna((d["temp_max"] + d["temp_min"]) / 2)
    rows.append(pd.DataFrame({
        "date": d["date"], "code": code,
        "tmean": tmean,
        "prec": d["prec"] if "prec" in d else np.nan,
    }))
long = pd.concat(rows, ignore_index=True)

# ---- daily network temperature -> monthly mean ----
net_daily_t = long.dropna(subset=["tmean"]).groupby("date")["tmean"].mean()
mt = net_daily_t.resample("MS")
city_temp = mt.mean().where(mt.count() >= 10)

# ---- rainfall from the pluviômetro (rain-gauge) network — the authoritative source ----
# (meteo-station rain sensors, incl. UDESC, are NOT used for rainfall climatology)
gc = pd.read_csv(ROOT / "data" / "gauges" / "gauge_city_daily.csv")
gc["date"] = pd.to_datetime(gc["date"])
gc = gc.dropna(subset=["city_rain_mm"]).set_index("date")["city_rain_mm"].sort_index()
gm = gc.resample("MS")
city_rain = gm.sum().where(gm.count() >= 20)          # monthly total, >= 20 valid days

# rainfall-story metrics (gauge network)
rainy = gc >= 1.0                                      # a "rainy day" = >= 1 mm
rainy_year = rainy.groupby(gc.index.year).sum()
cover_year = gc.groupby(gc.index.year).size()
wettest = gc.idxmax()
top = gc.sort_values(ascending=False).head(5)
STORY = {
    "wettest_day": {"date": str(wettest.date()), "mm": round(float(gc.max()), 1)},
    "top_days": [{"date": str(i.date()), "mm": round(float(v), 1)} for i, v in top.items()],
    "rainy_days_by_year": {int(y): int(n) for y, n in rainy_year.items() if cover_year[y] >= 330},
    "gauge_period": [str(gc.index.min().date()), str(gc.index.max().date())],
}
_rd = [v for v in STORY["rainy_days_by_year"].values()]
STORY["rainy_days_mean"] = round(float(np.mean(_rd))) if _rd else None

# ---- temperature record days (robust city daily extremes) ----
# City daily high/low = the across-station MEDIAN of that day's station daily
# max/min (median resists a single sun-baked or shaded sensor), requiring >= 3
# stations and applying physical bounds before ranking. Reported as the hottest
# and coldest days on record for the network.
tx_rows = []
for _code, d in masters.iter_masters(DAILY):
    tx_rows.append(pd.DataFrame({
        "date": d["date"],
        "tmax": d["temp_max"] if "temp_max" in d else np.nan,
        "tmin": d["temp_min"] if "temp_min" in d else np.nan,
    }))
tx = pd.concat(tx_rows, ignore_index=True)
tx.loc[(tx["tmax"] > 42) | (tx["tmax"] < -5), "tmax"] = np.nan
tx.loc[(tx["tmin"] > 35) | (tx["tmin"] < -10), "tmin"] = np.nan
gx = tx.dropna(subset=["tmax"]).groupby("date")["tmax"]
gn = tx.dropna(subset=["tmin"]).groupby("date")["tmin"]
city_tmax = gx.median().where(gx.count() >= 3)
city_tmin = gn.median().where(gn.count() >= 3)
_hot = city_tmax.dropna().sort_values(ascending=False).head(5)
_cold = city_tmin.dropna().sort_values().head(5)
STORY["hottest_days"] = [{"date": str(i.date()), "tmax": round(float(v), 1)} for i, v in _hot.items()]
STORY["coldest_days"] = [{"date": str(i.date()), "tmin": round(float(v), 1)} for i, v in _cold.items()]
STORY["temp_record_method"] = ("mediana das máximas/mínimas diárias das estações naquele dia "
                               "(>= 3 estações), com limites físicos")

# ---- wind: city-mean speed + windiest days (by gust) + predominant direction ----
# Wind SPEED climatology and predominant DIRECTION are derived from the 5-MINUTE
# records (site/data/stations/fivemin/); a station with no 5-minute store falls
# back to its hourly master. Gust EXTREMES stay on the daily master (a daily
# maximum is already the peak of the finer record).
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import fivemin
CALM_MS = 0.5; STUCK_FRAC = 0.25
COMPASS = ["N", "NNE", "NE", "ENE", "L", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
HOURLY = ROOT / "data" / "hourly"

def _station_wind(code):
    """(DataFrame[date,wd,ws], source) preferring the 5-min store, else hourly."""
    d = fivemin.load_wind(code); src = "5min"
    if d is None:
        f = HOURLY / f"{code}.csv"
        if not f.exists():
            return None, None
        try:
            d = pd.read_csv(f, usecols=lambda c: c in ("date", "wd", "ws"))
        except Exception:
            return None, None
        if "wd" not in d.columns or "ws" not in d.columns:
            return None, None
        d["date"] = pd.to_datetime(d["date"], errors="coerce"); src = "hourly"
    d = d.dropna(subset=["date"])
    return (d if len(d) else None), src

raw_wind = {}    # code -> (DataFrame[date,wd,ws], src)
for code in masters.codes(DAILY):
    dw, src = _station_wind(code)
    if dw is not None:
        raw_wind[code] = (dw, src)
WIND_RES = "5 min" if any(s == "5min" for _, s in raw_wind.values()) else "horária"

# monthly city-mean wind speed: per-station daily mean (all valid ws incl. calm),
# averaged across stations per day, then monthly (months with < 10 valid days null)
w_rows = []
for code, (dw, src) in raw_wind.items():
    s = dw.dropna(subset=["ws"])
    s = s[(s["ws"] >= 0) & (s["ws"] < 60)]                       # physical bound (m/s)
    if not len(s):
        continue
    day = s.set_index("date")["ws"].resample("D").mean()
    w_rows.append(pd.DataFrame({"date": day.index, "code": code, "ws": day.to_numpy()}))
wx = pd.concat(w_rows, ignore_index=True) if w_rows else pd.DataFrame(columns=["date", "code", "ws"])
net_daily_w = wx.dropna(subset=["ws"]).groupby("date")["ws"].mean()
mw = net_daily_w.resample("MS")
city_wind = mw.mean().where(mw.count() >= 10)                    # monthly city-mean wind speed

# windiest days (robust city daily peak gust) — from the daily master's gust_max
gx_rows = []
for _code, d in masters.iter_masters(DAILY):
    gx_rows.append(pd.DataFrame({"date": d["date"],
                                 "gust": d["gust_max"] if "gust_max" in d else np.nan}))
gxx = pd.concat(gx_rows, ignore_index=True)
gxx.loc[(gxx["gust"] > 60) | (gxx["gust"] < 0), "gust"] = np.nan  # physical bound (m/s)
gg = gxx.dropna(subset=["gust"]).groupby("date")["gust"]
city_gust = gg.median().where(gg.count() >= 3)                   # robust city daily peak gust
_wind = city_gust.dropna().sort_values(ascending=False).head(5)
STORY["windiest_days"] = [{"date": str(i.date()), "gust": round(float(v), 1)} for i, v in _wind.items()]
STORY["wind_record_method"] = "mediana da rajada máxima diária das estações naquele dia (>= 3 estações)"

# predominant wind DIRECTION (meteorological: the sector winds come FROM), from the 5-minute wd.
# Method: vector resultant (Grange 2014, "Averaging wind speeds and directions"; the method
# used by the R `openair` package). Directions cannot be arithmetically averaged (the 0/360
# discontinuity), so each hourly obs is resolved into flow vectors
#   u = -ws*sin(theta),  v = -ws*cos(theta)      (theta = FROM bearing, radians)
# the (u,v) are averaged, and the resultant FROM direction is atan2(mean_u, mean_v)+180 deg.
# We average station-equal-weight (each station contributes its own mean vector, then those
# are averaged) so a single long coastal record does not dominate the city-wide value —
# consistent with the request for a "todo o município" (whole-city) view.
# The single most-frequent 22.5 deg sector (mode) was rejected: Joinville's rose is near-flat
# (no sector > ~11%), so the mode is noisy and, when checked, hid the real seasonal cycle.
# The vector resultant recovers it: summer -> E/ESE (sea breeze off the Babitonga bay),
# autumn-winter (Apr-Jul, peak May-Jun) -> S/SSO/SO (post-frontal polar air), matching the
# physical expectation and the independent sea-breeze diurnal test.
MIN_ST_N = 576         # min valid samples for a station to join a group (~2 days @ 5 min)
MIN_ST_N_HOURLY = 48   # equivalent floor when a station falls back to hourly (~2 days)
MIN_STATIONS_DIR = 2   # need >= 2 stations for a city-wide resultant

def _uv(wd, ws):
    th = np.deg2rad(wd)
    return -ws * np.sin(th), -ws * np.cos(th)

def resultant_dir(station_arrays):
    # station_arrays: list of (wd, ws, min_n) tuples (one per station), already QC'd:
    # calm winds (ws<CALM_MS) and the exact-0.0 stuck-vane sentinel are excluded upstream.
    mus, mvs, ntot, nst, ok = [], [], 0, 0, []
    for wd, ws, min_n in station_arrays:
        if len(wd) < min_n:
            continue
        u, v = _uv(wd, ws)
        mus.append(float(np.mean(u))); mvs.append(float(np.mean(v)))
        ntot += int(len(wd)); nst += 1; ok.append((wd, ws))
    if nst < MIN_STATIONS_DIR:
        return None
    mu, mv = float(np.mean(mus)), float(np.mean(mvs))
    frm = (np.degrees(np.arctan2(mu, mv)) + 180.0) % 360.0   # resultant FROM bearing
    sec = int(np.floor(((frm % 360) + 11.25) / 22.5)) % 16
    band = [(sec - 1) % 16, sec, (sec + 1) % 16]
    octs = []
    for wd, ws in ok:
        s = (np.floor(((wd % 360) + 11.25) / 22.5).astype(int)) % 16
        octs.append(float(np.mean(np.isin(s, band)) * 100))   # % samples within +/-1 sector
    scalar = np.mean([float(np.mean(ws)) for wd, ws in ok])
    r = float(np.hypot(mu, mv))
    return {"deg": round(frm, 1), "sector": COMPASS[sec],
            "pct": round(float(np.mean(octs)), 1),            # predominancia (octant frequency)
            "r": round(r, 3), "const": round(r / scalar, 3) if scalar else None,
            "n": ntot, "nst": nst}

# per-station QC'd direction frames (calm, 0-sentinel and stuck-vane stations removed)
st_dir = {}   # code -> (DataFrame[date,wd,ws,mo,y], min_n)
for code, (dw, src) in raw_wind.items():
    d = dw.dropna(subset=["wd", "ws"])
    wd_s = d["wd"].to_numpy(float); ws_s = d["ws"].to_numpy(float); windy = ws_s >= CALM_MS
    if windy.sum() >= 100 and float(np.mean(wd_s[windy] == 0.0)) > STUCK_FRAC:
        continue                                              # stuck/absent vane -> drop station
    m = (ws_s >= CALM_MS) & (wd_s != 0.0) & np.isfinite(wd_s) & np.isfinite(ws_s)
    d = d[m]
    if d.empty:
        continue
    d = d.assign(mo=d["date"].dt.month, y=d["date"].dt.year)
    st_dir[code] = (d, MIN_ST_N if src == "5min" else MIN_ST_N_HOURLY)

wind_dir = {"clim": [None] * 12, "annual": [],
            "method": f"resultante vetorial (Grange 2014; openair), peso igual por estação; dados de {WIND_RES}"}
if st_dir:
    for k in range(1, 13):
        arrs = [(g["wd"].to_numpy(float), g["ws"].to_numpy(float), mn)
                for (d, mn) in st_dir.values() for g in [d[d["mo"] == k]] if len(g)]
        wind_dir["clim"][k - 1] = resultant_dir(arrs)
    years_w = sorted({int(y) for (d, _) in st_dir.values() for y in d["y"].unique()})
    for y in years_w:
        arrs = [(g["wd"].to_numpy(float), g["ws"].to_numpy(float), mn)
                for (d, mn) in st_dir.values() for g in [d[d["y"] == y]] if len(g)]
        r = resultant_dir(arrs)
        if r:
            r["year"] = int(y); wind_dir["annual"].append(r)

# ---- assemble year x month matrices ----
idx = pd.period_range(min(city_temp.index.min(), city_rain.index.min() if len(city_rain) else city_temp.index.min()),
                      max(city_temp.index.max(), city_rain.index.max() if len(city_rain) else city_temp.index.max()),
                      freq="M")
years = sorted({p.year for p in idx})

def matrix(series):
    m = {(y): [None] * 12 for y in years}
    for ts, val in series.items():
        if pd.notna(val):
            m[ts.year][ts.month - 1] = round(float(val), 1)
    return [m[y] for y in years]

temp_mat = matrix(city_temp)
rain_mat = matrix(city_rain)
wind_mat = matrix(city_wind)

# ---- annual + climatology ----
annual = []
for i, y in enumerate(years):
    tvals = [v for v in temp_mat[i] if v is not None]
    rvals = [v for v in rain_mat[i] if v is not None]
    annual.append({
        "year": y,
        "temp_mean": round(float(np.mean(tvals)), 1) if len(tvals) >= 6 else None,
        "rain_total": round(float(np.sum(rvals)), 0) if len(rvals) >= 6 else None,
        "rain_months": len(rvals),
        "rainy_days": STORY["rainy_days_by_year"].get(y),
    })

def climo(mat):
    out = []
    for mo in range(12):
        vals = [mat[i][mo] for i in range(len(years)) if mat[i][mo] is not None]
        out.append(round(float(np.mean(vals)), 1) if vals else None)
    return out

# ---- per-variable climatology + annual means (tf.tang summary page) ----
def clim_annual_mean(s):
    mon = s.resample("MS").mean()
    clim = [None] * 12
    for k in range(1, 13):
        sub = mon[mon.index.month == k].dropna()
        clim[k - 1] = round(float(sub.mean()), 1) if len(sub) else None
    yr = mon.resample("YS").mean().dropna()
    return clim, [{"year": int(t.year), "value": round(float(v), 1)} for t, v in yr.items()]

vrows = []
for _code, d in masters.iter_masters(DAILY):
    for c in ["temp_mean", "umid_mean", "solar_mean", "ws_mean"]:
        if c not in d: d[c] = np.nan
    vrows.append(d[["date", "temp_mean", "umid_mean", "solar_mean", "ws_mean"]])
vdf = pd.concat(vrows, ignore_index=True)

variables = {}
for key, col, label, unit, rmp in [
    ("temp", "temp_mean", "Temperatura", "°C", "temp"),
    ("umid", "umid_mean", "Umidade relativa", "%", "humid"),
    ("solar", "solar_mean", "Radiação solar", "W/m²", "sun"),
    ("wind", "ws_mean", "Vento", "m/s", "wind")]:
    # Vento (mean speed) uses the 5-min-derived network daily mean, consistent with
    # the wind rose / predominant direction; the other variables use the daily masters.
    s = net_daily_w if key == "wind" else vdf.dropna(subset=[col]).groupby("date")[col].mean()
    if not len(s):
        continue
    clim, ann = clim_annual_mean(s)
    variables[key] = {"label": label, "unit": unit, "agg": "mean", "ramp": rmp, "clim": clim, "annual": ann}
    if key == "wind":
        variables[key]["resolution"] = WIND_RES
# rainfall: monthly totals -> climatology = mean monthly total; annual = total
clim_r = [None] * 12
for k in range(1, 13):
    sub = city_rain[city_rain.index.month == k].dropna()
    clim_r[k - 1] = round(float(sub.mean()), 0) if len(sub) else None
ry = city_rain.resample("YS").sum(min_count=6).dropna()
variables["rain"] = {"label": "Chuva", "unit": "mm", "agg": "sum", "ramp": "rain",
                     "clim": clim_r, "annual": [{"year": int(t.year), "value": round(float(v), 0)} for t, v in ry.items()]}

payload = {
    "generated_at": pd.Timestamp.now("UTC").isoformat(),
    "variables": variables,
    "years": years,
    "months": MONTHS,
    "temp": temp_mat,
    "rain": rain_mat,
    "wind": wind_mat,
    "annual": annual,
    "climatology": {"temp": climo(temp_mat), "rain": climo(rain_mat), "wind": climo(wind_mat)},
    "wind_dir": wind_dir,
    "wind_resolution": WIND_RES,
    "story": STORY,
    "reference_annual_rain_mm": 2130,
    "notes": "Temperatura, umidade, radiação e vento = média da rede meteorológica. Chuva = média espacial combinada da rede de pluviômetros da Defesa Civil e das estações meteorológicas (excluídos o pluviômetro Nova Brasília, com falha, e a estação UDESC, que superestima). Precipitação média anual de referência para Joinville: ~2.130 mm (média de 42 postos desde 1950; cf. De Mello, 2020). Meses/anos com poucos dias válidos aparecem em cinza.",
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "city_history.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

print(f"years: {years[0]}–{years[-1]} ({len(years)})")
print(f"temp months with data: {sum(v is not None for row in temp_mat for v in row)}")
print(f"rain months with data: {sum(v is not None for row in rain_mat for v in row)}")
print("climatology temp:", payload["climatology"]["temp"])
print("climatology rain:", payload["climatology"]["rain"])
print("annual sample:", [a for a in annual if a["temp_mean"] is not None][:3])
