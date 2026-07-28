#!/usr/bin/env python3
"""
Accumulate every WRF run's per-cell forecast into a LONG-FORMAT archive, chunked by YEAR, so the
full history of the model output over Joinville can be retrieved later (the per-run files
wrf_forecast.json / wrf_grid.geojson are OVERWRITTEN each day — this archive is what persists).

Layout (site/data/wrf_archive/):
  grade_YYYY.csv        one plain-CSV file per calendar year of valid_time_local (universally openable)
  grade_YYYY.csv.gz     the same file gzip-compressed (~5–10× smaller; opens in pandas/R directly)
  index.json            manifest: which years exist, their date ranges, row counts and byte sizes

Each row is one (run, valid time, grid cell):
  run_time_utc, valid_time_local, lead_h, i, j, lat, lon,
  rain_mm_h, temp_degC, u10_ms, v10_ms, wind_ms, wind_dir_deg

Why chunk by year:
- **No 100 MB wall.** A single growing CSV would hit GitHub's per-file limit (~25 MB/year → ~4 yr).
  Per-year files stay small and each closed year is immutable.
- **No git-history bloat.** Only the CURRENT year's file is ever rewritten; past years never change,
  so git does not re-store the whole archive on every run.
- **Chunked download & preservation.** Users can pull just the year(s) they need, and each frozen
  yearly file is independently archivable (e.g. deposited to Zenodo for a citable DOI).

Guarantees (data must remain fully available):
- **Non-destructive migration.** A pre-existing single-file archive (site/data/wrf_grid_archive.csv,
  old or tz-explicit headers) is folded into the yearly files ONCE, row for row, and then left in
  place untouched as a frozen backup. No row is ever dropped.
- **Append-only + idempotent.** Rows are keyed by (run_time_utc, valid_time_local, i, j); re-running
  on the same forecast changes nothing. Files are written deterministically (sorted rows, gzip
  mtime=0) so an unchanged year produces byte-identical output — git sees no diff.

Usage:  python scripts/archive_wrf_grid.py
        [--forecast site/data/wrf_forecast.json] [--archive-dir site/data/wrf_archive]
        [--legacy site/data/wrf_grid_archive.csv]
"""
from __future__ import annotations
import argparse
import csv
import gzip
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
COLS = ["run_time_utc", "valid_time_local", "lead_h", "i", "j", "lat", "lon",
        "rain_mm_h", "temp_degC", "u10_ms", "v10_ms", "wind_ms", "wind_dir_deg"]


def _norm(r):
    """Accept a pre-rename archive row (run_time / valid_time) and map it to the
    tz-explicit names (run_time_utc = model cycle in UTC; valid_time_local = UTC-3)."""
    if "run_time" in r and "run_time_utc" not in r:
        r["run_time_utc"] = r.pop("run_time")
    if "valid_time" in r and "valid_time_local" not in r:
        r["valid_time_local"] = r.pop("valid_time")
    return r


def _key(r):
    """Dedup key: one row per (run cycle, valid instant, grid cell). Strings so a CSV-read
    row and a freshly-built row compare equal."""
    return (str(r.get("run_time_utc", "")), str(r.get("valid_time_local", "")),
            str(r.get("i", "")), str(r.get("j", "")))


def _year(r):
    """Chunk key = calendar year of the LOCAL valid time (e.g. '2026'). Rows whose valid time
    isn't a normal date fall into 'undated' so nothing is ever silently lost."""
    t = str(r.get("valid_time_local", ""))
    return t[:4] if t[:4].isdigit() else "undated"


def _sort_key(r):
    def _int(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return 0
    return (str(r.get("run_time_utc", "")), str(r.get("valid_time_local", "")),
            _int(r.get("i")), _int(r.get("j")))


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
                    "run_time_utc": run, "valid_time_local": vt[t], "lead_h": lead[t],
                    "i": i, "j": j, "lat": round(float(lat[i]), 4), "lon": round(float(lon[j]), 4),
                    "rain_mm_h": (round(float(rain[t][i][j]), 2) if rain else ""),
                    "temp_degC": (round(float(temp[t][i][j]), 1) if temp else ""),
                    "u10_ms": (round(float(uu), 2) if u else ""),
                    "v10_ms": (round(float(vv), 2) if v else ""),
                    "wind_ms": (round(float(spd[t][i][j]), 2) if spd else ""),
                    "wind_dir_deg": wdir_from_uv(uu, vv) if u else "",
                }


def _read_csv(path: Path):
    """Read a CSV archive file (plain or tz-explicit header) into normalized row dicts."""
    if not path.exists():
        return []
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append(_norm(dict(r)))
    return out


def _csv_bytes(rows):
    """Deterministic CSV bytes for a set of rows (sorted; fixed column order)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, extrasaction="ignore")
    w.writeheader()
    for r in sorted(rows, key=_sort_key):
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def _dedup(*sources):
    """Merge row iterables, keeping the first occurrence of each dedup key."""
    seen = set(); rows = []
    for src in sources:
        for r in src:
            k = _key(r)
            if k in seen:
                continue
            seen.add(k); rows.append(r)
    return rows


def _year_stats(year, rows, csv_path, gz_path):
    vts = sorted(str(r.get("valid_time_local", "")) for r in rows if r.get("valid_time_local"))
    return {"year": year, "csv": csv_path.name, "gz": gz_path.name, "rows": len(rows),
            "first": vts[0] if vts else "", "last": vts[-1] if vts else "",
            "bytes_csv": csv_path.stat().st_size if csv_path.exists() else 0,
            "bytes_gz": gz_path.stat().st_size if gz_path.exists() else 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--forecast", default=str(ROOT / "site" / "data" / "wrf_forecast.json"))
    ap.add_argument("--archive-dir", default=str(ROOT / "site" / "data" / "wrf_archive"))
    ap.add_argument("--legacy", default=str(ROOT / "site" / "data" / "wrf_grid_archive.csv"))
    a = ap.parse_args()
    fc = Path(a.forecast); adir = Path(a.archive_dir); legacy = Path(a.legacy)
    adir.mkdir(parents=True, exist_ok=True)
    idx_path = adir / "index.json"

    # existing manifest (carries per-year stats for years we won't touch this run)
    manifest = {}
    if idx_path.exists():
        try:
            manifest = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    years_meta = {e["year"]: e for e in manifest.get("years", [])}
    legacy_migrated = bool(manifest.get("legacy_migrated"))

    # new rows from this run's forecast (if any)
    new_rows = []
    if fc.exists():
        try:
            doc = json.loads(fc.read_text(encoding="utf-8"))
            new_rows = list(rows_from_forecast(doc))
        except Exception as e:
            print(f"[archive] could not read forecast {fc}: {e}")
    else:
        print(f"[archive] no forecast at {fc} — only migration/manifest maintenance")

    # one-time, non-destructive fold-in of any pre-existing single-file archive
    legacy_by_year = {}
    do_migrate = legacy.exists() and not legacy_migrated
    if do_migrate:
        for r in _read_csv(legacy):
            legacy_by_year.setdefault(_year(r), []).append(r)
        print(f"[archive] migrating legacy {legacy.name}: "
              f"{sum(len(v) for v in legacy_by_year.values())} rows across {sorted(legacy_by_year)}")

    years_new = {}
    for r in new_rows:
        years_new.setdefault(_year(r), []).append(r)

    years_to_process = set(years_new) | set(legacy_by_year)
    changed = []
    for year in sorted(years_to_process):
        cpath = adir / f"grade_{year}.csv"
        gpath = adir / f"grade_{year}.csv.gz"
        rows = _dedup(_read_csv(cpath), legacy_by_year.get(year, []), years_new.get(year, []))
        data = _csv_bytes(rows)
        old = cpath.read_bytes() if cpath.exists() else None
        if data != old:
            cpath.write_bytes(data)
            gpath.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))  # mtime=0 → reproducible
            changed.append(year)
        years_meta[year] = _year_stats(year, rows, cpath, gpath)

    # discover any year files not yet in the manifest (e.g. first run over a pre-seeded dir)
    for cpath in sorted(adir.glob("grade_*.csv")):
        year = cpath.stem.split("_", 1)[1]
        if year not in years_meta:
            rows = _read_csv(cpath)
            years_meta[year] = _year_stats(year, rows, cpath, adir / f"grade_{year}.csv.gz")

    years_sorted = [years_meta[y] for y in sorted(years_meta)]
    total_rows = sum(e["rows"] for e in years_sorted)
    core = {"columns": COLS, "legacy_migrated": legacy_migrated or do_migrate,
            "years": years_sorted, "total_rows": total_rows,
            "unit_note": "rain_mm_h mm/h; temp_degC °C; u10/v10/wind_ms m/s; wind_dir_deg deg (from).",
            "tz_note": "valid_time_local = Joinville local (UTC-3); run_time_utc = model cycle in UTC."}
    # rewrite the manifest only when its data content changed (keeps 'no-op' runs a true no-op)
    prev_core = {k: manifest.get(k) for k in core} if manifest else None
    if prev_core != core:
        out = dict(core); out["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        idx_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[archive] {total_rows} rows across {len(years_sorted)} year(s); "
              f"rewrote {changed or 'no'} year file(s); manifest updated → {idx_path}")
    else:
        print(f"[archive] {total_rows} rows across {len(years_sorted)} year(s) — no change")


if __name__ == "__main__":
    main()
