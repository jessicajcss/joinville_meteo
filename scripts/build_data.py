#!/usr/bin/env python3
"""
Joinville meteorological dashboard - DATA PIPELINE
==================================================
Reads the raw station CSVs + rain-gauge CSV + station coordinates + GIS layers,
runs quality control, aggregates to compact daily / recent series, flags extreme
rainfall events, and writes small dashboard-ready files into data/processed/.

The dashboard (dashboard/index.qmd) only ever reads data/processed/, so the
browser never loads the big raw files. This script is what the GitHub Action runs
every time new data is pushed.

Run from the repo root:  python scripts/build_data.py
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
GEO = ROOT / "data" / "geo"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

TZ = "America/Sao_Paulo"                 # Joinville local time
RECENT_DAYS = 90                         # window kept at hourly resolution
VAR_COLS = ["temp", "umid", "ws", "wd", "prec"]

# Daily-rainfall alert thresholds (mm/day). Tune to Defesa Civil de Joinville
# criteria — these are sensible starting values for subtropical SC.
RAIN_ALERTS = [(100, "critical"), (60, "serious"), (30, "warning")]


def rain_level(mm: float) -> str:
    if mm is None or pd.isna(mm):
        return "good"
    for thr, lvl in RAIN_ALERTS:
        if mm >= thr:
            return lvl
    return "good"


def log(msg: str) -> None:
    print(f"[build_data] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# 1. Station metadata
# --------------------------------------------------------------------------- #
meta = pd.read_excel(RAW / "stations.xlsx")
meta.columns = [c.strip() for c in meta.columns]
log(f"{len(meta)} stations in metadata")

daily_frames, recent_frames, latest_rows, events = [], [], [], []

for _, m in meta.iterrows():
    code = str(m["code"]).strip()
    f = RAW / f"{code}_raw.csv"
    if not f.exists():
        log(f"  - {code}: no raw file, skipped")
        continue
    try:
        df = pd.read_csv(f)
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(TZ)
        df = df.dropna(subset=["date"]).set_index("date").sort_index()

        # ---- quality control: clamp physically impossible values to NaN ----
        if "temp" in df:
            df.loc[(df["temp"] < -10) | (df["temp"] > 50), "temp"] = np.nan
        if "umid" in df:
            df.loc[(df["umid"] < 0) | (df["umid"] > 100), "umid"] = np.nan
        if "prec" in df:
            df.loc[df["prec"] < 0, "prec"] = np.nan
        if "ws" in df:
            df.loc[df["ws"] < 0, "ws"] = np.nan

        have = [c for c in VAR_COLS if c in df.columns]

        # ---- daily aggregation ----
        agg = {}
        if "temp" in df: agg["temp"] = ["mean", "min", "max"]
        if "umid" in df: agg["umid"] = ["mean"]
        if "ws" in df:   agg["ws"] = ["mean", "max"]
        if "prec" in df: agg["prec"] = ["sum"]
        d = df.resample("1D").agg(agg)
        d.columns = ["_".join(c).rstrip("_") for c in d.columns.to_flat_index()]
        d.insert(0, "code", code)
        d.insert(1, "station", m["Station"])
        dd = d.reset_index()
        dd["date"] = pd.to_datetime(dd["date"]).dt.tz_localize(None)   # naive local -> clean CSV
        daily_frames.append(dd)

        # ---- recent window at hourly resolution ----
        cutoff = df.index.max() - pd.Timedelta(days=RECENT_DAYS)
        rec = df.loc[df.index >= cutoff]
        how = {c: ("sum" if c == "prec" else "mean") for c in have}
        r = rec.resample("1h").agg(how)
        r.insert(0, "code", code)
        r.insert(1, "station", m["Station"])
        rr = r.reset_index()
        rr["date"] = pd.to_datetime(rr["date"]).dt.tz_localize(None)   # naive local -> clean CSV
        recent_frames.append(rr)

        # ---- latest snapshot (most recent non-empty observation) ----
        nonempty = df.dropna(how="all", subset=have)
        last = nonempty.iloc[-1] if len(nonempty) else None
        row = {
            "code": code, "station": m["Station"],
            "lon": float(m["Longitude"]), "lat": float(m["Latitude"]),
            "elevation": float(m["Elevation"]),
            "last_time": (df.index.max().isoformat() if len(df) else None),
            "n_obs": int(len(df)),
            "start": (df.index.min().isoformat() if len(df) else None),
        }
        for c in have:
            v = None if last is None else last.get(c)
            row[c] = None if (v is None or pd.isna(v)) else round(float(v), 2)
        # 24h rainfall for the alert badge
        if "prec" in df:
            last_day = df["prec"].loc[df.index >= (df.index.max() - pd.Timedelta(hours=24))].sum()
            row["rain_24h"] = round(float(last_day), 1)
            row["alert"] = rain_level(last_day)
        else:
            row["rain_24h"] = None
            row["alert"] = "good"
        latest_rows.append(row)

        # ---- extreme rainfall events (daily) ----
        if "prec_sum" in d.columns:
            for dt, mm in d["prec_sum"].dropna().items():
                if mm >= RAIN_ALERTS[-1][0]:      # >= lowest alert threshold
                    events.append({
                        "code": code, "station": m["Station"],
                        "date": dt.date().isoformat(),
                        "rain_mm": round(float(mm), 1),
                        "level": rain_level(mm),
                    })
        log(f"  - {code}: {len(df):,} rows | vars={have} | {row['start'][:10]}..{row['last_time'][:10]}")
    except Exception as e:                                # noqa: BLE001
        log(f"  ! {code}: FAILED ({e})")

# --------------------------------------------------------------------------- #
# 2. Write station series
# --------------------------------------------------------------------------- #
daily = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
recent = pd.concat(recent_frames, ignore_index=True) if recent_frames else pd.DataFrame()
daily.to_csv(OUT / "daily.csv", index=False)
recent.to_csv(OUT / "recent.csv", index=False)
with open(OUT / "latest.json", "w", encoding="utf-8") as fh:
    json.dump(latest_rows, fh, ensure_ascii=False, indent=2)

events_df = pd.DataFrame(events).sort_values(["date", "rain_mm"], ascending=[False, False]) \
    if events else pd.DataFrame(columns=["code", "station", "date", "rain_mm", "level"])
events_df.to_csv(OUT / "events.csv", index=False)
log(f"stations: daily={len(daily):,} rows, recent={len(recent):,} rows, events={len(events_df)}")

# --------------------------------------------------------------------------- #
# 3. Rain gauges (pluviometros_raw.csv, wide -> long daily)
# --------------------------------------------------------------------------- #
pluvio_daily = pd.DataFrame()
pluvio_latest = []
pg = RAW / "pluviometros_raw.csv"
if pg.exists():
    try:
        pv = pd.read_csv(pg)
        pv["date"] = pd.to_datetime(pv["date"], utc=True, errors="coerce").dt.tz_convert(TZ)
        pv = pv.dropna(subset=["date"]).set_index("date").sort_index()
        # keep the lowercase (deduplicated) gauge columns; drop the Capitalized dupes
        gauges = [c for c in pv.columns if c == c.lower() and c != "date"]
        pv = pv[gauges].apply(pd.to_numeric, errors="coerce")
        pv[pv < 0] = np.nan
        dd = pv.resample("1D").sum(min_count=1)
        longd = dd.reset_index().melt(id_vars="date", var_name="gauge", value_name="rain_mm").dropna()
        longd["date"] = longd["date"].dt.date.astype(str)
        pluvio_daily = longd
        pluvio_daily.to_csv(OUT / "pluvio_daily.csv", index=False)

        # gauge coordinates from stations_pluv_ID.xlsx
        try:
            gmeta = pd.read_excel(RAW / "stations_pluv_ID.xlsx")
            gmeta.columns = [c.strip() for c in gmeta.columns]
            coords = {str(r["code"]).strip(): (float(r["Longitude"]), float(r["Latitude"]),
                                               str(r["Station"])) for _, r in gmeta.iterrows()}
        except Exception:
            coords = {}
        for g in gauges:
            lon, lat, name = coords.get(g, (None, None, g))
            s = pv[g].dropna()
            if len(s):
                last_valid = s.index.max()
                total90 = float(pv.loc[pv.index >= last_valid - pd.Timedelta(days=90), g].sum())
                last24 = float(pv.loc[pv.index >= last_valid - pd.Timedelta(hours=24), g].sum())
                span_years = max((s.index.max() - s.index.min()).days / 365.25, 1e-9)
                annual = float(s.sum() / span_years)
            else:
                last_valid, total90, last24, annual = None, 0.0, 0.0, 0.0
            pluvio_latest.append({
                "gauge": g, "name": name, "lon": lon, "lat": lat,
                "rain_90d": round(total90, 1), "rain_24h": round(last24, 1),
                "rain_annual": round(annual, 0), "alert": rain_level(last24),
                "last_time": last_valid.isoformat() if last_valid is not None else None,
            })
        with open(OUT / "pluvio_latest.json", "w", encoding="utf-8") as fh:
            json.dump(pluvio_latest, fh, ensure_ascii=False, indent=2)
        log(f"gauges: {len(gauges)} gauges, {len(pluvio_daily):,} daily rows")
    except Exception as e:                                # noqa: BLE001
        log(f"! pluviometros FAILED ({e})")

# --------------------------------------------------------------------------- #
# 4. GIS layers -> simplified GeoJSON in EPSG:4326
# --------------------------------------------------------------------------- #
def export_geo(name: str, simplify: float = 0.0005) -> None:
    shp = GEO / f"{name}.shp"
    if not shp.exists():
        log(f"  geo: {name}.shp missing, skipped")
        return
    g = gpd.read_file(shp).to_crs(4326)
    if simplify:
        g["geometry"] = g["geometry"].simplify(simplify, preserve_topology=True)
    g.to_file(OUT / f"{name}.geojson", driver="GeoJSON")
    log(f"  geo: {name} -> {len(g)} feature(s)")

export_geo("joinville_limite", simplify=0.0004)
export_geo("BAIRROS", simplify=0.0004)
export_geo("bacias_joinville", simplify=0.0004)

# --------------------------------------------------------------------------- #
# 5. City-wide summary / KPIs
# --------------------------------------------------------------------------- #
reporting = [r for r in latest_rows if r.get("temp") is not None]
temps = [r["temp"] for r in latest_rows if r.get("temp") is not None]
hums = [r["umid"] for r in latest_rows if r.get("umid") is not None]
winds = [r["ws"] for r in latest_rows if r.get("ws") is not None]
rain24 = [r["rain_24h"] for r in latest_rows if r.get("rain_24h") is not None]
gauge24 = [g["rain_24h"] for g in pluvio_latest if g.get("rain_24h") is not None]
max_rain_station = max(latest_rows, key=lambda r: (r.get("rain_24h") or -1), default=None)

summary = {
    "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
    "city": "Joinville - SC",
    "n_stations": len(meta),
    "n_reporting": len(reporting),
    "n_gauges": len(pluvio_latest),
    "temp_mean": round(float(np.mean(temps)), 1) if temps else None,
    "temp_min": round(float(np.min(temps)), 1) if temps else None,
    "temp_max": round(float(np.max(temps)), 1) if temps else None,
    "humidity_mean": round(float(np.mean(hums)), 0) if hums else None,
    "wind_max": round(float(np.max(winds)), 1) if winds else None,
    "rain_24h_max": round(float(np.max(rain24 + gauge24)), 1) if (rain24 or gauge24) else 0.0,
    "rain_24h_where": (max_rain_station["station"] if max_rain_station else None),
    "n_events": int(len(events_df)),
    "worst_alert": (max([r["alert"] for r in latest_rows] + [g["alert"] for g in pluvio_latest],
                        key=lambda a: ["good", "warning", "serious", "critical"].index(a))
                    if (latest_rows or pluvio_latest) else "good"),
}
with open(OUT / "summary.json", "w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=2)
log(f"summary: {json.dumps(summary, ensure_ascii=False)}")
log("DONE")
