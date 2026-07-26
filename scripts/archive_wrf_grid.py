#!/usr/bin/env python3
"""
Accumulate every WRF run's per-cell forecast into ONE growing long-format CSV, so the full
history of the model output over Joinville can be retrieved later (the per-run files
wrf_forecast.json / wrf_grid.geojson are OVERWRITTEN each day — this archive is what persists).

What it stores — the native ~7 km grid over the Joinville window (the same local grid the
Previsão map draws, ~10×10 cells), HOURLY, one row per (run, valid time, cell):

  run_time, valid_time, lead_h, i, j, lat, lon,
  rain_mm_h, temp_degC, u10_ms, v10_ms, wind_ms, wind_dir_deg

- Times are LOCAL (UTC−3), matching the rest of the dashboard; `run_time` is the model cycle
  (UTC label, 00Z/12Z). `i,j` and `lat,lon` are the grid geometry at original resolution.
- **Append-only + idempotent:** rows are keyed by (run_time, valid_time, i, j). Re-running on the
  same forecast adds nothing; a new run appends its ~900 rows. Plain CSV so git stores each day as
  a small append delta.
- Size: ~900 rows/run ≈ 0.33 M rows/year ≈ ~25 MB/year. If it ever nears GitHub's 100 MB/file
  limit, switch to a yearly file (see YEARLY note) — the reader in build_* doesn't depend on it.

Only the local Joinville window is archived (not the full CPTEC box) to keep the file tractable;
the full-box field for any single run is still in that run's wrf_grid.geojson.

Usage:  python scripts/archive_wrf_grid.py [--forecast site/data/wrf_forecast.json]
                                           [--out site/data/wrf_grid_archive.csv]
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
COLS = ["run_time", "valid_time", "lead_h", "i", "j", "lat", "lon",
        "rain_mm_h", "temp_degC", "u10_ms", "v10_ms", "wind_ms", "wind_dir_deg"]


def wdir_from_uv(u, v):
    return round(float((270.0 - np.degrees(np.arctan2(v, u))) % 360.0)) if (u is not None and v is not None) else ""


def rows_from_forecast(doc):
    lat = doc["lat"]; lon = doc["lon"]
    vt = doc["valid_times"]; lead = doc["lead_h"]; run = doc.get("run_time", "")
    V = doc["vars"]
    rain = V.get("rain", {}).get("grid_hourly")
    temp = V.get("temp", {}).get("grid_hourly")
    u = V.get("wind", {}).get("u_hourly"); v = V.get("wind", {}).get("v_hourly")
    spd = V.get("wind", {}).get("spd_hourly")
    T = doc["n_steps"]
    for t in range(T):
        for i in range(len(lat)):
            for j in range(len(lon)):
                uu = u[t][i][j] if u else None
                vv = v[t][i][j] if v else None
                yield {
                    "run_time": run, "valid_time": vt[t], "lead_h": lead[t],
                    "i": i, "j": j, "lat": round(float(lat[i]), 4), "lon": round(float(lon[j]), 4),
                    "rain_mm_h": (round(float(rain[t][i][j]), 2) if rain else ""),
                    "temp_degC": (round(float(temp[t][i][j]), 1) if temp else ""),
                    "u10_ms": (round(float(uu), 2) if u else ""),
                    "v10_ms": (round(float(vv), 2) if v else ""),
                    "wind_ms": (round(float(spd[t][i][j]), 2) if spd else ""),
                    "wind_dir_deg": wdir_from_uv(uu, vv) if u else "",
                }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forecast", default=str(ROOT / "site" / "data" / "wrf_forecast.json"))
    ap.add_argument("--out", default=str(ROOT / "site" / "data" / "wrf_grid_archive.csv"))
    a = ap.parse_args()
    fc = Path(a.forecast); out = Path(a.out)
    if not fc.exists():
        print(f"[archive] no forecast at {fc} — nothing to archive")
        return
    doc = json.loads(fc.read_text(encoding="utf-8"))

    # existing keys (run_time, valid_time, i, j) so re-runs never duplicate
    seen = set()
    n_existing = 0
    if out.exists():
        with out.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                seen.add((r["run_time"], r["valid_time"], r["i"], r["j"]))
                n_existing += 1

    new = [r for r in rows_from_forecast(doc)
           if (r["run_time"], r["valid_time"], str(r["i"]), str(r["j"])) not in seen]
    if not new:
        print(f"[archive] run {doc.get('run_time')} already archived ({n_existing} rows) — no change")
        return

    write_header = not out.exists()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        if write_header:
            w.writeheader()
        w.writerows(new)
    print(f"[archive] appended {len(new)} rows for run {doc.get('run_time')} "
          f"→ {out} (total {n_existing + len(new)} rows)")


if __name__ == "__main__":
    main()
