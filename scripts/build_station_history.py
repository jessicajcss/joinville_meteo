#!/usr/bin/env python3
"""
build_station_history.py — per-station data for the "Histórico · estação" page
(Ireland-climate-dashboard layout), plus download-ready daily CSVs.

Writes:
  site/data/station_history.json
  site/data/stations/daily/<code>.csv   (copy of each daily master, for period-download)

Per station:
  meta   : code, name, type, lat, lon, elevation, resolution, period, n_days, vars, years
  wind   : monthly-climatology mean wind speed [12]  (for the wind-speed map)
  temp   : {year: {maxrec[12], minrec[12], maxmean[12], minmean[12]}}  (temperature-conditions plot)
  rain   : {year: [12]}  monthly totals  (historical-rainfall heatmap)
  coverage: {year: fraction of days with any data}
Everything is the station's OWN record (unblended).
"""
from __future__ import annotations
import glob, json, os, shutil, subprocess
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DAILY = ROOT / "data" / "daily"
REG = pd.read_csv(ROOT / "data" / "geo" / "stations_master.csv")
OUT = ROOT / "site" / "data"
DLDIR = OUT / "stations" / "daily"
DLDIR.mkdir(parents=True, exist_ok=True)

VAR_LABELS = {"temp": "Temperatura", "rain": "Chuva", "umid": "Umidade", "wind": "Vento"}
reg_by = {r["code"]: r for _, r in REG.iterrows()}
stations = []

for f in sorted(glob.glob(str(DAILY / "*.parquet"))):
    code = os.path.basename(f)[:-8]
    if code not in reg_by:
        continue
    r = reg_by[code]
    d = pd.read_parquet(f); d["date"] = pd.to_datetime(d["date"]); d = d.sort_values("date")
    d["y"] = d["date"].dt.year; d["mo"] = d["date"].dt.month
    for c in ("temp_max", "temp_min", "prec", "umid_mean", "ws_mean"):
        if c not in d: d[c] = np.nan

    any_data = d[["temp_max", "temp_min", "prec", "umid_mean"]].notna().any(axis=1)
    valid = d[any_data]
    if not len(valid):
        continue
    period = [str(valid["date"].min().date()), str(valid["date"].max().date())]

    # monthly wind climatology
    wsm = d.dropna(subset=["ws_mean"]).groupby("mo")["ws_mean"].mean()
    wind = [round(float(wsm[m]), 1) if m in wsm.index else None for m in range(1, 13)]

    # temperature conditions by year
    temp = {}
    for yr, g in d.groupby("y"):
        maxrec = [None]*12; minrec = [None]*12; maxmean = [None]*12; minmean = [None]*12
        for m, mg in g.groupby("mo"):
            if mg["temp_max"].notna().any():
                maxrec[m-1] = round(float(mg["temp_max"].max()), 1)
                maxmean[m-1] = round(float(mg["temp_max"].mean()), 1)
            if mg["temp_min"].notna().any():
                minrec[m-1] = round(float(mg["temp_min"].min()), 1)
                minmean[m-1] = round(float(mg["temp_min"].mean()), 1)
        if any(v is not None for v in maxrec + minrec):
            temp[int(yr)] = {"maxrec": maxrec, "minrec": minrec, "maxmean": maxmean, "minmean": minmean}

    # rainfall by year (monthly totals, >=15 valid days)
    rain = {}
    for yr, g in d.groupby("y"):
        arr = [None]*12
        for m, mg in g.groupby("mo"):
            if mg["prec"].notna().sum() >= 15:
                arr[m-1] = round(float(mg["prec"].sum()), 0)
        if any(v is not None for v in arr):
            rain[int(yr)] = arr

    cov = {int(y): round(float(g.sum())/365.0, 2) for y, g in any_data.groupby(d["y"])}
    years = sorted(set(temp) | set(rain) | {int(y) for y in cov})
    vars_present = [v for v, col in (("temp", "temp_max"), ("rain", "prec"),
                                     ("umid", "umid_mean"), ("wind", "ws_mean")) if d[col].notna().any()]

    stations.append({
        "code": code, "name": str(r["name"]), "type": r["type"],
        "resolution": (None if pd.isna(r.get("resolution")) else r.get("resolution")),
        "lat": float(r["lat"]), "lon": float(r["lon"]),
        "elevation": (None if pd.isna(r["elevation"]) else float(r["elevation"])),
        "period": period, "n_days": int(len(valid)), "vars": vars_present, "years": years,
        "wind": wind, "temp": temp, "rain": rain, "coverage": cov,
    })
    csv = DAILY / f"{code}.csv"
    if csv.exists():
        shutil.copy(csv, DLDIR / f"{code}.csv")

stations.sort(key=lambda s: s["name"])
all_years = sorted({y for s in stations for y in s["years"]})
stamp = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%MZ"], capture_output=True, text=True).stdout.strip()
(OUT / "station_history.json").write_text(
    json.dumps({"generated_at": stamp, "var_labels": VAR_LABELS, "all_years": all_years, "stations": stations},
               ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

# ---- per-station monthly wind roses (Estação page) -> station_windrose.json ----
# 16-sector x speed-class frequency per (station, year, month), from the hourly masters.
# Same QC as the network rose: drop stuck-vane stations (>25% of windy hours at exactly 0°),
# exclude calm winds and the exact-0 sentinel from the sectors.
HOURLY = ROOT / "data" / "hourly"
CALM_MS = 0.5; STUCK_FRAC = 0.25
ROSE_CLASSES = [(0, 2), (2, 4), (4, 6), (6, 8), (8, 999)]
def bin_rose(wd, ws):
    wd = np.asarray(wd, float); ws = np.asarray(ws, float)
    keep = np.isfinite(wd) & np.isfinite(ws) & (wd != 0.0)
    wd, ws = wd[keep], ws[keep]
    if len(wd) == 0:
        return None
    calm = ws < CALM_MS
    cp = round(float(np.mean(calm) * 100), 1)
    wdn, wsn = wd[~calm], ws[~calm]; n = len(wdn)
    freq = np.zeros((16, len(ROSE_CLASSES)))
    if n:
        sec = (np.floor(((wdn % 360) + 11.25) / 22.5).astype(int)) % 16
        for i in range(16):
            wsi = wsn[sec == i]
            for j, (lo, hi) in enumerate(ROSE_CLASSES):
                freq[i, j] = np.sum((wsi >= lo) & (wsi < hi))
        freq = freq / n * 100.0
    return {"freq": np.round(freq, 1).tolist(), "n": int(n), "calm": cp}

wr = {}
for f in sorted(glob.glob(str(HOURLY / "*.csv"))):
    code = os.path.basename(f)[:-4]
    if code not in reg_by:
        continue
    try:
        d = pd.read_csv(f, usecols=lambda c: c in ("date", "wd", "ws"))
    except Exception:
        continue
    if "wd" not in d.columns or "ws" not in d.columns:
        continue
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date", "wd", "ws"])
    if d.empty:
        continue
    windy = d["ws"].to_numpy() >= CALM_MS
    if windy.sum() >= 100 and float(np.mean(d["wd"].to_numpy()[windy] == 0.0)) > STUCK_FRAC:
        continue
    d["y"] = d["date"].dt.year; d["mo"] = d["date"].dt.month
    st = {}
    for (y, mo), g in d.groupby(["y", "mo"]):
        r = bin_rose(g["wd"].values, g["ws"].values)
        if r and r["n"] >= 1:
            st.setdefault(str(int(y)), {})[str(int(mo))] = r
    if st:
        wr[code] = st
(OUT / "station_windrose.json").write_text(json.dumps(
    {"generated_at": stamp, "calm_ms": CALM_MS, "dirs": 16, "class_edges": ROSE_CLASSES,
     "stations": wr}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"windrose stations: {sorted(wr)} | roses: {sum(len(m) for s in wr.values() for m in s.values())}")

print(f"stations: {len(stations)} | years {all_years[0]}–{all_years[-1]}")
for s in stations:
    print(f"  {s['code']:12s} {s['period'][0]}..{s['period'][1]} wind={'y' if any(s['wind']) else '-'} "
          f"temp_years={len(s['temp'])} rain_years={len(s['rain'])}")
