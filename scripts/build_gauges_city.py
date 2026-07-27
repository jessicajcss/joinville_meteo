#!/usr/bin/env python3
"""
build_gauges_city.py — city daily-rainfall series BLENDED from the two networks:
the Defesa Civil rain-gauge (pluviômetro) network AND the meteo-station rain
sensors. Rainfall is highly local, so pooling every valid site and taking the
spatial mean gives the best city-wide estimate.

Anchored to the literature: Joinville's mean annual rainfall is ~2,130 mm
(42-gauge average since 1950; e.g. the Joinville precipitation studies and
De Mello 2020 on the Serra Dona Francisca). The gauge network ALONE reads low,
partly because the "Nova Brasília" gauge is a flat zero (no data) and some
gauges sit in drier parts of the city — hence the blend.

Excluded sites:
  * gauge "novabrasilia" — reads a constant 0 (broken / no data).
  * meteo station "udesc"  — consumer gauge over-reads (~1.7x).

Inputs:
  data/processed/pluvio_daily.csv                     (long) 2014-2020 gauges
  meteo/PLUVIOMETROS/pluviometros_raw_2021_2025.csv   (10-min) 2021-2025 gauges
  data/daily/*.parquet                                (meteo-station daily prec)

Output: data/processed/gauge_city_daily.csv  (date, city_rain_mm, n_sites)
  city_rain_mm = spatial mean of all valid sites reporting that day (>= 3 sites).
"""
from __future__ import annotations
from pathlib import Path
import glob, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import masters

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
GAUGES = ROOT / "data" / "gauges"; GAUGES.mkdir(parents=True, exist_ok=True)
DAILY = ROOT / "data" / "daily"
RAW21 = Path("/mnt/user-data/uploads/projeto_resposta_eventos/meteo/PLUVIOMETROS/pluviometros_raw_2021_2025.csv")
MAP = {"Aventureiro": "aventureiro", "Centro": "centro", "Costa e Silva": "costaesilva",
       "Estrada Geral Salto I": "estradageral", "Iririu": "iririu", "Itinga": "itinga",
       "Nova Brasília": "novabrasilia", "Paranaguamirim": "paranaguamirim"}
GAUGE_EXCLUDE = {"novabrasilia"}     # flat zero
METEO_EXCLUDE = {"udesc"}            # over-reads

rows = []  # long: date, site, rain_mm

# --- gauges 2014-2020 (already daily) ---
p = GAUGES / "pluvio_daily.csv"
if p.exists():
    d1 = pd.read_csv(p); d1["date"] = pd.to_datetime(d1["date"], errors="coerce")
    d1 = d1.dropna(subset=["date"])
    d1 = d1[~d1["gauge"].isin(GAUGE_EXCLUDE)]
    rows.append(d1.assign(site="gauge:" + d1["gauge"])[["date", "site", "rain_mm"]])

# --- gauges 2021-2025 (10-min -> daily) ---
# The raw 10-min file lives OUTSIDE the repo. When present (local), process it and
# cache the daily result into the repo so the GitHub Action — which has only the
# cache — can rebuild the city rainfall without the raw file.
CACHE = GAUGES / "gauge_daily_2021_2025.csv"
d2 = None
if RAW21.exists():
    raw = pd.read_csv(RAW21)
    raw["date"] = pd.to_datetime(raw["date"], format="ISO8601", errors="coerce")
    raw = raw.dropna(subset=["date"]).rename(columns=MAP).set_index("date")
    cols = [c for c in MAP.values() if c in raw.columns and c not in GAUGE_EXCLUDE]
    for c in cols:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    daily2 = raw[cols].resample("D").sum(min_count=100)
    d2 = daily2.reset_index().melt(id_vars="date", var_name="gauge", value_name="rain_mm").dropna(subset=["rain_mm"])
    d2.to_csv(CACHE, index=False)
elif CACHE.exists():
    d2 = pd.read_csv(CACHE, parse_dates=["date"])
if d2 is not None:
    rows.append(d2.assign(site="gauge:" + d2["gauge"])[["date", "site", "rain_mm"]])

# --- meteo-station daily prec ---
for code, d in masters.iter_masters(DAILY):
    if code in METEO_EXCLUDE:
        continue
    if "prec" not in d.columns:
        continue
    s = d[["date", "prec"]].dropna(subset=["prec"]).rename(columns={"prec": "rain_mm"})
    if len(s):
        rows.append(s.assign(site="meteo:" + code)[["date", "site", "rain_mm"]])

pool = pd.concat(rows, ignore_index=True)
pool = pool.drop_duplicates(["date", "site"], keep="last")
pool["rain_mm"] = pd.to_numeric(pool["rain_mm"], errors="coerce").clip(lower=0)
pool = pool.dropna(subset=["rain_mm"])

city = pool.groupby("date")["rain_mm"].agg(city_rain_mm="mean", n_sites="count").reset_index()
city.loc[city["n_sites"] < 3, "city_rain_mm"] = np.nan
city = city.sort_values("date")
city.to_csv(GAUGES / "gauge_city_daily.csv", index=False)

c = city.dropna(subset=["city_rain_mm"]).set_index("date")["city_rain_mm"]
yr = c.resample("YS").sum()
print(f"sites pooled: {sorted(pool['site'].unique())}")
print(f"city daily rain: {c.index.min().date()} -> {c.index.max().date()} ({len(c)} days)")
print("annual blended city rainfall (mm):")
for ts, v in yr.items():
    n = int(c[c.index.year == ts.year].shape[0])
    if n >= 330:
        print(f"  {ts.year}: {v:6.0f}  ({n} days)")
full = [v for ts, v in yr.items() if int(c[c.index.year == ts.year].shape[0]) >= 350]
print(f"mean of full years: {np.mean(full):.0f} mm  (reference ~2130 mm)")
