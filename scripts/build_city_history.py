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
import glob, json, os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DAILY = ROOT / "data" / "daily"
OUT = ROOT / "site" / "data"
MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

rows = []
for f in sorted(glob.glob(str(DAILY / "*.parquet"))):
    code = os.path.basename(f)[:-8]
    d = pd.read_parquet(f)
    d["date"] = pd.to_datetime(d["date"])
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
for f in sorted(glob.glob(str(DAILY / "*.parquet"))):
    d = pd.read_parquet(f); d["date"] = pd.to_datetime(d["date"])
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
    s = vdf.dropna(subset=[col]).groupby("date")[col].mean()
    if not len(s):
        continue
    clim, ann = clim_annual_mean(s)
    variables[key] = {"label": label, "unit": unit, "agg": "mean", "ramp": rmp, "clim": clim, "annual": ann}
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
    "annual": annual,
    "climatology": {"temp": climo(temp_mat), "rain": climo(rain_mat)},
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
