#!/usr/bin/env python3
"""
Area-weight a WRF hourly NetCDF onto Joinville's hydrological basins AND neighbourhoods
(bairros) — rainfall, temperature and wind — and emit gridded outputs.

Input : wrf_joinville_*.nc (from notebooks/CPTEC_WRF_Joinville_downloader.ipynb) with
        precip_mm_h[forecast_hour,lat,lon] (required) + optional t2m_degC, u10_ms/v10_ms.
        + site/data/bacias.geojson, bairros.geojson, limite.geojson.

Method: each WRF cell -> footprint polygon; cells and target polygons projected to an
        EQUAL-AREA CRS (EPSG:31982) and intersected exactly; a polygon's value each hour is
        the area-weighted mean of the cells it overlaps. Rain accumulates; temperature is a
        mean; wind is vector-averaged (u,v -> speed/direction). Uniform field -> identical
        value everywhere (invariant, tested). NOTE: WRF is ~7 km, coarser than a neighbourhood,
        so bairros within one cell share the same value — a documented resolution limit.

Output (site/data/):
  wrf_basins.csv / wrf_basins.geojson         per-basin summary
  wrf_bairros.csv / wrf_bairros.geojson       per-neighbourhood summary
  wrf_grid.geojson                            WRF cells (full box) as a grid with per-cell forecast
  wrf_basins_hourly.csv                       tidy per-basin hourly series
  wrf_forecast.json                           local grid + regional (full-box) grid + basins + bairros
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
from shapely.geometry import box as shp_box

ROOT = Path(__file__).resolve().parents[1]
EQ_AREA = "EPSG:31982"
MARGIN_DEG = 0.06


def cell_edges(c):
    c = np.asarray(c, float)
    if c.size == 1:
        return np.array([c[0] - 0.05, c[0] + 0.05])
    mid = (c[:-1] + c[1:]) / 2.0
    return np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])


def r1(x):
    v = round(float(x), 1)
    return 0.0 if v == 0 else v


def r2(x):
    v = round(float(x), 2)     # rain kept to 2 decimals so light drizzle isn't shown as a flat 0.0
    return 0.0 if v == 0 else v


def wdir_from_uv(u, v):
    return float((270.0 - np.degrees(np.arctan2(v, u))) % 360.0)


def boundary_rings(gdf):
    """List of (lon, lat) exterior/interior ring polylines for a WGS84 GeoDataFrame,
    used to overlay administrative borders (state, municipality) on the regional figure."""
    rings = []
    for geom in gdf.geometry:
        if geom is None:
            continue
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for p in polys:
            if p.geom_type != "Polygon":
                continue
            x, y = p.exterior.xy
            rings.append((np.asarray(x, float), np.asarray(y, float)))
            for hole in p.interiors:
                xi, yi = hole.xy
                rings.append((np.asarray(xi, float), np.asarray(yi, float)))
    return rings


def read_polys(path):
    g = gpd.read_file(path)
    return (g.set_crs("EPSG:4326") if g.crs is None else g.to_crs("EPSG:4326"))


def build_cells(lat, lon):
    """GeoDataFrame of WRF cell footprints (EPSG:4326) with cell_id = i*nlon + j."""
    lat_e, lon_e = cell_edges(lat), cell_edges(lon)
    geoms, cids = [], []
    for i in range(len(lat)):
        y0, y1 = sorted((lat_e[i], lat_e[i + 1]))
        for j in range(len(lon)):
            x0, x1 = sorted((lon_e[j], lon_e[j + 1]))
            geoms.append(shp_box(x0, y0, x1, y1)); cids.append(i * len(lon) + j)
    return gpd.GeoDataFrame({"cell_id": cids}, geometry=geoms, crs="EPSG:4326")


def weight_matrix(cells_wgs, polys_wgs, ncells):
    cg = cells_wgs.to_crs(EQ_AREA)
    pg = polys_wgs.to_crs(EQ_AREA).reset_index(drop=True)
    pg["pidx"] = range(len(pg))
    pieces = gpd.overlay(cg[["cell_id", "geometry"]], pg[["pidx", "geometry"]],
                         how="intersection", keep_geom_type=True)
    pieces["w"] = pieces.geometry.area
    W = np.zeros((len(pg), ncells))
    for cid, pidx, w in zip(pieces["cell_id"].astype(int), pieces["pidx"].astype(int), pieces["w"]):
        W[pidx, cid] += w
    rowsum = W.sum(axis=1)
    area = pg.geometry.area.values
    cov = np.divide(rowsum, area, out=np.zeros(len(pg)), where=area > 0)
    return W, rowsum, cov, area


def wmean(field, W, rowsum, T, ncells):
    flat = field.reshape(T, ncells)
    out = np.zeros((T, len(rowsum)))
    for t in range(T):
        out[t] = np.divide(W @ flat[t], rowsum, out=np.zeros(len(rowsum)), where=rowsum > 0)
    return out


def aggregate(polys_wgs, name_col, id_col, cells_win, fields, dt, T, ncells, vt, titlecase=False):
    """Return (json_list, summary_records, geojson_gdf) for a set of target polygons."""
    W, rowsum, cov, area = weight_matrix(cells_win, polys_wgs, ncells)
    rain_s = wmean(fields["rain"], W, rowsum, T, ncells)
    temp_s = wmean(fields["temp"], W, rowsum, T, ncells) if fields["temp"] is not None else None
    u_s = wmean(fields["u"], W, rowsum, T, ncells) if fields["u"] is not None else None
    v_s = wmean(fields["v"], W, rowsum, T, ncells) if fields["v"] is not None else None
    spd_s = np.hypot(u_s, v_s) if u_s is not None else None

    raw_names = polys_wgs[name_col].astype(str).tolist()
    names = [n.title() for n in raw_names] if titlecase else raw_names
    ids = polys_wgs[id_col].tolist() if id_col else list(range(1, len(polys_wgs) + 1))
    rain_total = rain_s.sum(axis=0) * dt
    rain_peak = rain_s.max(axis=0); rain_peak_i = rain_s.argmax(axis=0)
    n = len(polys_wgs)

    json_list, recs, gprops = [], [], {}
    tot_c, tmean_c, tmin_c, tmax_c, wmean_c, wmax_c, wdir_c = ([] for _ in range(7))
    for b in range(n):
        d = {"id": ids[b], "name": names[b], "area_km2": round(float(area[b] / 1e6), 2),
             "coverage_pct": round(float(cov[b] * 100), 1),
             "rain": {"total_mm": round(float(rain_total[b]), 2),
                      "peak_mm_h": round(float(rain_peak[b]), 2),
                      "peak_time": vt[int(rain_peak_i[b])],
                      "series": [round(float(rain_s[t, b]), 3) for t in range(T)]}}
        rec = {"id": ids[b], "name": names[b], "area_km2": round(float(area[b] / 1e6), 2),
               "coverage_pct": round(float(cov[b] * 100), 1),
               "rain_total_mm": round(float(rain_total[b]), 3),
               "rain_peak_mm_h": round(float(rain_peak[b]), 3)}
        tot_c.append(round(float(rain_total[b]), 3))
        if temp_s is not None:
            d["temp"] = {"mean": round(float(temp_s[:, b].mean()), 1),
                         "min": round(float(temp_s[:, b].min()), 1),
                         "max": round(float(temp_s[:, b].max()), 1),
                         "series": [round(float(temp_s[t, b]), 2) for t in range(T)]}
            rec.update(temp_mean_degC=d["temp"]["mean"], temp_min_degC=d["temp"]["min"], temp_max_degC=d["temp"]["max"])
            tmean_c.append(d["temp"]["mean"]); tmin_c.append(d["temp"]["min"]); tmax_c.append(d["temp"]["max"])
        if spd_s is not None:
            d["wind"] = {"mean_ms": round(float(spd_s[:, b].mean()), 2),
                         "max_ms": round(float(spd_s[:, b].max()), 2),
                         "dir_deg": round(wdir_from_uv(u_s[:, b].mean(), v_s[:, b].mean())),
                         "series": [round(float(spd_s[t, b]), 2) for t in range(T)]}
            rec.update(wind_mean_ms=d["wind"]["mean_ms"], wind_max_ms=d["wind"]["max_ms"], wind_dir_deg=d["wind"]["dir_deg"])
            wmean_c.append(d["wind"]["mean_ms"]); wmax_c.append(d["wind"]["max_ms"]); wdir_c.append(d["wind"]["dir_deg"])
        json_list.append(d); recs.append(rec)

    gj = polys_wgs.reset_index(drop=True).copy()
    gj["name"] = names
    gj["rain_total_mm"] = tot_c
    if temp_s is not None:
        gj["temp_mean_degC"] = tmean_c
    if spd_s is not None:
        gj["wind_mean_ms"] = wmean_c; gj["wind_dir_deg"] = wdir_c
    gj["coverage_pct"] = np.round(cov * 100, 1)
    return json_list, recs, gj


def regional_figure(lat, lon, fields, vt, out, overlays=None, run_time=None, tgt=None):
    """Reproduce the 6-panel wrf_joinville_sanity scientific figure (matplotlib PNG),
    over the full WRF domain, for the Previsão page. Regenerated every run by the pipeline.
    `overlays` = list of {rings,color,lw,alpha} faint administrative borders (state, city)
    drawn on the three map panels (b,d,f). Times shown are LOCAL (UTC-3, already applied to vt)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rain = fields["rain"]; temp = fields["temp"]; u = fields["u"]; v = fields["v"]
    T = rain.shape[0]
    tgt = (T // 2) if tgt is None else max(0, min(int(tgt), T - 1))   # maps (b,d,f): next forecast hour
    lbl = [s[5:16] for s in vt]                       # 'MM-DD HH:MM' (local)
    # series panels (a,c,e) show only a 24-h window from the update forward (legible x-axis);
    # the maps (b,d,f) keep the single next-hour snapshot at `tgt`.
    s0 = tgt; s1 = min(T, s0 + 24); nx = s1 - s0; xx = list(range(nx)); xr = lbl[s0:s1]
    def _xt(a):
        step = max(1, nx // 8)
        a.set_xticks(xx[::step]); a.set_xticklabels([xr[i] for i in xx[::step]], rotation=45, ha="right")
    have_t = temp is not None; have_w = u is not None
    xlim = (float(np.min(lon)), float(np.max(lon)))
    ylim = (float(np.min(lat)), float(np.max(lat)))
    mean_lat = 0.5 * (ylim[0] + ylim[1])
    geo_aspect = 1.0 / np.cos(np.deg2rad(mean_lat))   # equirectangular: 1° lat vs 1° lon·cos(lat)
    overlays = overlays or []

    def deco(a):
        """faint SC/Joinville borders on a map panel, clipped to the WRF box,
        with a true geographic aspect so shapes (and Joinville) are not flattened."""
        for ov in overlays:
            for lon_r, lat_r in ov["rings"]:
                a.plot(lon_r, lat_r, color=ov["color"], lw=ov["lw"], alpha=ov["alpha"], zorder=6)
        a.set_xlim(*xlim); a.set_ylim(*ylim)
        a.set_aspect(geo_aspect, adjustable="box")

    fig, ax = plt.subplots(3, 2, figsize=(13, 13))
    # (a) precip series
    ax[0, 0].plot(xx, rain[s0:s1].mean((1, 2)), "o-", label="box mean")
    ax[0, 0].plot(xx, rain[s0:s1].max((1, 2)), "s--", label="box max")
    ax[0, 0].set_title("(a) hourly precip · próximas 24 h"); ax[0, 0].set_ylabel("mm h$^{-1}$")
    ax[0, 0].legend(); _xt(ax[0, 0])
    # (b) precip map
    vmax = float(np.nanpercentile(rain, 99)) or 1
    im = ax[0, 1].pcolormesh(lon, lat, rain[tgt], vmin=0, vmax=vmax, cmap="viridis", shading="auto")
    deco(ax[0, 1])
    ax[0, 1].set_title(f"(b) precip @ {lbl[tgt]}"); plt.colorbar(im, ax=ax[0, 1])
    if have_t:
        ax[1, 0].plot(xx, temp[s0:s1].mean((1, 2)), "o-", color="#c0392b", label="box mean")
        ax[1, 0].fill_between(xx, temp[s0:s1].min((1, 2)), temp[s0:s1].max((1, 2)), color="#c0392b", alpha=0.15, label="min-max")
        ax[1, 0].set_title("(c) 2-m temperature · próximas 24 h"); ax[1, 0].set_ylabel("°C")
        ax[1, 0].legend(); _xt(ax[1, 0])
        im2 = ax[1, 1].pcolormesh(lon, lat, temp[tgt], cmap="RdYlBu_r", shading="auto")
        deco(ax[1, 1])
        ax[1, 1].set_title(f"(d) 2-m T @ {lbl[tgt]}"); plt.colorbar(im2, ax=ax[1, 1])
    else:
        for a in (ax[1, 0], ax[1, 1]): a.text(.5, .5, "no t2m", ha="center"); a.axis("off")
    if have_w:
        sp = np.hypot(u, v)
        ax[2, 0].plot(xx, sp[s0:s1].mean((1, 2)), "o-", color="#2c7fb8", label="box mean")
        ax[2, 0].plot(xx, sp[s0:s1].max((1, 2)), "s--", color="#2c7fb8", label="box max")
        ax[2, 0].set_title("(e) 10-m wind speed · próximas 24 h"); ax[2, 0].set_ylabel("m s$^{-1}$")
        ax[2, 0].legend(); _xt(ax[2, 0])
        im3 = ax[2, 1].pcolormesh(lon, lat, sp[tgt], cmap="YlGnBu", vmin=0, shading="auto")
        s = max(1, sp.shape[2] // 12)
        ax[2, 1].quiver(lon[::s], lat[::s], u[tgt, ::s, ::s], v[tgt, ::s, ::s], scale=200, width=0.003)
        deco(ax[2, 1])
        ax[2, 1].set_title(f"(f) 10-m wind @ {lbl[tgt]}"); plt.colorbar(im3, ax=ax[2, 1])
    else:
        for a in (ax[2, 0], ax[2, 1]): a.text(.5, .5, "no wind", ha="center"); a.axis("off")
    if overlays:
        # single caption for the border overlay, bottom-left of the precip map
        ax[0, 1].text(0.015, 0.02, "contornos: SC · Joinville", transform=ax[0, 1].transAxes,
                      fontsize=8, color="#222", ha="left", va="bottom",
                      bbox=dict(facecolor="white", alpha=0.65, edgecolor="none", pad=1.5))
    run_lbl = (f"rodada {run_time} UTC · " if run_time else "")
    fig.suptitle(f"CPTEC/INPE WRF AMS 7 km — Joinville domain · {run_lbl}horários locais (UTC−3)",
                 y=1.005, fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(str(out), dpi=110, bbox_inches="tight")
    plt.close(fig)


def regional_hourly_maps(lat, lon, fields, vt, lead_h, out_dir, overlays=None, run_time=None, idx=None, maxh=24):
    """Per-hour regional map images (the 3 map panels b/d/f, 1x3) for the interactive hour menu
    on the Previsão page. FIXED filenames wrf_reg_00.png..wrf_reg_NN.png -> OVERWRITTEN every run
    (the working tree / live site never accumulate). A manifest wrf_regional_hours.json lists which
    hours are valid this run. Colour scales are FIXED across the window so hours are comparable.
    Same look as the static figure's maps (viridis / RdYlBu_r / YlGnBu + quiver + faint borders)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rain = fields["rain"]; temp = fields["temp"]; u = fields["u"]; v = fields["v"]
    T = rain.shape[0]
    idx = [int(i) for i in (range(T) if idx is None else idx) if 0 <= int(i) < T][:maxh]
    if not idx:
        return 0
    ia = np.array(idx)
    lbl = [s[5:16] for s in vt]
    xlim = (float(np.min(lon)), float(np.max(lon))); ylim = (float(np.min(lat)), float(np.max(lat)))
    geo_aspect = 1.0 / np.cos(np.deg2rad(0.5 * (ylim[0] + ylim[1]))); overlays = overlays or []
    have_t = temp is not None; have_w = (u is not None and v is not None)
    sp = np.hypot(u, v) if have_w else None
    # fixed colour scales across the whole window (so the menu/animation is comparable hour-to-hour)
    rvmax = float(np.nanpercentile(rain[ia], 99)) or 1.0
    tvmin = float(np.nanmin(temp[ia])) if have_t else 0.0
    tvmax = float(np.nanmax(temp[ia])) if have_t else 1.0
    svmax = float(np.nanpercentile(sp[ia], 99)) if have_w else 1.0

    def deco(a):
        for ov in overlays:
            for lo_r, la_r in ov["rings"]:
                a.plot(lo_r, la_r, color=ov["color"], lw=ov["lw"], alpha=ov["alpha"], zorder=6)
        a.set_xlim(*xlim); a.set_ylim(*ylim); a.set_aspect(geo_aspect, adjustable="box")

    manifest = []
    for k, i in enumerate(idx):
        fig, ax = plt.subplots(1, 3, figsize=(15, 5.2))
        im = ax[0].pcolormesh(lon, lat, rain[i], vmin=0, vmax=rvmax, cmap="viridis", shading="auto")
        deco(ax[0]); ax[0].set_title(f"(b) chuva · +{int(lead_h[i])} h · {lbl[i]}")
        plt.colorbar(im, ax=ax[0], label="mm h$^{-1}$", fraction=0.046, pad=0.04)
        if have_t:
            im2 = ax[1].pcolormesh(lon, lat, temp[i], vmin=tvmin, vmax=tvmax, cmap="RdYlBu_r", shading="auto")
            deco(ax[1]); ax[1].set_title(f"(d) temperatura 2 m · +{int(lead_h[i])} h")
            plt.colorbar(im2, ax=ax[1], label="°C", fraction=0.046, pad=0.04)
        else:
            ax[1].text(.5, .5, "sem t2m", ha="center"); ax[1].axis("off")
        if have_w:
            im3 = ax[2].pcolormesh(lon, lat, sp[i], vmin=0, vmax=svmax, cmap="YlGnBu", shading="auto")
            s = max(1, sp.shape[2] // 12)
            ax[2].quiver(lon[::s], lat[::s], u[i, ::s, ::s], v[i, ::s, ::s], scale=200, width=0.003)
            deco(ax[2]); ax[2].set_title(f"(f) vento 10 m · +{int(lead_h[i])} h")
            plt.colorbar(im3, ax=ax[2], label="m s$^{-1}$", fraction=0.046, pad=0.04)
        else:
            ax[2].text(.5, .5, "sem vento", ha="center"); ax[2].axis("off")
        run_lbl = (f"rodada {run_time} UTC · " if run_time else "")
        fig.suptitle(f"CPTEC/INPE WRF AMS 7 km — Joinville · {run_lbl}{lbl[i]} (local, UTC−3)",
                     y=1.02, fontsize=12, fontweight="bold")
        plt.tight_layout()
        fn = f"wrf_reg_{k:02d}.png"
        plt.savefig(str(out_dir / fn), dpi=95, bbox_inches="tight"); plt.close(fig)
        manifest.append({"i": k, "lead_h": int(lead_h[i]), "valid_time": vt[i], "file": fn})
    (out_dir / "wrf_regional_hours.json").write_text(
        json.dumps({"run_time": run_time, "generated_at": vt[0] if vt else "", "hours": manifest},
                   ensure_ascii=False), encoding="utf-8")
    return len(manifest)


def grid_block(lat, lon, fields, T):
    """Full-box grid fields for the regional patchwork map."""
    block = {"lat": [round(float(x), 4) for x in lat], "lon": [round(float(x), 4) for x in lon], "vars": {}}
    rain = fields["rain"]
    block["vars"]["rain"] = {"unit": "mm",
        "grid_accum": [[r2(x) for x in row] for row in rain.sum(axis=0)],
        "grid_hourly": [[[r2(x) for x in row] for row in rain[t]] for t in range(T)],
        "accum_max": r2(float(rain.sum(axis=0).max())), "hourly_max": r2(float(rain.max()))}
    if fields["temp"] is not None:
        temp = fields["temp"]
        block["vars"]["temp"] = {"unit": "°C",
            "grid_hourly": [[[r1(x) for x in row] for row in temp[t]] for t in range(T)],
            "min": r1(float(temp.min())), "max": r1(float(temp.max()))}
    if fields["u"] is not None:
        u, v = fields["u"], fields["v"]; spd = np.hypot(u, v)
        block["vars"]["wind"] = {"unit": "m/s",
            "u_hourly": [[[r1(x) for x in row] for row in u[t]] for t in range(T)],
            "v_hourly": [[[r1(x) for x in row] for row in v[t]] for t in range(T)],
            "spd_hourly": [[[r1(x) for x in row] for row in spd[t]] for t in range(T)],
            "spd_max": r1(float(spd.max()))}
    return block


def write_grid_geojson(lat, lon, fields, dt, T, out):
    """WRF cells (full box) as a fishnet GeoJSON with per-cell forecast summary."""
    rain = fields["rain"]; temp = fields["temp"]; u = fields["u"]; v = fields["v"]
    accum = rain.sum(axis=0) * dt
    feats = []
    lat_e, lon_e = cell_edges(lat), cell_edges(lon)
    r3 = lambda x: round(float(x), 3)                 # ~110 m — plenty for a 7 km grid; keeps the file small
    for i in range(len(lat)):
        y0, y1 = sorted((r3(lat_e[i]), r3(lat_e[i + 1])))
        for j in range(len(lon)):
            x0, x1 = sorted((r3(lon_e[j]), r3(lon_e[j + 1])))
            props = {"i": i, "j": j, "lat": round(float(lat[i]), 4), "lon": round(float(lon[j]), 4),
                     "rain_total_mm": round(float(accum[i, j]), 2)}
            if temp is not None:
                props["temp_mean_degC"] = round(float(temp[:, i, j].mean()), 1)
                props["temp_min_degC"] = round(float(temp[:, i, j].min()), 1)
                props["temp_max_degC"] = round(float(temp[:, i, j].max()), 1)
            if u is not None:
                sp = np.hypot(u[:, i, j], v[:, i, j])
                props["wind_mean_ms"] = round(float(sp.mean()), 2)
                props["wind_dir_deg"] = round(wdir_from_uv(u[:, i, j].mean(), v[:, i, j].mean()))
            feats.append({"type": "Feature",
                          "geometry": {"type": "Polygon",
                                       "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]},
                          "properties": props})
    fc = {"type": "FeatureCollection", "name": "wrf_grid",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
          "features": feats}
    out.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return len(feats)


def build(nc_path, basins_path, bairros_path, limite_path, outdir):
    ds = xr.open_dataset(nc_path).sortby("latitude").sortby("longitude")
    if "precip_mm_h" not in ds:
        raise SystemExit(f"{nc_path}: no 'precip_mm_h' (got {list(ds.data_vars)})")
    lat_full = ds["latitude"].values.astype(float)
    lon_full = ds["longitude"].values.astype(float)
    fh = ds["precip_mm_h"]["forecast_hour"].values.astype(float)
    # WRF valid_time is UTC → show LOCAL time (Joinville = UTC-3, no DST since 2019),
    # to match the rest of the dashboard (loggers record local standard time)
    TZ_OFFSET_H = 3
    if "valid_time" in ds:
        vt = [str(np.datetime64(v) - np.timedelta64(TZ_OFFSET_H, "h"))[:16].replace("T", " ")
              for v in ds["valid_time"].values]
    else:
        vt = [f"+{int(h)}h" for h in fh]
    dt = float(np.median(np.diff(fh))) if len(fh) > 1 else 1.0
    T = len(fh)
    # regional maps (b,d,f): show the NEXT forecast hour from generation time — a true forecast
    # snapshot, not the middle of the run. Falls back to mid-run if valid_time is unavailable.
    tgt_next = None; future = None
    if "valid_time" in ds:
        vt_utc = ds["valid_time"].values.astype("datetime64[s]")
        now_utc = np.datetime64(datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0), "s")
        future = np.where(vt_utc >= now_utc)[0]
        tgt_next = int(future[0]) if future.size else int(T - 1)

    def full(name):
        return np.nan_to_num(ds[name].values.astype(float), nan=0.0) if name in ds else None
    fields_full = {"rain": full("precip_mm_h"), "temp": full("t2m_degC"),
                   "u": full("u10_ms"), "v": full("v10_ms")}

    outdir.mkdir(parents=True, exist_ok=True)
    basins = read_polys(basins_path)
    bairros = read_polys(bairros_path) if Path(bairros_path).exists() else None
    lim = read_polys(limite_path) if Path(limite_path).exists() else None

    # --- crop window for aggregation & the local map (basins ∪ bairros ∪ municipality) ---
    bnds = [basins.total_bounds]
    if bairros is not None: bnds.append(bairros.total_bounds)
    if lim is not None: bnds.append(lim.total_bounds)
    bnds = np.array(bnds)
    minx, miny = bnds[:, 0].min(), bnds[:, 1].min()
    maxx, maxy = bnds[:, 2].max(), bnds[:, 3].max()
    ilat = np.where((lat_full >= miny - MARGIN_DEG) & (lat_full <= maxy + MARGIN_DEG))[0]
    ilon = np.where((lon_full >= minx - MARGIN_DEG) & (lon_full <= maxx + MARGIN_DEG))[0]
    if len(ilat) < 2 or len(ilon) < 2:
        ilat, ilon = np.arange(len(lat_full)), np.arange(len(lon_full))
    latw, lonw = lat_full[ilat], lon_full[ilon]
    nlatw, nlonw = len(latw), len(lonw)
    ncw = nlatw * nlonw

    def win(name):
        a = fields_full[name]
        return None if a is None else a[:, ilat][:, :, ilon]
    fields_win = {k: win(k) for k in fields_full}
    cells_win = build_cells(latw, lonw)

    # --- aggregate basins & bairros ---
    bname = "Nomes" if "Nomes" in basins.columns else basins.columns[0]
    bid = "ID" if "ID" in basins.columns else None
    basins_json, basins_recs, basins_gj = aggregate(basins, bname, bid, cells_win, fields_win, dt, T, ncw, vt)
    bairros_json = bairros_recs = bairros_gj = None
    if bairros is not None:
        nname = "Nome_Bairr" if "Nome_Bairr" in bairros.columns else bairros.columns[0]
        bairros_json, bairros_recs, bairros_gj = aggregate(bairros, nname, None, cells_win, fields_win, dt, T, ncw, vt, titlecase=True)

    run_time = str(ds.attrs.get("run_time", "")) or (vt[0] if vt else "")
    source = str(ds.attrs.get("source", "CPTEC/INPE WRF AMS 7km"))
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    has = {"rain": True, "temp": fields_full["temp"] is not None, "wind": fields_full["u"] is not None}

    # --- write CSVs + GeoJSONs ---
    def order(df):
        return df.sort_values("rain_total_mm", ascending=False)
    bdf = order(pd.DataFrame(basins_recs)); bdf["run_time"] = run_time; bdf["window"] = f"{vt[0]} .. {vt[-1]}"; bdf["source"] = source
    bdf.to_csv(outdir / "wrf_basins.csv", index=False)
    basins_gj.to_file(outdir / "wrf_basins.geojson", driver="GeoJSON")
    if bairros_recs is not None:
        rdf = order(pd.DataFrame(bairros_recs)); rdf["run_time"] = run_time; rdf["window"] = f"{vt[0]} .. {vt[-1]}"; rdf["source"] = source
        rdf.to_csv(outdir / "wrf_bairros.csv", index=False)
        bairros_gj.to_file(outdir / "wrf_bairros.geojson", driver="GeoJSON")

    # tidy per-basin hourly
    rows = []
    for b in basins_json:
        acc = 0.0
        for t in range(T):
            acc += b["rain"]["series"][t] * dt
            row = {"basin": b["name"], "id": b["id"], "valid_time": vt[t], "lead_h": int(fh[t]),
                   "precip_mm_h": b["rain"]["series"][t], "accum_mm": round(acc, 3)}
            if "temp" in b: row["t2m_degC"] = b["temp"]["series"][t]
            if "wind" in b: row["wspd_ms"] = b["wind"]["series"][t]
            rows.append(row)
    pd.DataFrame(rows).to_csv(outdir / "wrf_basins_hourly.csv", index=False)

    ncell = write_grid_geojson(lat_full, lon_full, fields_full, dt, T, outdir / "wrf_grid.geojson")

    # --- faint admin borders for the regional figure (real IBGE-derived outlines) ---
    overlays = []
    geo_states = ROOT / "site" / "data" / "geo" / "estados_sul.geojson"
    if geo_states.exists():
        try:
            st = read_polys(geo_states)
            overlays.append({"rings": boundary_rings(st), "color": "#3a3f47", "lw": 0.8, "alpha": 0.35})
        except Exception as e:
            print(f"[wrf] state overlay skipped: {e}")
    if lim is not None:
        overlays.append({"rings": boundary_rings(lim), "color": "#111418", "lw": 1.1, "alpha": 0.6})

    # --- regional 6-panel scientific figure (PNG, auto-updated by the pipeline) ---
    try:
        regional_figure(lat_full, lon_full, fields_full, vt, outdir / "wrf_regional.png",
                        overlays=overlays, run_time=run_time, tgt=tgt_next)
        have_fig = True
    except Exception as e:      # matplotlib missing / plotting error must not break the data build
        print(f"[wrf] regional figure skipped: {e}")
        have_fig = False

    # --- per-hour regional maps for the interactive hour menu (fixed names, overwritten each run) ---
    n_reg_hours = 0
    try:
        fut = future.tolist() if (isinstance(future, np.ndarray) and future.size) else list(range(T))
        n_reg_hours = regional_hourly_maps(lat_full, lon_full, fields_full, vt, fh, outdir,
                                           overlays=overlays, run_time=run_time, idx=fut, maxh=24)
    except Exception as e:
        print(f"[wrf] hourly regional maps skipped: {e}")

    # --- forecast JSON: local (window) grid + basins + bairros ---
    local = grid_block(latw, lonw, fields_win, T)
    doc = {"source": source, "run_time": run_time, "generated_at": gen,
           "domain": str(ds.attrs.get("domain", "")), "dt_hours": dt, "n_steps": T,
           "tz": "America/Sao_Paulo (UTC-3)", "time_note": "valid_times em hora local de Joinville (UTC-3)",
           "valid_times": vt, "lead_h": [int(x) for x in fh], "has": has,
           "has_figure": have_fig,
           "lat": local["lat"], "lon": local["lon"], "vars": local["vars"],
           "basins": basins_json}
    if bairros_json is not None:
        doc["bairros"] = bairros_json
    (outdir / "wrf_forecast.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    return {"basins": len(basins_json), "bairros": (len(bairros_json) if bairros_json else 0),
            "T": T, "win": (nlatw, nlonw), "full": (len(lat_full), len(lon_full)), "cells_geojson": ncell,
            "have": list(local["vars"].keys()),
            "cov_basin": (float(basins_gj["coverage_pct"].min()), float(basins_gj["coverage_pct"].max())),
            "run_time": run_time, "window": (vt[0], vt[-1]) if vt else None,
            "rain_totals": {b["name"]: b["rain"]["total_mm"] for b in basins_json}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nc")
    ap.add_argument("--basins", default=str(ROOT / "site" / "data" / "bacias.geojson"))
    ap.add_argument("--bairros", default=str(ROOT / "site" / "data" / "bairros.geojson"))
    ap.add_argument("--limite", default=str(ROOT / "site" / "data" / "limite.geojson"))
    ap.add_argument("--outdir", default=str(ROOT / "site" / "data"))
    a = ap.parse_args()
    info = build(Path(a.nc), Path(a.basins), Path(a.bairros), Path(a.limite), Path(a.outdir))
    print(f"[wrf] vars={info['have']} basins={info['basins']} bairros={info['bairros']} "
          f"steps={info['T']} win={info['win']} full={info['full']} grid_cells={info['cells_geojson']}")
    print(f"[wrf] basin coverage {info['cov_basin'][0]:.1f}%..{info['cov_basin'][1]:.1f}% | run {info['run_time']} window {info['window']}")
    for k, v in sorted(info["rain_totals"].items(), key=lambda kv: -kv[1]):
        print(f"    {v:7.2f} mm  {k}")


if __name__ == "__main__":
    main()
