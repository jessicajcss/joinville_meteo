#!/usr/bin/env python3
"""
Headless CPTEC-WRF fetch for the dashboard auto-update — the script form of
notebooks/CPTEC_WRF_Joinville_downloader.ipynb (rain + temperature + wind).

Auto-detects the most recent available CPTEC/INPE WRF (AMS 7 km) run, downloads the
requested leads, and writes a clean hourly NetCDF over the Joinville box:
  precip_mm_h (de-accumulated hourly)  ·  t2m_degC (instantaneous)  ·  u10_ms/v10_ms/wspd10_ms/wdir10_deg (instantaneous)

Runs in GitHub Actions (needs internet + cfgrib/eccodes). NOT for the Cowork sandbox.
The scheduled workflow then feeds the .nc to build_wrf_basins.py.

  python scripts/fetch_wrf.py --out site/data/wrf_joinville_latest.nc
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# same box + convention as the notebook (verification domain; build_wrf_basins.py crops it)
LAT_MIN, LAT_MAX = -28.61, -24.00
LON_MIN, LON_MAX = -51.41, -46.28
BASE_URL = "https://dataserver.cptec.inpe.br/dataserver_modelos/wrf/ams_07km/brutos"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120 Safari/537.36"}
RAIN_VARS = ["tp", "acpcp", "ncpcp"]
WIND = {"u10": ["u10", "10u"], "v10": ["v10", "10v"]}


def build_url(run_dt, fcast_dt):
    r = run_dt.strftime("%Y%m%d%H"); f = fcast_dt.strftime("%Y%m%d%H")
    y, m, d, h = run_dt.strftime("%Y"), run_dt.strftime("%m"), run_dt.strftime("%d"), run_dt.strftime("%H")
    return f"{BASE_URL}/{y}/{m}/{d}/{h}/WRF_cpt_07KM_{r}_{f}.grib2"


def find_latest_run(sess, fhs, max_back_hours=72):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    anchor = now.replace(hour=(12 if now.hour >= 12 else 0))
    probe = min(fhs[-1], 12)   # confirm the run is posted; longer leads may still be uploading (skipped gracefully)
    for k in range(max_back_hours // 12 + 1):
        cand = anchor - timedelta(hours=12 * k)
        url = build_url(cand, cand + timedelta(hours=probe))
        try:
            r = sess.get(url, stream=True, timeout=40, headers={"Range": "bytes=0-1"})
            ok = r.status_code in (200, 206); r.close()
            if ok:
                return cand
        except Exception:
            pass
    return None


def _norm(ds):
    lon = ds.longitude
    if float(lon.max()) > 180:
        ds = ds.assign_coords(longitude=(((lon + 180) % 360) - 180)).sortby("longitude")
    ds = ds.sortby("latitude")
    return ds.sel(latitude=slice(LAT_MIN, LAT_MAX), longitude=slice(LON_MIN, LON_MAX))


def open_joinville(path):
    import cfgrib
    dss = cfgrib.open_datasets(str(path))
    rain = temp = None; wind = {}; tp_attrs = None
    for d in dss:
        if rain is None and any(v in d.data_vars for v in RAIN_VARS):
            rain = _norm(d[[v for v in RAIN_VARS if v in d.data_vars]])
        if temp is None:
            if "t2m" in d.data_vars: temp = _norm(d[["t2m"]])
            elif "2t" in d.data_vars: temp = _norm(d[["2t"]].rename({"2t": "t2m"}))
            elif "t" in d.data_vars and "heightAboveGround" in d["t"].coords \
                 and float(np.atleast_1d(d["t"].heightAboveGround.values)[0]) == 2.0:
                temp = _norm(d[["t"]].rename({"t": "t2m"}))
        for canon, names in WIND.items():
            if canon in wind: continue
            for nm in names:
                if nm in d.data_vars:
                    wind[canon] = _norm(d[[nm]].rename({nm: canon})); break
    if rain is None:
        for d in dss:
            try: d.close()
            except Exception: pass
        return None, None
    if "tp" in rain:
        tp_attrs = {k: v for k, v in rain["tp"].attrs.items() if "step" in k.lower() or "Grib" in k}
    parts = [rain[v].reset_coords(drop=True).rename(v) for v in rain.data_vars]
    if temp is not None:
        parts.append(temp["t2m"].reset_coords(drop=True).reindex_like(rain, method="nearest").rename("t2m"))
    for canon in ("u10", "v10"):
        if canon in wind:
            parts.append(wind[canon][canon].reset_coords(drop=True).reindex_like(rain, method="nearest").rename(canon))
    import xarray as xr
    merged = xr.merge(parts).load()          # read into memory so the source GRIB can be deleted immediately
    for d in dss:
        try: d.close()
        except Exception: pass
    return merged, tp_attrs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data/wrf_joinville_latest.nc")
    ap.add_argument("--leads", default="0,72", help="first,last forecast hour (default: next 72 h / 3 days)")
    ap.add_argument("--tmp", default="/tmp/cptec_wrf")
    a = ap.parse_args()
    import requests, xarray as xr
    lo, hi = (int(x) for x in a.leads.split(","))
    fhs = list(range(lo, hi + 1))
    tmp = Path(a.tmp); tmp.mkdir(parents=True, exist_ok=True)

    sess = requests.Session(); sess.headers.update(HEADERS)
    run_dt = find_latest_run(sess, fhs)
    if run_dt is None:
        print("[fetch_wrf] no available CPTEC run found in the last 72 h", file=sys.stderr)
        return 2
    print(f"[fetch_wrf] latest available run: {run_dt:%Y-%m-%d %H}Z")

    # download → extract → delete, one lead at a time, so peak disk stays ~one GRIB
    # even for the 72-hour (3-day) window (files can be tens of MB over the full AMS domain)
    per_fh, grib_attrs = [], None
    for fh in fhs:
        url = build_url(run_dt, run_dt + timedelta(hours=fh))
        dest = tmp / Path(url).name
        try:
            r = sess.get(url, stream=True, timeout=180)
            if r.status_code != 200:
                r.close(); continue
            with open(dest, "wb") as f:
                for ch in r.iter_content(1 << 16): f.write(ch)
            r.close()
            if dest.stat().st_size <= 1e5:
                continue
            ds, tp_attrs = open_joinville(dest)
            if ds is not None:
                if grib_attrs is None and tp_attrs: grib_attrs = tp_attrs
                per_fh.append(ds.expand_dims(forecast_hour=[fh]))
        except Exception as e:
            print(f"[fetch_wrf] +{fh}h err: {e}", file=sys.stderr)
        finally:
            for p in tmp.glob(dest.name + "*"):     # remove the GRIB and any cfgrib .idx sidecar
                try: p.unlink()
                except Exception: pass
    if not per_fh:
        print("[fetch_wrf] nothing downloaded/extracted (retention/access?)", file=sys.stderr)
        return 3
    print(f"[fetch_wrf] {len(per_fh)} lead files extracted")
    common = set(per_fh[0].data_vars)
    for ds in per_fh[1:]: common &= set(ds.data_vars)
    per_fh = [ds[list(common)] for ds in per_fh]
    wrf = xr.concat(per_fh, dim="forecast_hour").sortby("forecast_hour")
    wrf = wrf.assign_coords(valid_time=("forecast_hour",
          [run_dt + timedelta(hours=int(h)) for h in wrf.forecast_hour.values]))

    # rain: de-accumulate from-init (verified for CPTEC AMS 7km); temp/wind: instantaneous
    dom = wrf["tp"].mean(("latitude", "longitude")).values
    step_range = (grib_attrs or {}).get("GRIB_stepRange", "?")
    from_init = bool(np.all(np.diff(dom) >= -1e-6)) or (isinstance(step_range, str) and step_range.strip().startswith("0"))
    if from_init:
        tph = wrf["tp"].diff("forecast_hour").clip(min=0)
        wrf_h = wrf.isel(forecast_hour=slice(1, None)).copy(); wrf_h["precip_mm_h"] = tph
    else:
        wrf_h = wrf.copy(); wrf_h["precip_mm_h"] = wrf["tp"]
    wrf_h["precip_mm_h"].attrs.update(units="mm h-1")
    if "t2m" in wrf_h:
        tK = wrf_h["t2m"]
        wrf_h["t2m_degC"] = (tK - 273.15) if float(np.nanmedian(tK.values)) > 100 else tK
        wrf_h["t2m_degC"].attrs.update(units="degC")
    if "u10" in wrf_h and "v10" in wrf_h:
        u, v = wrf_h["u10"], wrf_h["v10"]
        wrf_h["u10_ms"] = u; wrf_h["v10_ms"] = v
        wrf_h["wspd10_ms"] = np.hypot(u, v)
        wrf_h["wdir10_deg"] = (270.0 - np.degrees(np.arctan2(v, u))) % 360.0

    keep = [v for v in ["precip_mm_h", "t2m_degC", "wspd10_ms", "wdir10_deg", "u10_ms", "v10_ms"] if v in wrf_h]
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    ds_out = wrf_h[keep].copy()
    ds_out.attrs.update(source="CPTEC/INPE WRF AMS 7km", run_time=str(run_dt),
                        domain=f"Joinville (lat {LAT_MIN}..{LAT_MAX}, lon {LON_MIN}..{LON_MAX})")
    ds_out.to_netcdf(out)
    print(f"[fetch_wrf] wrote {out} · vars {keep} · run {run_dt:%Y-%m-%d %H}Z")
    return 0


if __name__ == "__main__":
    sys.exit(main())
